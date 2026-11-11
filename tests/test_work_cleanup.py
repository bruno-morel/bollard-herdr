"""Exercise shell cleanup with real worktrees and inert Docker/session boundaries."""

import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess as sp
import sys
import tempfile
import unittest

BIN = Path(__file__).resolve().parent


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "repo"
        self.root.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.log = self.base / "calls"
        for name in ("work", "repo-context.zsh"):
            shutil.copy2(BIN / name, self.bin / name)
        self.env = dict(
            os.environ,
            HOME=str(self.base),
            XDG_STATE_HOME=str(self.base / "state"),
            PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
            TEST_LOG=str(self.log),
            REAL_PYTHON=sys.executable,
            REAL_GIT=shutil.which("git"),
        )
        for key in ("ZELLIJ", "ZELLIJ_SESSION_NAME"):
            self.env.pop(key, None)
        scripts = {
            "python3": """#!/bin/sh
case "$1" in
  -) exec "$REAL_PYTHON" "$@" ;;
  */repo-zellij-socket.py) echo "$HOME/socket" ;;
  */repo_sessions.py) echo work-test ;;
  */studio-session.py) exit 0 ;;
  */repo_herdr.py) exit "${GUARD_EXIT:-0}" ;;
  *) exit 99 ;;
esac
""",
            "docker": '#!/bin/sh\nprintf "docker %s\\n" "$*" >> "$TEST_LOG"\nexit "${DOCKER_EXIT:-0}"\n',
            "zellij": '#!/bin/sh\nprintf "zellij %s\\n" "$*" >> "$TEST_LOG"\n',
            "git": """#!/bin/sh
case "$*" in
  *"status --porcelain"*) [ "${STATUS_FAIL:-0}" = 0 ] || exit 1 ;;
esac
exec "$REAL_GIT" "$@"
""",
        }
        for name, script in scripts.items():
            p = self.bin / name
            p.write_text(script)
            p.chmod(0o755)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("commit", "--allow-empty", "-qm", "Initial")
        self.tree = self.base / "repo-worktrees/demo"
        self.git("worktree", "add", "-qb", "codex/demo", str(self.tree))
        common = (self.root / ".git").resolve()
        key = hashlib.sha256(os.fsencode(common)).hexdigest()[:16]
        self.state = self.base / "state/repo-tools/work" / key / "demo"
        self.state.mkdir(parents=True)
        (self.state / "state.env").write_text(
            "SLUG=demo\nSLOT=1\nBRANCH=codex/demo\nSESSION=work-test\nWORKTREE_PATH="
            + shlex.quote(str(self.tree))
            + "\n"
        )
        (self.state / "compose.work.json").write_text("{}")

    def git(self, *args):
        return sp.check_output(
            [self.env["REAL_GIT"], "-C", str(self.root), *args],
            stderr=sp.DEVNULL,
            env=self.env,
            text=True,
        )

    def run_work(self, *args, answer="y\n", **env):
        return sp.run(
            ["zsh", str(self.bin / "work"), *args],
            cwd=self.root,
            env=dict(self.env, **env),
            input=answer,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def calls(self):
        return self.log.read_text() if self.log.exists() else ""

    def preserved(self):
        self.assertTrue(self.tree.is_dir())
        self.assertTrue((self.state / "state.env").is_file())

    def test_declined_removal_does_nothing(self):
        result = self.run_work("rm", "demo", answer="n\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.preserved()
        self.assertEqual(self.calls(), "")

    def test_failed_docker_cleanup_preserves_tree_and_record(self):
        result = self.run_work("rm", "demo", DOCKER_EXIT="7")
        self.assertNotEqual(result.returncode, 0)
        self.preserved()
        self.assertNotIn("zellij", self.calls())

    def test_failed_status_is_not_clean(self):
        result = self.run_work("rm", "demo", STATUS_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot inspect worktree", result.stderr)
        self.preserved()
        self.assertEqual(self.calls(), "")

    def test_dirty_tree_refuses_without_force(self):
        (self.tree / "draft.txt").write_text("Keep me")
        result = self.run_work("rm", "demo")
        self.assertNotEqual(result.returncode, 0)
        self.preserved()
        self.assertEqual(self.calls(), "")

    def test_success_removes_checkout_but_preserves_branch(self):
        result = self.run_work("rm", "demo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.tree.exists())
        self.assertFalse(self.state.exists())
        self.git("show-ref", "--verify", "refs/heads/codex/demo")
        self.assertEqual(
            self.calls().splitlines(),
            [
                "docker compose down -v --remove-orphans",
                "zellij kill-session work-test",
                "zellij delete-session work-test",
            ],
        )

    def test_force_still_obeys_agent_ownership_guard(self):
        result = self.run_work("rm", "demo", "--force", GUARD_EXIT="1")
        self.assertNotEqual(result.returncode, 0)
        self.preserved()
        self.assertEqual(self.calls(), "")

    def test_finish_rejects_unknown_options_before_cleanup(self):
        result = self.run_work("finish", "demo", "--delete-remtoe")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown option", result.stderr)
        self.preserved()
        self.assertEqual(self.calls(), "")
