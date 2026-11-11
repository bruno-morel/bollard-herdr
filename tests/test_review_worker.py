"""Run harmless local checks; replace only model/auth/network-facing boundaries."""

import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess as sp
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "review_worker", Path(__file__).with_name("repo-review.py")
)
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


class WorkerFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.root = base / "repo"
        self.root.mkdir()
        self.runtime = base / "state/reviews/repo-key/demo"
        self.runtime.mkdir(parents=True)
        self.artifacts = self.root / "scratch/review"
        self.artifacts.mkdir(parents=True)
        self.config = {
            "version": 1,
            "base": "HEAD",
            "checks": [
                {
                    "id": "browser",
                    "kind": "e2e",
                    "argv": [sys.executable, "-c", 'print("one test passed")'],
                    "timeout": 3,
                }
            ],
            "criteria": [
                {
                    "id": "AC1",
                    "requirement": "User can see the updated title.",
                    "checks": ["browser"],
                }
            ],
        }
        self.fp = {"head": "abc", "digest": "digest", "merge_base": "abc"}
        self.state = dict(
            root=str(self.root),
            stream="demo",
            config=self.config,
            artifacts=str(self.artifacts),
            token="request",
            state="preflight",
            fingerprint=self.fp,
            cycle="cycle",
            attempt=1,
            calls=0,
        )
        self.result = dict(
            verdict="verified",
            summary="The focused browser assertion covers the title.",
            requirements_covered=True,
            tests_meaningful=True,
            criteria=[
                dict(
                    id="AC1",
                    status="pass",
                    evidence="browser: assertion passed on the current title",
                )
            ],
            findings=[],
            limitations=[],
        )
        self.model_argv = []
        self.real_process = R.process
        self.patches = [
            patch.object(R, "fingerprint", return_value=self.fp),
            patch.object(R, "load_config", return_value=self.config),
            patch.object(
                R, "git", side_effect=lambda *a, **k: b"" if k.get("raw") else ""
            ),
            patch.object(R, "auth", return_value=dict(os.environ)),
            patch.dict(os.environ, {"HC_TERMINAL_ID": ""}),
        ]
        for guard in self.patches:
            guard.start()
            self.addCleanup(guard.stop)

    def run_worker(self, code=0, mutate=False, rerun=False):
        R.write(self.runtime / "state.json", self.state)
        R.write(self.runtime / "job.json", {})

        def process(argv, root, log, seconds, **kwargs):
            if argv[0] not in ("claude", "codex", "cursor"):
                return self.real_process(argv, root, log, seconds, **kwargs)
            self.model_argv.append(argv)
            # Budget is reserved before any model execution, including failures.
            self.assertEqual(R.read(self.runtime / "state.json")["calls"], 1)
            self.assertEqual(seconds, R.CLAUDE_SECONDS)
            if rerun:
                row = R.check(root, self.config, "browser", self.artifacts, "claude-1")
                R.write(self.artifacts / "rerun-1.json", row)
            if argv[0] == "codex":
                (self.artifacts / "result.json").write_text(json.dumps(self.result))
            else:
                log.write_text(
                    json.dumps(
                        {
                            "subtype": "success",
                            "structured_output": self.result,
                            "result": json.dumps(self.result),
                        }
                    )
                )
            if mutate:
                R.fingerprint.return_value = dict(self.fp, digest="changed")
            return code

        with patch.object(
            R, "process", side_effect=process
        ), contextlib.redirect_stdout(io.StringIO()):
            R.worker(self.runtime, "request")
        return R.read(self.runtime / "state.json")


