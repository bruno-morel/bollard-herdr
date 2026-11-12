"""Status panels must distinguish missing evidence, failures and real empty results."""

import copy
import unittest
from repo_tui_present import info_lines, test_line


class Presentation(unittest.TestCase):
    def text(self, tab, cache, errors=None):
        return "\n".join(line for line, _ in info_lines(tab, cache, errors))

    def test_loading_is_not_clean_git_or_empty_docker(self):
        for tab in ("git-info", "services", "context", "usage"):
            self.assertEqual(info_lines(tab, {}), [("Loading…", 0)])
        self.assertIn(
            "Working tree clean",
            self.text("git-info", {"git": {"branch": "demo", "files": []}}),
        )
        self.assertIn(
            "No containers running",
            self.text("services", {"services": {"services": []}}),
        )

    def test_refresh_failure_cannot_present_cached_success(self):
        for tab, key in [
            ("git-info", "git"),
            ("context", "metadata"),
            ("services", "services"),
            ("usage", "usage"),
        ]:
            with self.subTest(tab=tab):
                lines = info_lines(tab, {key: {}}, {key: "Disconnected"})
                self.assertEqual(lines, [("Could not refresh: Disconnected", 4)])

    def test_quotas_distinguish_missing_from_zero_and_keep_review_allowance_separate(
        self,
    ):
        cache = {
            "usage": {
                "providers": [
                    {
                        "provider": "codex",
                        "connected": True,
                        "quota": {
                            "weekly": {"used_percent": 0, "window_minutes": 10080}
                        },
                    },
                    {"provider": "claude", "connected": True},
                    {"provider": "cursor", "connected": False},
                ]
            },
            "review": {"remaining": 1},
        }
        before = copy.deepcopy(cache)
        text = self.text("usage", cache)
        self.assertIn("0% · Weekly", text)
        self.assertIn("Quota not reported", text)
        self.assertIn("Sign in on the agent", text)
        self.assertIn("Review calls: 1 / 2", text)
        self.assertEqual(cache, before)

    def test_context_does_not_invent_model_or_compaction_data(self):
        text = self.text("context", {"metadata": {}})
        for expected in (
            "Model not reported",
            "Unknown",
            "Compactions: ?",
            "not a live estimate",
        ):
            self.assertIn(expected, text)

    def test_container_memory_uses_explicit_cap_and_labels_host_fallback(self):
        service = {
            "Service": "web",
            "State": "running",
            "Health": "healthy",
            "UptimeSeconds": 90000,
            "Restarts": 2,
            "MemoryLimitBytes": 256 * 1024**2,
            "Metrics": {"MemUsage": "128 MiB / 8 GiB"},
        }
        text = self.text("services", {"services": {"services": [service]}})
        self.assertIn("web · running healthy", text)
        self.assertIn("Up 1d 1h · ↻ 2", text)
        self.assertIn("128 MiB / 256 MiB", text)
        self.assertIn("Container cap", text)
        service["MemoryLimitBytes"] = 0
        self.assertIn(
            "Shared Docker host limit",
            self.text("services", {"services": {"services": [service]}}),
        )

    def test_test_rows_keep_failure_pending_and_native_summary_distinct(self):
        for code, mark, color in [(0, "✓", 2), (1, "✗", 4), (None, "…", 3)]:
            line, actual = test_line(
                {
                    "id": "browser",
                    "exit_code": code,
                    "native_summary": {"passed": 7, "failed": 1},
                }
            )
            self.assertTrue(line.startswith(mark))
            self.assertIn("1 failed", line)
            self.assertEqual(actual, color)

    def test_success_and_unknown_counts_have_no_failure_label(self):
        line, color = test_line({'id':'unit','exit_code':0,'native_summary':{'passed':244,'failed':0}})
        self.assertIn('244 passed', line)
        self.assertNotIn('failed', line)
        self.assertEqual(color,2)
        line, color = test_line({'id':'typecheck','exit_code':0})
        self.assertIn('Count unavailable',line)
        self.assertNotIn('failed',line)
