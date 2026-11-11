"""Usage parsing and refresh scheduling without a Claude process or model call."""

import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import repo_claude_usage as usage


class UsageTests(unittest.TestCase):
    def test_screen_sections_and_terminal_escapes(self):
        screen = "\x1b[32mCurrent session (5h)\x1b[0m\n0% used\nResets 2pm (UTC)\nCurrent week (all models)\n99.5% used\nCurrent week (Sonnet only)\n20% used\nWhat's contributing\n80% used"
        now = datetime(2026, 11, 11, 12, tzinfo=timezone.utc).timestamp()
        result = usage.parse_usage(screen, now)
        self.assertEqual(result["five_hour"]["used_percent"], 0)
        self.assertEqual(result["five_hour"]["resets_at"], now + 7200)
        self.assertEqual(result["seven_day"]["used_percent"], 99.5)
        self.assertEqual(result["seven_day_sonnet"]["used_percent"], 20)

    def test_redraw_and_unrecognized_section_do_not_reuse_reading(self):
        screen = "Current session\n40% used\nCurrent session\nloading\nCurrent mystery\n90% used\nCurrent week (all models)\n101% used"
        self.assertEqual(usage.parse_usage(screen), {})

    def test_reset_rollover_and_invalid_dates(self):
        now = datetime(2026, 12, 31, 23, tzinfo=timezone.utc).timestamp()
        self.assertEqual(
            usage.reset_epoch("Resets Jan 1 at 1am (UTC)", "seven_day", now), now + 7200
        )
        self.assertEqual(
            usage.reset_epoch("Resets 1am (UTC)", "five_hour", now), now + 7200
        )
        for text in (
            "Resets Feb 30 at 1am (UTC)",
            "Resets 13pm (UTC)",
            "Resets 1pm (EST)",
            "Resets 10am (UTC)",
        ):
            self.assertIsNone(usage.reset_epoch(text, "five_hour", now))


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.sample = self.folder / "claude-quota.json"
        self.attempt = self.folder / "claude-usage-check.json"
        self.clock = patch.object(usage.time, "time", return_value=1000)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.probe = patch.object(usage, "native_usage")
        self.native = self.probe.start()
        self.addCleanup(self.probe.stop)

    def write(self, path, value):
        path.write_text(json.dumps(value))

    def refresh(self):
        return usage.refresh("/fake/claude", self.folder)

    def test_fresh_sample_does_not_probe(self):
        prior = {"windows": {"five_hour": {"used_percent": 0}}, "reported_at": 999}
        self.write(self.sample, prior)
        self.assertEqual(self.refresh()[0], prior)
        self.native.assert_not_called()

    def test_failure_keeps_sample_and_is_throttled(self):
        prior = {"windows": {"five_hour": {"used_percent": 50}}, "reported_at": 100}
        self.write(self.sample, prior)
        self.native.side_effect = RuntimeError("usage unavailable")
        sample, check = self.refresh()
        self.assertEqual(sample, prior)
        self.assertEqual(check["note"], "usage unavailable")
        self.assertEqual(self.refresh(), (sample, check))
        self.native.assert_called_once()
        self.assertEqual(json.loads(self.sample.read_text()), prior)

    def test_newer_statusline_wins_over_probe(self):
        newer = {"windows": {"seven_day": {"used_percent": 70}}, "reported_at": 1002}

        def probe(*args):
            self.write(self.sample, newer)
            return {"windows": {"seven_day": {"used_percent": 60}}, "reported_at": 1001}

        self.native.side_effect = probe
        self.assertEqual(self.refresh()[0], newer)
        self.assertEqual(json.loads(self.sample.read_text()), newer)

    def test_corrupt_cache_does_not_prevent_refresh(self):
        latest = {"windows": {"five_hour": {"used_percent": 0}}, "reported_at": 1000}
        self.native.return_value = latest
        for invalid in (
            [],
            None,
            {"checked": "yesterday", "reported_at": "tomorrow", "windows": {}},
        ):
            self.write(self.sample, invalid)
            self.write(self.attempt, invalid)
            self.assertEqual(self.refresh()[0], latest)
        self.assertEqual(self.native.call_count, 3)

    def test_live_lock_does_not_launch_second_probe(self):
        with (self.folder / "claude-usage.lock").open("a") as lock:
            usage.fcntl.flock(lock, usage.fcntl.LOCK_EX | usage.fcntl.LOCK_NB)
            self.assertEqual(self.refresh(), ({}, {"refreshing": True}))
        self.native.assert_not_called()

    def test_attempt_saved_before_probe_even_if_interrupted(self):
        self.native.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.refresh()
        self.assertEqual(json.loads(self.attempt.read_text())["checked"], 1000)
        self.refresh()
        self.native.assert_called_once()


class ProbeTests(unittest.TestCase):
    def test_probe_submits_only_usage_and_reaps_its_child(self):
        import os
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            script = folder / "fake_cli.py"
            received = folder / "received.txt"
            script.write_text(
                "import pathlib,sys,time\n"
                'print("Claude Code v0.test\\n$", flush=True)\n'
                "line=sys.stdin.readline()\n"
                "pathlib.Path(sys.argv[1]).write_text(line)\n"
                'print("Current session\\n0% used\\nCurrent week (all models)\\n25% used", flush=True)\n'
                "time.sleep(30)\n"
            )
            real_popen = subprocess.Popen
            children = []

            def launch(args, **kwargs):
                self.assertEqual(args[0], "/fake/claude")
                self.assertIn("--safe-mode", args)
                self.assertIn("--strict-mcp-config", args)
                self.assertEqual(args[args.index("--tools") + 1], "")
                self.assertEqual(kwargs["env"]["TZ"], "UTC")
                self.assertNotIn("CLAUDECODE", kwargs["env"])
                child = real_popen(
                    [sys.executable, str(script), str(received)], **kwargs
                )
                children.append(child)
                return child

            with patch.object(usage.sp, "Popen", side_effect=launch), patch.dict(
                os.environ, {"CLAUDECODE": "parent"}
            ):
                result = usage.native_usage("/fake/claude", folder / "probe", timeout=3)
            self.assertEqual(received.read_text(), "/usage\n")
            self.assertEqual(result["windows"]["seven_day"]["used_percent"], 25)
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].returncode)
