import contextlib, hashlib, importlib.util, io, json, os, subprocess as sp, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "checkpoint", Path(__file__).with_name("repo-new-conversation.py")
)
N = importlib.util.module_from_spec(spec)
spec.loader.exec_module(N)


class Checkpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        self.remote = self.base / "remote.git"
        self.run_git("init", "-q")
        self.run_git("config", "user.name", "Test")
        self.run_git("config", "user.email", "test@example.com")
        self.run_git("checkout", "-qb", "codex/sample")
        sp.run(["git", "init", "--bare", "-q", str(self.remote)], check=True)
        self.run_git("remote", "add", "origin", str(self.remote))
        self.packet = self.root / "docs/handoffs/sample"
        self.packet.mkdir(parents=True)
        (self.packet / "context.md").write_text(
            "Current task and next steps\nCheckpoint: abc123\n"
        )
        (self.root / "code.txt").write_text("work in progress")
        self.run_git("add", ".")
        self.run_git("commit", "-qm", "checkpoint")
        self.run_git("push", "-qu", "origin", "codex/sample")
        self.job = dict(
            token="abc123",
            target="t1",
            state="saving",
            destination=N.push_destination(self.root, "sample"),
        )
        self.review = self.base / "state/repo-tools/review/key/sample"
        self.flow = self.base / "flow"
        self.ctx = (self.root, "sample", self.review, self.packet, "key")

    def tearDown(self):
        self.tmp.cleanup()

    def run_git(self, *a):
        return (
            sp.check_output(["git", "-C", str(self.root), *a], stderr=sp.STDOUT)
            .decode()
            .strip()
        )

    def test_remote_proof(self):
        self.assertEqual(
            N.verify_saved(self.root, "sample", self.job)["head"],
            self.run_git("rev-parse", "HEAD"),
        )

    def test_untracked_blocks(self):
        (self.root / "unsaved.txt").write_text("preserve")
        self.assertRaisesRegex(
            RuntimeError, "Uncommitted", N.verify_saved, self.root, "sample", self.job
        )

    def test_unpushed_blocks(self):
        (self.root / "code.txt").write_text("next")
        self.run_git("add", ".")
        self.run_git("commit", "-qm", "not pushed")
        self.assertRaisesRegex(
            RuntimeError,
            "Remote checkpoint",
            N.verify_saved,
            self.root,
            "sample",
            self.job,
        )

    def test_missing_context_blocks(self):
        self.job["token"] = "different"
        self.assertRaisesRegex(
            RuntimeError,
            "checkpoint is missing",
            N.verify_saved,
            self.root,
            "sample",
            self.job,
        )

    def test_main_destination_refused(self):
        self.run_git("config", "branch.codex/sample.merge", "refs/heads/main")
        self.assertRaisesRegex(
            RuntimeError, "never main", N.push_destination, self.root, "sample"
        )

    def test_ignore_scratch_does_not_count_as_backup(self):
        (self.root / ".gitignore").write_text("/scratch/\n")
        self.run_git("add", ".")
        self.run_git("commit", "-qm", "ignore")
        self.run_git("push", "-q")
        (self.root / "scratch").mkdir()
        (self.root / "scratch/blob").write_text("temporary")
        N.verify_saved(self.root, "sample", self.job)
        self.assertIn("NOT backed up", N.checkpoint_prompt("sample", self.job))

    def test_receipt_owner_and_remote_required(self):
        N.R.write(self.flow / "new-chat.json", self.job)
        a = type("Args", (), dict(target="t1", checkpoint_ready="abc123"))()
        with patch.dict(os.environ, HC_TERMINAL_ID="t2"):
            self.assertRaisesRegex(
                RuntimeError, "assigned", N.receipt, a, self.ctx, self.flow
            )
        with patch.dict(os.environ, HC_TERMINAL_ID="t1"), contextlib.redirect_stdout(
            io.StringIO()
        ):
            N.receipt(a, self.ctx, self.flow)
        self.assertTrue((self.flow / "checkpoint-abc123.json").exists())

    def test_active_workflow_refused(self):
        N.R.write(self.flow / "state.json", dict(state="implementing"))
        self.assertRaisesRegex(
            RuntimeError, "workflow", N.guard, self.flow, self.review
        )

    def test_worker_restarts_only_after_proof(self):
        self.job["state"] = "queued"
        N.R.write(self.flow / "new-chat.json", self.job)
        proof = N.verify_saved(self.root, "sample", self.job)
        N.R.write(self.flow / "checkpoint-abc123.json", proof)
        row = dict(state="live", status={"state": "idle"}, turn=1)
        sent = []

        def hc(*a):
            if a[0] == "get":
                return row
            sent.append(a)
            return {"started": True}

        with patch.object(N, "hc", side_effect=hc), patch.object(
            N, "validate"
        ), patch.object(N.time, "sleep"), patch.object(N, "restart") as restart:
            N.worker(type("A", (), {"worker": "abc123"})(), self.ctx, self.flow)
            restart.assert_called_once_with("t1")
        self.assertEqual(len(sent), 1)
        self.assertIn("checkpoint-ready", sent[0][2])
        self.assertEqual(N.R.read(self.flow / "new-chat.json")["state"], "started")

    def test_missing_receipt_never_restarts(self):
        self.job["state"] = "queued"
        N.R.write(self.flow / "new-chat.json", self.job)
        counter = [0]

        def hc(*a):
            if a[0] == "get":
                counter[0] += 1
                return dict(state="live", status={"state": "idle"}, turn=counter[0])
            return {"started": True}

        with patch.object(N, "hc", side_effect=hc), patch.object(
            N, "validate"
        ), patch.object(N.time, "sleep"), patch.object(N, "restart") as restart:
            self.assertRaisesRegex(
                RuntimeError,
                "without a verified",
                N.worker,
                type("A", (), {"worker": "abc123"})(),
                self.ctx,
                self.flow,
            )
            restart.assert_not_called()
        self.assertEqual(N.R.read(self.flow / "new-chat.json")["state"], "needs-you")

    def test_progress_owned_and_monotonic(self):
        N.R.write(self.flow / "new-chat.json", self.job)
        a = type(
            "Args",
            (),
            dict(target="t1", progress_token="abc123", stage="committing", detail=None),
        )()
        with patch.dict(os.environ, HC_TERMINAL_ID="t2"):
            self.assertRaisesRegex(
                RuntimeError, "another agent", N.report_progress, a, self.ctx, self.flow
            )
        with patch.dict(os.environ, HC_TERMINAL_ID="t1"), contextlib.redirect_stdout(
            io.StringIO()
        ):
            N.report_progress(a, self.ctx, self.flow)
            a.stage = "saving"
            self.assertRaisesRegex(
                RuntimeError, "backwards", N.report_progress, a, self.ctx, self.flow
            )
        self.assertEqual(
            N.R.read(self.flow / "progress-abc123.json")["stage"], "committing"
        )
        self.assertFalse((self.flow / "checkpoint-abc123.json").exists())

    def test_failure_retains_stage(self):
        job = dict(self.job, stage="pushing")
        N.state(self.flow, job, "needs-you", "Push rejected")
        out = N.R.read(self.flow / "new-chat.json")
        self.assertEqual(out["failed_stage"], "pushing")
        self.assertEqual(out["message"], "Push rejected")

    def test_prompt_requests_all_stages(self):
        text = N.checkpoint_prompt("sample", self.job)
        for stage in ("saving", "committing", "pushing", "failed"):
            self.assertIn("--stage " + stage, text)

    def test_retry_skips_saved_context_commit_and_push(self):
        self.assertEqual(N.retry_stage(self.root, "sample", self.job), "verifying")

    def test_retry_only_push_after_committed_change(self):
        (self.root / "code.txt").write_text("new")
        self.run_git("add", ".")
        self.run_git("commit", "-qm", "new")
        self.assertEqual(N.retry_stage(self.root, "sample", self.job), "pushing")

    def test_retry_only_commit_for_dirty_saved_context(self):
        (self.root / "code.txt").write_text("new")
        self.assertEqual(N.retry_stage(self.root, "sample", self.job), "committing")

    def test_retry_starts_context_if_missing(self):
        (self.packet / "context.md").write_text("no marker")
        self.assertEqual(N.retry_stage(self.root, "sample", self.job), "saving")

    def test_retry_refuses_wrong_branch(self):
        self.run_git("checkout", "-qb", "other")
        self.assertRaisesRegex(
            RuntimeError, "Branch changed", N.retry_stage, self.root, "sample", self.job
        )

    def test_retry_wrong_token_never_launches(self):
        N.R.write(self.flow / "new-chat.json", dict(self.job, state="needs-you"))
        a = type("A", (), dict(target="t1", retry="wrong"))()
        with patch.object(N, "launch_worker") as launch:
            self.assertRaisesRegex(
                RuntimeError, "changed", N.retry_job, a, self.ctx, self.flow
            )
            launch.assert_not_called()

    def test_retry_verifies_without_agent_save_turn(self):
        self.job.update(state="queued", resume_from="verifying")
        N.R.write(self.flow / "new-chat.json", self.job)
        row = dict(state="live", status={"state": "idle"}, turn=1)
        with patch.object(N, "hc", return_value=row) as hc, patch.object(
            N, "validate"
        ), patch.object(N, "restart") as restart:
            N.worker(type("A", (), {"worker": "abc123"})(), self.ctx, self.flow)
            restart.assert_called_once_with("t1")
            self.assertTrue(all(c.args[0] == "get" for c in hc.call_args_list))


if __name__ == "__main__":
    unittest.main()
