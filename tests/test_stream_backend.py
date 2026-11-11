import unittest
from unittest.mock import patch
import subprocess as sp
import repo_stream_backend as B


class StreamBackend(unittest.TestCase):
    def test_remote_arguments_are_never_interpolated_as_shell_text(self):
        backend = B.Backend()
        with patch.object(
            sp, "run", return_value=sp.CompletedProcess([], 0, "{}", "")
        ) as run:
            backend.script(
                "remote",
                "repo-streams.py",
                ["catalog", "--repo", "/repo/$(literal)"],
                cwd="/with spaces",
            )
        argv = run.call_args.args[0]
        self.assertEqual(argv[-1], "/repo/$(literal)")
        self.assertEqual(argv[argv.index("--cwd") + 1], "/with spaces")
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_existing_conversation_is_reused_without_preparing_or_starting(self):
        backend = B.Backend()
        row = {
            "address": "remote/t1",
            "labels": {
                "repo-tools.role": "work",
                "repo-tools.stream": "demo",
                "repo-tools.checkout": "/repo/demo",
            },
        }
        with patch.object(backend, "inventory", return_value=[row]), patch.object(
            backend, "catalog", return_value={"common": "/repo/.git"}
        ), patch.object(backend, "verify", return_value=row), patch.object(
            backend, "script"
        ) as script:
            result = backend.prepare_and_open(
                "remote",
                {"common": "/repo/.git"},
                {"source": "tree", "stream": "demo"},
                "work",
                "codex",
            )
        self.assertEqual(result, {"address": "remote/t1"})
        script.assert_not_called()

    def test_ambiguous_conversations_require_selection_not_another_launch(self):
        backend = B.Backend()
        row = {
            "address": "remote/t1",
            "labels": {
                "repo-tools.role": "work",
                "repo-tools.stream": "demo",
                "repo-tools.checkout": "/repo/demo",
            },
        }
        with patch.object(
            backend, "inventory", return_value=[row, dict(row, address="remote/t2")]
        ), patch.object(
            backend, "catalog", return_value={"common": "/repo/.git"}
        ), patch.object(
            backend, "script"
        ) as script:
            with self.assertRaisesRegex(RuntimeError, "Multiple conversations"):
                backend.prepare_and_open(
                    "remote",
                    {"common": "/repo/.git"},
                    {"source": "tree", "stream": "demo"},
                    "work",
                    "codex",
                )
        script.assert_not_called()

    def test_transport_preserves_raw_logs_and_parses_last_json_line(self):
        backend = B.Backend()
        with patch.object(
            sp,
            "run",
            return_value=sp.CompletedProcess(
                [], 0, 'progress\n{"state":"ready"}\n', ""
            ),
        ):
            self.assertEqual(backend.script("", "work"), {"state": "ready"})
            self.assertEqual(
                backend.script("", "work", raw=True), 'progress\n{"state":"ready"}\n'
            )
