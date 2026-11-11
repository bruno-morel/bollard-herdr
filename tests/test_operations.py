import copy
import unittest
import repo_operations as O


class Operations(unittest.TestCase):
    def test_status_is_read_only_and_accepts_legacy_record(self):
        job = dict(
            token="a",
            state="saving",
            stage="pushing",
            updated="2026-11-10T15:00:00+00:00",
            heartbeat=1000,
        )
        before = copy.deepcopy(job)
        result = O.describe("checkpoint", job, now=1010)
        self.assertEqual(job, before)
        self.assertEqual(result["operation"]["label"], "Pushing branch")
        self.assertFalse(result["operation"]["can_retry"])

    def test_stalled_display_never_advertises_unsafe_retry(self):
        result = O.describe(
            "checkpoint", dict(token="a", state="saving", heartbeat=1), now=1000
        )
        self.assertEqual(result["state"], "needs-you")
        self.assertTrue(result["operation"]["stalled"])
        self.assertFalse(result["operation"]["can_retry"])

    def test_completion_elapsed_time_stops(self):
        result = O.describe(
            "checkpoint",
            dict(token="a", state="started", started_at=10, heartbeat=30),
            now=1000,
        )
        self.assertEqual(result["elapsed_seconds"], 20)
        self.assertEqual(result["operation"]["steps"][-1]["status"], "done")

    def test_failed_stage_preserved(self):
        job = dict(token="a", state="saving", stage="pushing")
        O.transition(job, "needs-you", "Push rejected", now=20)
        result = O.describe("checkpoint", job, now=30)
        self.assertEqual(result["operation"]["stage"], "pushing")
        self.assertTrue(result["operation"]["can_retry"])
        self.assertEqual(result["message"], "Push rejected")

    def test_retry_history_not_erased(self):
        job = dict(
            token="a",
            state="needs-you",
            stage="pushing",
            failed_stage="pushing",
            history=[{"stage": "pushing"}],
        )
        O.transition(job, "queued", "Retry requested", now=20)
        self.assertEqual(len(job["history"]), 2)
        self.assertNotIn("failed_stage", job)

    def test_only_open_workflows_offer_retry(self):
        for action in ("prepare", "implement", "helper"):
            job = dict(token="a", state="needs-you", action=action)
            self.assertFalse(O.describe("workflow", job)["operation"]["can_retry"])
            with self.assertRaises(RuntimeError):
                O.require_retry("workflow", job, "a")
        O.require_retry(
            "workflow", dict(token="a", state="needs-you", action="open"), "a"
        )

    def test_identity_checked_on_retry(self):
        job = dict(token="a", state="needs-you", target="t1")
        for token, target in (("b", "t1"), ("a", "t2")):
            with self.assertRaises(RuntimeError):
                O.require_retry("checkpoint", job, token, target=target)

    def test_attempts_have_distinct_notification_ids(self):
        job = dict(token="a", state="needs-you")
        one = O.describe("checkpoint", job)["operation"]["event_id"]
        two = O.describe("checkpoint", dict(job, attempt=2))["operation"]["event_id"]
        self.assertNotEqual(one, two)


if __name__ == "__main__":
    unittest.main()