class ReviewWorker(WorkerFixture):
    def test_other_reviewers_use_same_budget_and_verdict_checks(self):
        for reviewer in ("codex", "cursor"):
            with self.subTest(reviewer=reviewer), patch.object(
                R.agents, "executable", return_value=reviewer
            ), patch.object(R, "review_env", return_value=dict(os.environ)):
                self.state.update(reviewer=reviewer, implemented_by="claude")
                state = self.run_worker()
                self.assertEqual(state["state"], "verified")
                self.assertEqual(state["calls"], 1)
                self.assertEqual(self.model_argv[-1][0], reviewer)
                state = self.run_worker(code=1)
                self.assertEqual(state["state"], "incomplete")
                self.assertEqual(state["calls"], 1)

    def test_same_or_unknown_implementer_refuses_review(self):
        for provider in R.agents.AGENTS:
            with self.assertRaisesRegex(RuntimeError, "different"):
                R.independent(provider, provider)
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            R.independent("claude", None)

    def test_saved_work_provider_cannot_be_overridden(self):
        saved = (
            self.runtime.parents[2]
            / "agents"
            / self.runtime.parent.name
            / self.runtime.name
            / "work.agent"
        )
        saved.parent.mkdir(parents=True)
        saved.write_text("codex\n")
        self.assertEqual(R.implementation_agent(self.runtime), "codex")
        with self.assertRaisesRegex(RuntimeError, "disagrees"):
            R.implementation_agent(self.runtime, "cursor")

    def test_rotating_provider_never_resets_attempt_budget(self):
        for name in R.agents.AGENTS:
            state = dict(cycle="same", calls=2, reviewer=name, state="incomplete")
            with self.assertRaisesRegex(RuntimeError, "both review attempts"):
                R.reserve(state, True, False)

    def test_passing_checks_use_bounded_sonnet_and_keep_rerun_evidence(self):
        state = self.run_worker(rerun=True)
        self.assertEqual(state["state"], "verified")
        self.assertEqual(len(state["checks"]), 2)
        self.assertNotEqual(state["checks"][0]["log"], state["checks"][1]["log"])
        argv = self.model_argv[0]
        for flag, value in (
            ("--model", "sonnet"),
            ("--effort", "medium"),
            ("--max-turns", str(R.MAX_TURNS)),
        ):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        self.assertIn("--no-session-persistence", argv)
        self.assertTrue((self.root / state["report"]).is_file())

    def test_failing_check_uses_no_claude_allowance(self):
        self.config["checks"][0]["argv"] = [sys.executable, "-c", "raise SystemExit(2)"]
        state = self.run_worker()
        self.assertEqual(state["state"], "changes-required")
        self.assertEqual(state["calls"], 0)
        self.assertEqual(self.model_argv, [])
        R.auth.assert_not_called()

    def test_source_changed_before_start_runs_nothing(self):
        R.fingerprint.return_value = dict(self.fp, digest="changed")
        state = self.run_worker()
        self.assertEqual(state["state"], "incomplete")
        self.assertEqual(state["checks"], [])
        self.assertEqual(state["calls"], 0)

    def test_model_failure_consumes_one_call_and_never_passes(self):
        state = self.run_worker(code=1)
        self.assertEqual(state["state"], "incomplete")
        self.assertEqual(state["calls"], 1)

    def test_source_changed_during_review_is_stale(self):
        self.assertEqual(self.run_worker(mutate=True)["state"], "stale")

    def test_verdict_with_unresolved_findings_is_not_verified(self):
        self.result["findings"] = ["Missing failure-path assertion"]
        self.assertEqual(self.run_worker()["state"], "changes-required")


class BoundedProcess(unittest.TestCase):
    def test_timeout_cleans_marker_and_reaps_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "out.log"
            code = R.process(
                [sys.executable, "-c", "import time; time.sleep(30)"], root, log, 0.05
            )
            self.assertEqual(code, -1)
            self.assertEqual(list(root.glob(".active-*")), [])

    def test_completed_command_cannot_bypass_output_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "out.log"
            code = R.process(
                [sys.executable, "-c", 'import sys; sys.stdout.write("x" * 8100000)'],
                root,
                log,
                3,
            )
            self.assertEqual(code, -1)


class TestWorker(WorkerFixture):
    def run_tests(self, fail_check=False, changed=False):
        spec = importlib.util.spec_from_file_location(
            "test_worker", Path(__file__).with_name("repo-tests.py")
        )
        T = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(T)
        runtime = self.runtime.parents[2] / "tests/repo-key/demo"
        packet = self.root / "docs/handoffs/demo"
        packet.mkdir(parents=True)
        config = copy.deepcopy(self.config)
        if fail_check:
            config["checks"][0]["argv"] = [sys.executable, "-c", "raise SystemExit(2)"]
        R.write(packet / "tests-input.json", config)
        R.write(
            runtime / "state.json",
            dict(state="queued", token="tests", fingerprint=self.fp, results=[]),
        )
        ctx = (self.root, "demo", runtime, self.runtime, packet, "repo-key")
        real_run = sp.run

        def environment(argv, **kwargs):
            if str(argv[0]).endswith("/work"):
                self.assertEqual(argv[1:], ["_herdr-env", "demo"])
                return sp.CompletedProcess(argv, 0, "{}", "")
            return real_run(argv, **kwargs)

        fingerprints = [
            self.fp,
            self.fp,
            dict(self.fp, digest="changed") if changed else self.fp,
        ]
        with patch.object(T, "context", return_value=ctx), patch.object(
            T, "fingerprint", side_effect=fingerprints
        ), patch.object(T.R, "scratch"), patch.object(
            T.R, "auth", side_effect=AssertionError("No Claude for tests")
        ), patch.object(
            sp, "run", side_effect=environment
        ), patch.dict(
            os.environ, {}, clear=False
        ), contextlib.redirect_stdout(
            io.StringIO()
        ):
            T.worker("demo", "tests")
        return R.read(runtime / "state.json")

    def test_runs_project_command_and_preserves_evidence(self):
        state = self.run_tests()
        self.assertEqual(state["state"], "passed")
        self.assertEqual(state["results"][0]["exit_code"], 0)
        self.assertTrue((self.root / state["results"][0]["log"]).is_file())

    def test_failing_project_command_is_failed(self):
        state = self.run_tests(fail_check=True)
        self.assertEqual(state["state"], "failed")
        self.assertEqual(state["results"][0]["exit_code"], 2)

    def test_changed_source_after_checks_is_stale(self):
        self.assertEqual(self.run_tests(changed=True)["state"], "stale")
