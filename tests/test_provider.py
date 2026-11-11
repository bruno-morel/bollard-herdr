"""Account probes must not turn unknown responses into sign-in or spare quota."""

import importlib.util
import io
import json
from pathlib import Path
import subprocess as sp
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "provider", Path(__file__).with_name("repo-provider.py")
)
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)


class ProviderTests(unittest.TestCase):
    def probe(self, name, payload, code=0):
        result = sp.CompletedProcess([], code, payload, "")
        with patch.object(provider, "binary", return_value="/fake/agent"), patch.object(
            provider.sp, "run", return_value=result
        ) as run:
            row = provider.auth(name)
        self.assertEqual(run.call_count, 1)
        self.assertNotIn("run", run.call_args.args[0])
        return row

    def test_claude_requires_successful_boolean_status(self):
        for payload in ("[]", "null", "{}", '{"loggedIn":"true"}', "broken"):
            with self.subTest(payload=payload):
                self.assertIsNone(self.probe("claude", payload)["connected"])
        self.assertIsNone(self.probe("claude", '{"loggedIn":true}', 1)["connected"])
        self.assertIs(self.probe("claude", '{"loggedIn":false}')["connected"], False)
        self.assertIs(self.probe("claude", '{"loggedIn":true}')["connected"], True)

    def test_failed_cursor_command_cannot_claim_connection(self):
        self.assertIsNone(self.probe("cursor", "Previously logged in", 1)["connected"])
        self.assertIs(self.probe("cursor", "Not authenticated")["connected"], False)
        self.assertIs(self.probe("cursor", "Logged in")["connected"], True)

    def test_missing_cli_never_launches_anything(self):
        with patch.object(provider, "binary", return_value=None), patch.object(
            provider.sp, "run"
        ) as run:
            self.assertEqual(
                provider.auth("claude"),
                {"provider": "claude", "installed": False, "connected": None},
            )
            run.assert_not_called()

    def test_codex_malformed_windows_are_unknown(self):
        for raw in (
            None,
            [],
            "bad",
            {"rateLimitsByLimitId": []},
            {"rateLimits": {"primary": 7}},
        ):
            self.assertIsNone(provider.normalize_codex_limits(raw)["quota"])
        for value in (True, -1, 101, float("nan"), float("inf"), "20"):
            self.assertIsNone(
                provider.normalize_codex_limits(
                    {"rateLimits": {"primary": {"usedPercent": value}}}
                )["quota"]
            )

    def test_codex_zero_usage_is_real_and_metadata_is_validated(self):
        data = {
            "rateLimitsByLimitId": {
                "codex": {
                    "primary": {
                        "usedPercent": 0,
                        "windowDurationMins": 300,
                        "resetsAt": 1234,
                    },
                    "secondary": {
                        "usedPercent": 100,
                        "windowDurationMins": "bad",
                        "resetsAt": True,
                    },
                }
            }
        }
        row = provider.normalize_codex_limits(data)
        self.assertEqual(
            row["quota"]["primary"],
            {"used_percent": 0, "window_minutes": 300, "resets_at": 1234},
        )
        self.assertEqual(
            row["quota"]["secondary"],
            {"used_percent": 100, "window_minutes": None, "resets_at": None},
        )

    def test_capture_bad_windows_preserves_previous_measurement(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            quota = folder / "claude-quota.json"
            quota.write_text('{"previous":true}')
            for payload in (
                "null",
                '{"rate_limits":[]}',
                '{"rate_limits":{"five_hour":17}}',
            ):
                with patch.object(
                    provider, "runtime", return_value=folder
                ), patch.object(
                    provider.sys, "stdin", io.StringIO(payload)
                ), patch.object(
                    provider.sys, "stdout", io.StringIO()
                ), patch.object(
                    provider.sp, "run"
                ) as run:
                    provider.capture()
                    run.assert_not_called()
                self.assertEqual(json.loads(quota.read_text()), {"previous": True})

    def test_already_signed_in_does_not_open_account_terminal(self):
        for name in ("claude", "cursor"):
            with patch.object(
                provider, "binary", return_value="/fake/agent"
            ), patch.object(
                provider,
                "auth",
                return_value={"connected": True, "method": "claude.ai"},
            ), patch.object(
                provider.sp, "run"
            ) as run:
                self.assertTrue(provider.login_unlocked(name)["connected"])
                run.assert_not_called()
