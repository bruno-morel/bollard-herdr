"""Workflow delivery and completion signals must never replay ambiguous work."""

import importlib.util
import io
from pathlib import Path
import subprocess as sp
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "flow", Path(__file__).with_name("repo-flow.py")
)
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)


class FlowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.runtime = Path(temp.name)
        self.job = {
            "token": "test",
            "role": "work",
            "state": "queued",
            "stream": "demo",
        }
        self.row = {
            "address": "t1",
            "state": "live",
            "status": {"state": "idle"},
            "turn": 1,
        }
        foreground = patch.object(F, "agent_foreground", return_value=True)
        foreground.start()
        self.addCleanup(foreground.stop)

    def test_label_failure_does_not_undo_durable_completion(self):
        with patch.dict(F.os.environ, {"HC_TERMINAL_ID": "t2"}), patch.object(
            F, "command", side_effect=sp.CalledProcessError(1, ["hc"])
        ), patch("sys.stderr", new_callable=io.StringIO) as error, patch(
            "sys.stdout", new_callable=io.StringIO
        ):
            F.phase(self.runtime, self.job, "verified", "Complete")
        self.assertEqual(F.read(self.runtime / "state.json")["state"], "verified")
        self.assertIn("label update failed", error.getvalue())

    def test_state_write_failure_prevents_label_publication(self):
        with patch.dict(F.os.environ, {"HC_TERMINAL_ID": "t2"}), patch.object(
            F, "write", side_effect=OSError("disk full")
        ), patch.object(F, "command") as command:
            with self.assertRaises(OSError):
                F.phase(self.runtime, self.job, "verified", "Complete")
            command.assert_not_called()

    def test_startup_idle_is_not_a_completed_task(self):
        later = dict(self.row, turn=2)
        with patch.object(F, "hc", side_effect=[self.row, {}, later]) as hc:
            self.assertEqual(F.wait_turn(self.row, self.runtime, self.job), later)
        self.assertEqual(
            [c.args[:1] for c in hc.call_args_list], [("get",), ("wait",), ("get",)]
        )

    def test_blocked_agent_stops_without_wait_or_review(self):
        with patch.object(
            F, "hc", return_value=dict(self.row, status={"state": "blocked"})
        ) as hc:
            with self.assertRaisesRegex(RuntimeError, "needs attention"):
                F.wait_turn(self.row, self.runtime, self.job)
        hc.assert_called_once_with("get", "t1")

    def test_pause_prevents_any_agent_request(self):
        (self.runtime / "pause-test").touch()
        with patch.object(F, "hc") as hc:
            with self.assertRaisesRegex(RuntimeError, "Paused"):
                F.wait_turn(self.row, self.runtime, self.job)
            hc.assert_not_called()

    def test_ambiguous_delivery_is_reserved_and_never_replayed(self):
        with patch.object(
            F, "hc", side_effect=[self.row, sp.TimeoutExpired("hc send", 45)]
        ) as hc, patch.object(F, "wait_turn") as wait:
            with self.assertRaises(sp.TimeoutExpired):
                F.send_task(self.row, "Do the task", self.runtime, self.job)
            wait.assert_not_called()
        self.assertEqual(F.read(self.runtime / "state.json")["delivery"], "sending")
        self.assertEqual(hc.call_count, 2)

    def test_unconfirmed_delivery_does_not_wait_for_success(self):
        with patch.object(
            F, "hc", side_effect=[self.row, {"started": False}]
        ), patch.object(F, "wait_turn") as wait:
            with self.assertRaisesRegex(RuntimeError, "not confirmed"):
                F.send_task(self.row, "Do the task", self.runtime, self.job)
            wait.assert_not_called()
        self.assertEqual(F.read(self.runtime / "state.json")["delivery"], "sending")

    def test_confirmed_delivery_waits_without_second_send(self):
        with patch.object(
            F, "hc", side_effect=[self.row, {"started": True}]
        ) as hc, patch.object(F, "wait_turn", return_value=self.row) as wait:
            self.assertEqual(
                F.send_task(self.row, "Task", self.runtime, self.job), self.row
            )
            wait.assert_called_once_with(self.row, self.runtime, self.job, started=True)
        self.assertEqual(hc.call_count, 2)
        self.assertEqual(F.read(self.runtime / "state.json")["delivery"], "sent")
