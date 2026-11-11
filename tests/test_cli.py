"""Exercise the real shell entry points, without Docker, agents or sessions."""

import os
from pathlib import Path
import subprocess as sp
import tempfile
import unittest

BIN = Path(__file__).resolve().parent


class CommandBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(
            os.environ, HOME=str(self.root), XDG_STATE_HOME=str(self.root / "state")
        )

    def invoke(self, command, *args):
        return sp.run(
            ["zsh", str(BIN / command), *args],
            cwd=self.root,
            env=self.env,
            text=True,
            capture_output=True,
            timeout=5,
        )

    def test_help_outside_repository_has_no_side_effects(self):
        for command in ("studio", "work"):
            with self.subTest(command=command):
                result = self.invoke(command, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(command, result.stdout.lower())
                self.assertEqual(list(self.root.iterdir()), [])

    def test_open_outside_repository_fails_before_state_creation(self):
        for command in ("studio", "work"):
            with self.subTest(command=command):
                result = self.invoke(command, "open", "example")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Git-controlled source tree", result.stderr)
                self.assertEqual(list(self.root.iterdir()), [])

    def test_bare_repository_is_not_a_source_checkout(self):
        sp.run(["git", "init", "--bare", "-q", str(self.root)], check=True)
        for command in ("studio", "work"):
            result = self.invoke(command, "open", "example")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Git-controlled source tree", result.stderr)
            self.assertFalse((self.root / "state").exists())

    def test_work_default_help_matches_explicit_help_in_main_checkout(self):
        self.root = self.root / "repo"
        self.root.mkdir()
        sp.run(["git", "init", "-q", str(self.root)], check=True)
        default = self.invoke("work")
        explicit = self.invoke("work", "--help")
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(default.stdout, explicit.stdout)
        self.assertIn("work complete", default.stdout)
        self.assertIn("work tests first", default.stdout)


class StudioAliases(unittest.TestCase):
    """Run the shell dispatcher against real Git and inert process boundaries."""

    def setUp(self):
        import shutil

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        for name in ("studio", "repo-context.zsh"):
            shutil.copy2(BIN / name, self.bin / name)
        self.log = self.base / "commands"
        self.env = dict(
            os.environ,
            HOME=str(self.base),
            XDG_STATE_HOME=str(self.base / "state"),
            PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
            TEST_ROOT=str(self.root),
            TEST_LOG=str(self.log),
        )
        self.env.pop("ZELLIJ", None)
        self.env.pop("ZELLIJ_SESSION_NAME", None)
        scripts = {
            "python3": """#!/bin/sh
printf 'python %s\\n' "$*" >> "$TEST_LOG"
case "$1" in
  */repo_sessions.py) echo studio-test ;;
  */repo-zellij-socket.py) echo "$HOME/socket" ;;
esac
""",
            "work": """#!/bin/sh
printf 'work %s\\n' "$*" >> "$TEST_LOG"
[ "$1" != path ] || printf '%s\\n' "$TEST_ROOT"
""",
            "zellij": """#!/bin/sh
printf 'zellij %s\\n' "$*" >> "$TEST_LOG"
""",
        }
        for name, script in scripts.items():
            p = self.bin / name
            p.write_text(script)
            p.chmod(0o755)
        sp.run(["git", "init", "-q", str(self.root)], check=True)
        sp.run(
            [
                "git",
                "-C",
                str(self.root),
                "symbolic-ref",
                "HEAD",
                "refs/heads/codex/demo",
            ],
            check=True,
        )

    def invoke(self, *args):
        return sp.run(
            ["zsh", str(self.bin / "studio"), *args],
            cwd=self.root,
            env=self.env,
            text=True,
            capture_output=True,
            timeout=5,
        )

    def test_new_open_shorthand_and_plain_command_share_one_setup(self):
        for args in [("new", "demo"), ("open", "demo"), ("demo",), ()]:
            with self.subTest(args=args):
                self.log.unlink(missing_ok=True)
                result = self.invoke(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                calls = self.log.read_text().splitlines()
                self.assertEqual(calls.count("work prepare demo"), 1)
                self.assertEqual(sum("/repo-transfer.py init " in c for c in calls), 1)
                self.assertEqual(
                    sum(c.startswith("zellij -s studio-test ") for c in calls), 1
                )
                self.assertTrue((self.root / "docs/handoffs/demo/branch.txt").is_file())
                self.assertTrue((self.root / "scratch").is_dir())

    def test_help_variants_do_not_reach_repository_or_session_commands(self):
        for args in [("help",), ("-h",), ("--help",), ("open", "demo", "--help")]:
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Aliases:", result.stdout)
                self.assertIn("studio transfer", result.stdout)
                self.assertFalse(self.log.exists())
                self.assertFalse((self.root / "docs").exists())

    def test_copy_prefers_implementation_and_supports_legacy_handoff(self):
        import base64

        packet = self.root / "docs/handoffs/demo"
        packet.mkdir(parents=True)
        legacy = packet / "codex-prompt.md"
        modern = packet / "implementation.md"
        legacy.write_text("Legacy context\n")
        modern.write_text("Current context\n")
        for expected in ("Current context\n", "Legacy context\n"):
            result = self.invoke("copy", "demo")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = result.stdout.split("\x1b]52;c;", 1)[1].split("\x07", 1)[0]
            self.assertEqual(base64.b64decode(payload).decode(), expected)
            modern.unlink(missing_ok=True)
        legacy.unlink()
        result = self.invoke("copy", "demo")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("studio handoff build demo", result.stderr)
        self.assertNotIn("\x1b]52;", result.stdout)
