"""Exercise preview/merge against real disposable Git histories; no Herdr agents."""

import importlib.util
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "branch_sync", Path(__file__).with_name("repo-sync.py")
)
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


class BranchSync(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "tests@example.invalid")
        self.git("config", "user.name", "Test")
        self.git("config", "commit.gpgsign", "false")
        self.commit("base.txt", "base\n")
        self.git("branch", "-M", "main")
        self.git("checkout", "-qb", "codex/demo")
        self.branch = "refs/heads/codex/demo"
        self.source = "refs/heads/main"
        self.token = "a" * 32
        self.state = self.base / "state"
        self.record = self.state / "sync/key/demo" / (self.token + ".json")

    def git(self, *args):
        return S.git(self.root, *args)

    def commit(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        self.git("add", "--", name)
        self.git("commit", "-qm", "fixture change")

    def advance_source(self, name="incoming.txt", text="incoming\n"):
        self.git("checkout", "-q", "main")
        self.commit(name, text)
        self.git("checkout", "-q", "codex/demo")

    def preview(self):
        result = S.preview(self.root, self.branch, self.source)
        S.write(self.record, result)
        return result

    def apply(self):
        with patch.object(S, "ensure_idle"):
            return S.apply(
                self.root, self.branch, self.state, "key", "demo", self.token
            )

    def test_preview_does_not_change_checkout_and_apply_consumes_token(self):
        self.advance_source()
        head = self.git("rev-parse", "HEAD")
        view = self.preview()
        self.assertEqual(view["kind"], "fast-forward")
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertFalse((self.root / "incoming.txt").exists())
        result = self.apply()
        self.assertTrue(result["ok"])
        self.assertEqual(self.git("rev-parse", "HEAD"), self.git("rev-parse", "main"))
        self.assertTrue(S.read(self.record)["used"])
        with self.assertRaisesRegex(RuntimeError, "already used"):
            self.apply()

    def assert_stale(self):
        head = self.git("rev-parse", "HEAD")
        with self.assertRaisesRegex(RuntimeError, "branch changed"):
            self.apply()
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertFalse(S.read(self.record).get("used"))

    def test_moved_source_invalidates_preview(self):
        self.advance_source()
        self.preview()
        self.advance_source("another.txt", "new source\n")
        self.assert_stale()

    def test_moved_target_invalidates_preview(self):
        self.advance_source()
        self.preview()
        self.commit("local.txt", "new target\n")
        self.assert_stale()

    def test_untracked_files_block_merge_without_stashing(self):
        self.advance_source()
        self.preview()
        (self.root / "notes.txt").write_text("keep me")
        with self.assertRaisesRegex(RuntimeError, "Nothing will be stashed"):
            self.apply()
        self.assertEqual((self.root / "notes.txt").read_text(), "keep me")
        self.assertEqual(self.git("stash", "list"), "")

    def test_ignored_prefix_collision_is_blocked(self):
        self.commit(".gitignore", "assets/\n")
        self.advance_source("assets", "incoming file\n")
        (self.root / "assets").mkdir()
        (self.root / "assets/local.bin").write_text("preserve")
        view = self.preview()
        self.assertTrue(any("ignored local assets" in x for x in view["blocked"]))
        with self.assertRaisesRegex(RuntimeError, "ignored local assets"):
            self.apply()
        self.assertEqual((self.root / "assets/local.bin").read_text(), "preserve")

    def test_conflict_is_reported_and_left_for_user_without_reset(self):
        self.commit("base.txt", "target edit\n")
        self.advance_source("base.txt", "source edit\n")
        self.assertEqual(self.preview()["kind"], "merge commit")
        result = self.apply()
        self.assertFalse(result["ok"])
        self.assertEqual(result["conflicts"], "base.txt")
        self.assertEqual(S.operation(self.root), "MERGE_HEAD")
        self.assertTrue(S.read(self.record)["used"])

    def test_expired_preview_never_checks_agents_or_merges(self):
        self.advance_source()
        view = self.preview()
        view["created"] = time.time() - 901
        S.write(self.record, view)
        with patch.object(S, "ensure_idle") as idle:
            with self.assertRaisesRegex(RuntimeError, "expired"):
                S.apply(self.root, self.branch, self.state, "key", "demo", self.token)
        idle.assert_not_called()

    def test_active_checks_block_before_contacting_herdr(self):
        S.write(self.state / "tests/key/demo/state.json", {"state": "running"})
        with patch.object(S.sp, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "active"):
                S.ensure_idle(self.root, self.state, "key", "demo")
        run.assert_not_called()

    def test_checkpoint_blocks_merge_even_between_agent_turns(self):
        for phase in S.O.CHECKPOINT_ACTIVE:
            with self.subTest(phase=phase):
                S.write(
                    self.state / "agents/key/demo/workflow/new-chat.json",
                    {"state": phase},
                )
                with patch.object(S.sp, "run") as run:
                    with self.assertRaisesRegex(RuntimeError, "checkpoint"):
                        S.ensure_idle(self.root, self.state, "key", "demo")
                run.assert_not_called()
