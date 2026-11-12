"""Completion consumes recorded evidence; it must never buy another review."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess as sp
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "completion", Path(__file__).with_name("repo-completion.py")
)
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)


class Completion(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.root = base / "repo"
        self.root.mkdir()
        self.packet = self.root / "docs/handoffs/demo"
        self.packet.mkdir(parents=True)
        self.runtime = base / "runtime/tests"
        self.review = base / "runtime/review"
        self.ctx = (
            self.root,
            "demo",
            self.runtime,
            self.review,
            self.packet,
            "repo-key",
        )
        self.plan = dict(
            version=1,
            risk="low",
            scope="Change the title spacing",
            rationale="Local and reversible styling",
            coverage="Focused browser assertion",
            checks=["browser"],
            limitations=[],
        )
        self.config = dict(
            version=1,
            checks=[dict(id="browser", kind="e2e", argv=["npm", "test"], timeout=60)],
        )
        self.save_plan()
        C.R.write(self.packet / "tests-input.json", self.config)
        (self.root / ".gitignore").write_text("/scratch/\n")
        (self.root / "app.txt").write_text("source\n")
        self.git("init", "-q", "-b", "codex/demo")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        )
        self.log = self.root / "scratch/browser.log"
        self.log.parent.mkdir()
        self.log.write_text("one browser assertion passed\n")
        self.row = dict(
            id="browser",
            argv=["npm", "test"],
            exit_code=0,
            log="scratch/browser.log",
            sha256=hashlib.sha256(self.log.read_bytes()).hexdigest(),
        )
        self.save_pass()
        for obj, name in ((C.T, "launch"), (C.R, "launch"), (C.R, "auth")):
            guard = patch.object(
                obj, name, side_effect=AssertionError("Completion must not launch work")
            )
            guard.start()
            self.addCleanup(guard.stop)

    def git(self, *args):
        return sp.check_output(["git", "-C", str(self.root), *args], stderr=sp.STDOUT)

    def save_plan(self):
        C.R.write(self.packet / "validation-plan.json", self.plan)

    def save_pass(self, rows=None):
        config, _ = C.T.config(self.root, "demo")
        C.R.write(
            self.runtime / "state.json",
            dict(
                state="passed",
                token="fixture-run",
                head=self.git("rev-parse", "HEAD").decode().strip(),
                fingerprint=C.T.fingerprint(self.root, "demo", config),
                results=rows if rows is not None else [self.row],
            ),
        )

    def test_low_risk_accepts_one_focused_check_without_review_or_writes(self):
        before = {p: p.read_bytes() for p in self.runtime.rglob("*") if p.is_file()}
        result = C.snapshot(self.ctx)
        self.assertEqual(result["state"], "completed")
        self.assertFalse(result["independent_review"])
        self.assertEqual(result["checks"][0]["status"], "passed")
        self.assertEqual(
            before, {p: p.read_bytes() for p in self.runtime.rglob("*") if p.is_file()}
        )

    def test_visual_assessment_keeps_one_focused_check_and_no_review(self):
        self.plan.update(change_type="visual", behavior_changes=[], validation_scope="focused")
        self.save_plan()
        self.save_pass()
        result = C.evaluate(self.ctx)
        self.assertEqual(result["state"], "completed")
        self.assertFalse(result["independent_review"])

    def test_contradictory_visual_and_behavioral_assessments_block(self):
        for change, risk, behaviors in (
            ("visual", "low", ["Changed dialog focus restoration"]),
            ("visual", "medium", []),
            ("behavioral", "low", ["Changed dialog focus restoration"]),
            ("mixed", "medium", []),
            ("visual", "low", "none"),
            ("unassessed", "low", []),
        ):
            with self.subTest(change=change, risk=risk, behaviors=behaviors):
                self.plan.update(change_type=change, risk=risk, behavior_changes=behaviors,
                                 validation_scope="focused")
                self.save_plan()
                with self.assertRaises(RuntimeError):
                    C.assessment(self.root, "demo")

    def test_broad_scope_needs_reason_but_required_regression_is_allowed(self):
        self.plan.update(change_type="visual", behavior_changes=[], validation_scope="broad")
        self.save_plan()
        with self.assertRaisesRegex(RuntimeError, "broad_reason"):
            C.assessment(self.root, "demo")
        self.plan["broad_reason"] = "Repository policy requires its complete browser suite."
        self.save_plan()
        self.save_pass()
        self.assertEqual(C.evaluate(self.ctx)["state"], "completed")

    def test_behavioral_scope_retains_review_requirement_and_rejects_static_only(self):
        self.plan.update(change_type="behavioral", risk="medium",
                         behavior_changes=["Changed dialog focus restoration"],
                         validation_scope="focused")
        self.save_plan()
        self.save_pass()
        with self.assertRaisesRegex(RuntimeError, "independent review"):
            C.evaluate(self.ctx)
        self.plan["review_deferred_reason"] = "Independent review pending before merge; no approval claimed."
        self.save_plan()
        self.save_pass()
        self.assertEqual(C.evaluate(self.ctx)["state"], "completed-with-limitations")
        self.config["checks"][0]["kind"] = "static"
        C.R.write(self.packet / "tests-input.json", self.config)
        self.save_pass()
        with self.assertRaisesRegex(RuntimeError, "static checks alone"):
            C.evaluate(self.ctx)

    def test_source_and_command_changes_make_results_stale(self):
        for path in (self.root / "app.txt", self.packet / "tests-input.json"):
            with self.subTest(path=path.name):
                old = path.read_bytes()
                if path.suffix == ".json":
                    changed = copy.deepcopy(self.config)
                    changed["checks"][0]["argv"] = ["npm", "run", "other"]
                    C.R.write(path, changed)
                else:
                    path.write_text("changed\n")
                self.assertEqual(C.snapshot(self.ctx)["state"], "blocked")
                path.write_bytes(old)

    def test_missing_changed_and_symlink_logs_block_completion(self):
        self.log.write_text("tampered\n")
        self.assertEqual(C.snapshot(self.ctx)["state"], "blocked")
        self.log.unlink()
        self.assertEqual(C.snapshot(self.ctx)["state"], "blocked")
        self.log.symlink_to(self.root / "app.txt")
        self.assertEqual(C.snapshot(self.ctx)["state"], "blocked")

    def test_failed_unselected_result_cannot_be_hidden(self):
        self.save_pass([self.row, dict(self.row, id="other", exit_code=1)])
        self.assertEqual(C.snapshot(self.ctx)["state"], "blocked")

    def test_duplicate_evidence_is_rejected(self):
        self.save_pass([self.row, self.row])
        self.assertEqual(C.snapshot(self.ctx)["state"], "blocked")

    def test_missing_configured_result_is_not_a_completed_run(self):
        self.config["checks"].append(
            dict(id="second", kind="unit", argv=["npm", "run", "unit"])
        )
        C.R.write(self.packet / "tests-input.json", self.config)
        self.save_pass()
        self.assertEqual(C.snapshot(self.ctx)["state"], "blocked")

    def test_boolean_exit_code_is_not_a_process_success(self):
        self.save_pass([dict(self.row, exit_code=False)])
        self.assertEqual(C.snapshot(self.ctx)["state"], "blocked")

    def test_medium_requires_review_or_explicit_limitations(self):
        self.plan["risk"] = "medium"
        self.save_plan()
        self.save_pass()
        self.assertEqual(C.snapshot(self.ctx)["state"], "blocked")
        self.plan["review_deferred_reason"] = (
            "Human review scheduled before merging this change."
        )
        self.save_plan()
        self.save_pass()
        self.assertEqual(C.snapshot(self.ctx)["state"], "completed-with-limitations")
        with self.assertRaises(RuntimeError):
            C.evaluate(self.ctx, require_review=True)

    def test_outstanding_review_cannot_be_bypassed_with_passing_tests(self):
        for state in ("changes-required", "incomplete", "preflight", "reviewing"):
            with self.subTest(state=state):
                C.R.write(self.review / "state.json", dict(state=state))
                self.assertEqual(C.snapshot(self.ctx)["state"], "blocked")

    def test_invalid_risk_controls_return_actionable_status(self):
        self.plan.update(risk="high", risk_controls=17)
        self.save_plan()
        self.save_pass()
        result = C.snapshot(self.ctx)
        self.assertEqual(result["state"], "blocked")
        self.assertTrue(any("risk_controls" in s for s in result["missing"]))

    def test_record_receipt_then_change_source_invalidates_completion(self):
        result = C.snapshot(self.ctx, record=True)
        self.assertEqual(result["state"], "completed")
        receipt = self.runtime / "completion.json"
        before = receipt.read_bytes()
        (self.root / "app.txt").write_text("changed\n")
        self.assertEqual(C.snapshot(self.ctx, record=True)["state"], "blocked")
        self.assertEqual(receipt.read_bytes(), before)

    def test_verified_review_satisfies_high_risk_without_another_call(self):
        self.plan.update(
            risk="high",
            risk_controls="Affected storage paths tested; restore from backup on failure.",
        )
        self.save_plan()
        config = dict(
            self.config,
            base="HEAD",
            criteria=[
                dict(
                    id="AC1",
                    requirement="The title remains visible after reload.",
                    checks=["browser"],
                )
            ],
        )
        C.R.write(self.packet / "review-input.json", config)
        (self.packet / "acceptance.md").write_text(
            "The title stays visible after reload.\n"
        )
        (self.packet / "implementation.md").write_text("Adjust title spacing only.\n")
        state = dict(
            state="verified",
            calls=2,
            checks=[self.row],
            fingerprint=C.R.fingerprint(self.root, "demo", config),
        )
        C.R.write(self.review / "state.json", state)
        before = (self.review / "state.json").read_bytes()
        self.assertEqual(
            C.evaluate(self.ctx, require_review=True)["state"], "completed"
        )
        self.assertEqual(C.snapshot(self.ctx)["evidence_source"], "review")
        self.assertEqual((self.review / "state.json").read_bytes(), before)
        self.log.write_text("changed log\n")
        self.assertEqual(C.snapshot(self.ctx)["state"], "blocked")

    def test_scratch_output_does_not_invalidate_current_results(self):
        (self.log.parent / "unrelated.txt").write_text("temporary rendering\n")
        self.assertEqual(C.snapshot(self.ctx)["state"], "completed")

    def test_failed_run_shows_passing_row_but_never_completion(self):
        self.config["checks"].append(
            dict(id="second", kind="unit", argv=["npm", "run", "unit"])
        )
        C.R.write(self.packet / "tests-input.json", self.config)
        self.save_pass(
            [
                self.row,
                dict(self.row, id="second", argv=["npm", "run", "unit"], exit_code=1),
            ]
        )
        state = C.R.read(self.runtime / "state.json")
        state["state"] = "failed"
        C.R.write(self.runtime / "state.json", state)
        result = C.snapshot(self.ctx)
        self.assertEqual(result["state"], "blocked")
        self.assertEqual(result["checks"][0]["status"], "passed")


class ReviewAllowance(unittest.TestCase):
    def test_follow_up_keeps_existing_budget_and_requires_explicit_new_cycle(self):
        one = dict(cycle="existing", calls=1, state="changes-required", rounds=[])
        self.assertEqual(C.R.reserve(one, True, False), one)
        with self.assertRaises(RuntimeError):
            C.R.reserve(one, False, False)
        used = dict(one, calls=2)
        with self.assertRaises(RuntimeError):
            C.R.reserve(used, True, False)
        fresh = C.R.reserve(used, False, True)
        self.assertEqual(fresh["calls"], 0)
        self.assertNotEqual(fresh["cycle"], used["cycle"])
        self.assertEqual(used["calls"], 2)

    def test_new_cycle_cannot_replace_active_review(self):
        for state in ("preflight", "reviewing"):
            with self.subTest(state=state), self.assertRaises(RuntimeError):
                C.R.reserve(dict(cycle="busy", calls=1, state=state), False, True)


class ReviewRerunEvidence(unittest.TestCase):
    def test_review_accepts_distinct_passing_attempts_but_checks_every_log(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = []
            for name in ("first.log", "rerun.log"):
                (root / name).write_text("passed\n")
                rows.append(
                    dict(
                        id="browser",
                        argv=["test"],
                        exit_code=0,
                        log=name,
                        sha256=hashlib.sha256((root / name).read_bytes()).hexdigest(),
                    )
                )
            args = (
                root,
                {"checks": ["browser"]},
                {"state": "verified"},
                {"checks": [{"id": "browser", "argv": ["test"]}]},
                rows,
                "verified",
            )
            C.validate_evidence(*args)
            with self.assertRaises(RuntimeError):
                C.validate_evidence(
                    root,
                    {"checks": ["browser"]},
                    {"state": "passed"},
                    args[3],
                    rows,
                    "passed",
                )
            for mutation in ("failed", "changed", "duplicate"):
                changed = copy.deepcopy(rows)
                if mutation == "failed":
                    changed[0]["exit_code"] = 1
                if mutation == "changed":
                    changed[0]["sha256"] = "wrong"
                if mutation == "duplicate":
                    changed[1] = copy.deepcopy(changed[0])
                with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                    C.validate_evidence(*args[:4], changed, "verified")
