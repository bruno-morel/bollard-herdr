"""Helper ownership and launch contracts; no models or Herdr processes run."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "helper_flow", Path(__file__).with_name("repo-flow.py")
)
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)


class Helpers(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.lead = {
            "address": "t1",
            "state": "live",
            "labels": {"repo-tools.role": "work", "herdr.space": "demo"},
        }
        self.rows = [self.lead]
        self.args = SimpleNamespace(
            stream="demo",
            scope="Inspect failures",
            agent="codex",
            role="work",
            kind="research",
            preview=False,
        )
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stack.enter_context(
            patch.object(
                F, "context", return_value=(self.root, "demo", self.runtime, "key")
            )
        )
        self.stack.enter_context(patch.object(F.A, "checkout", return_value=self.root))
        self.stack.enter_context(
            patch.object(F, "details", side_effect=lambda *a: (self.root, self.rows))
        )
        self.stack.enter_context(patch.object(F.A, "git", return_value="base"))
        self.stack.enter_context(
            patch.object(F.A, "executable", return_value="/fake/agent")
        )
        self.packet = self.stack.enter_context(
            patch.object(F.C, "prepare", return_value=None)
        )
        self.command = self.stack.enter_context(patch.object(F, "command"))

    def test_research_helper_keeps_parent_and_read_only_instructions(self):
        F.helper(self.args)
        argv = self.command.call_args.args[0]
        self.assertEqual(argv[argv.index("--parent") + 1], "t1")
        self.assertIn("--keep", argv)
        self.assertIn("--outlive-parent", argv)
        job = json.loads(next(self.runtime.glob("helper-*.json")).read_text())
        self.assertEqual(job["root"], str(self.root))
        self.assertEqual(job["parent"], "t1")
        self.assertIn("Do not modify any files", job["prompt"])
        self.assertEqual(self.command.call_count, 1)  # no worktree or Docker commands

    def test_unknown_provider_is_rejected(self):
        self.args.agent = "unknown"
        with self.assertRaisesRegex(RuntimeError, "Choose"):
            F.helper(self.args)
        self.command.assert_not_called()

    def test_live_helper_or_missing_or_ambiguous_lead_prevents_launch(self):
        cases = [
            [],
            [self.lead, dict(self.lead, address="t2")],
            [self.lead, {"state": "live", "labels": {"repo-tools.role": "helper"}}],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                self.rows = rows
                with self.assertRaises(RuntimeError):
                    F.helper(self.args)
                self.command.assert_not_called()
                self.assertFalse(list(self.runtime.glob("helper-*.json")))

    def test_changed_pane_parent_refuses_launch(self):
        self.packet.return_value = {"scope": "Inspect", "evidence": {"parent": "t9"}}
        with self.assertRaisesRegex(RuntimeError, "pane lead changed"):
            F.helper(self.args)
        self.command.assert_not_called()

    def test_active_workflow_refuses_helper(self):
        F.write(self.runtime / "state.json", {"state": next(iter(F.ACTIVE))})
        with self.assertRaisesRegex(RuntimeError, "current implementation/review"):
            F.helper(self.args)
        self.command.assert_not_called()

    def test_coding_helper_refuses_dirty_parent_without_stashing(self):
        self.args.kind = "code"
        with self.assertRaisesRegex(RuntimeError, "Commit the lead checkout"):
            F.helper(self.args)
        self.command.assert_not_called()

    def test_research_agent_launch_uses_restricted_mode_and_keeps_shell(self):
        for agent in ("codex", "claude", "cursor"):
            with self.subTest(agent=agent):
                path = self.runtime / "job.json"
                F.write(
                    path,
                    {
                        "agent": agent,
                        "kind": "research",
                        "root": str(self.root),
                        "prompt": "Inspect only",
                    },
                )
                with patch.object(F.sp, "run") as run, patch.object(
                    F.os, "chdir"
                ), patch.object(F.os, "execv") as shell:
                    F.helper_pane(path)
                argv = run.call_args.args[0]
                if agent == "codex":
                    self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
                    self.assertEqual(
                        argv[argv.index("--ask-for-approval") + 1], "never"
                    )
                elif agent == "claude":
                    self.assertEqual(argv[argv.index("--tools") + 1], "Read,Glob,Grep")
                    self.assertIn("--strict-mcp-config", argv)
                else:
                    self.assertEqual(argv[argv.index("--mode") + 1], "ask")
                self.assertEqual(argv[-1], "Inspect only")
                shell.assert_called_once_with("/bin/zsh", ["zsh", "-l"])
