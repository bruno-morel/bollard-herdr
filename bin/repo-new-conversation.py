#!/usr/bin/env python3
"""Explicit fresh chat in the exact managed stream; never create or switch a checkout."""
import argparse, hashlib, importlib.util, json, os, re, shlex, subprocess as sp, sys, time, uuid
from pathlib import Path

BIN = Path(__file__).resolve().parent
sys.path.insert(0, str(BIN))
from repo_process import agent_running
import repo_operations as O
import repo_role_handoff as handoffs
import repo_roles as profiles

spec = importlib.util.spec_from_file_location("review", BIN / "repo-review.py")
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


def hc(*args):
    p = sp.run(["hc", "--json", *args], capture_output=True, text=True, timeout=20)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return json.loads(p.stdout)


def validate(row, root, stream, key):
    labels = row.get("labels") or {}
    status = row.get("status") or {}
    if (
        row.get("state") != "live"
        or labels.get("repo-tools.repo") != key
        or labels.get("repo-tools.stream") != stream
        or labels.get("repo-tools.role") not in ("studio", "work")
    ):
        raise RuntimeError(
            "Selected terminal is not this stream’s live lead conversation"
        )
    if not os.path.samefile(labels.get("repo-tools.checkout", ""), root):
        raise RuntimeError("Checkout mismatch; refresh the selected stream")
    if (
        not isinstance(status, dict)
        or status.get("state") not in ("idle", "done")
        or not agent_running(row)
    ):
        raise RuntimeError(
            "Finish/stop the current agent task first. A new conversation can only replace an idle managed agent."
        )
    # Only the managed supervisor provides the verified New chat menu.
    command = row.get("argv", [])
    if "repo_herdr.py" not in str(command):
        raise RuntimeError(
            "Use this terminal’s own New chat menu; it is not a managed Herdr supervisor"
        )
    return labels


ACTIVE = O.CHECKPOINT_ACTIVE


def paths(stream):
    ctx = R.resolve(stream)
    root, stream, review, packet, key = ctx
    return ctx, review.parents[2] / "agents" / key / stream / "workflow"


def guard(flow, review):
    if R.read(flow / "state.json", {}).get("state") in O.WORKFLOW_ACTIVE:
        raise RuntimeError(
            "Pause/finish the implementation workflow before starting a fresh conversation"
        )
    if R.read(review / "state.json", {}).get("state") in ("preflight", "reviewing"):
        raise RuntimeError("Wait for the current review to finish")


def config(root, name):
    p = sp.run(
        ["git", "-C", str(root), "config", "--get", name],
        capture_output=True,
        text=True,
    )
    return p.stdout.strip() if p.returncode == 0 else ""


def push_destination(root, stream):
    branch = "codex/" + stream
    remote = config(root, "branch." + branch + ".remote") or "origin"
    ref = config(root, "branch." + branch + ".merge") or "refs/heads/" + branch
    if (
        remote == "."
        or remote.startswith("-")
        or remote not in R.git(root, "remote").splitlines()
    ):
        raise RuntimeError(
            "Configure a remote for this stream before saving and restarting"
        )
    if ref != "refs/heads/" + branch:
        raise RuntimeError(
            "Checkpoint push must target this stream branch, never main or another branch"
        )
    url = R.git(root, "remote", "get-url", "--push", remote)
    return dict(
        remote=remote, ref=ref, url_hash=hashlib.sha256(url.encode()).hexdigest()
    )


def verify_saved(root, stream, job):
    if R.git(root, "symbolic-ref", "--quiet", "--short", "HEAD") != "codex/" + stream:
        raise RuntimeError("Branch changed; restart refused")
    if R.git(root, "status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError(
            "Uncommitted or untracked files remain; save intentional changes or explain the blocker"
        )
    rel = "docs/handoffs/" + stream + "/context.md"
    path = R.safe(root, rel)
    if not path.is_file() or job["token"] not in path.read_text():
        raise RuntimeError("The current checkpoint is missing from context.md")
    R.git(root, "ls-files", "--error-unmatch", "--", rel)
    if job.get("handoff"):
        note = handoffs.notes(stream, job["handoff"])
        saved = R.safe(root, note)
        if not saved.is_file() or job["token"] not in saved.read_text():
            raise RuntimeError(
                "Save the outgoing role progress note with this checkpoint token first"
            )
        R.git(root, "ls-files", "--error-unmatch", "--", note)
    destination = push_destination(root, stream)
    if destination != job["destination"]:
        raise RuntimeError("Push destination changed; restart refused")
    head = R.git(root, "rev-parse", "HEAD")
    # Query the push destination directly; a stale tracking ref is not proof of backup.
    url = R.git(root, "remote", "get-url", "--push", destination["remote"])
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    reply = sp.run(
        ["git", "ls-remote", "--exit-code", "--", url, destination["ref"]],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=25,
        env=env,
    )
    if reply.returncode or not any(
        line.split() == [head, destination["ref"]] for line in reply.stdout.splitlines()
    ):
        raise RuntimeError(
            "Remote checkpoint could not be verified. Resolve push/network/authentication first; conversation stays open"
        )
    if R.git(root, "rev-parse", "HEAD") != head or R.git(
        root, "status", "--porcelain", "--untracked-files=all"
    ):
        raise RuntimeError("Files changed during verification; restart refused")
    return dict(head=head, context_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def checkpoint_prompt(stream, job):
    command = shlex.join(
        [
            str(BIN / "repo-new-conversation.py"),
            stream,
            "--target",
            job["target"],
            "--checkpoint-ready",
            job["token"],
        ]
    )
    report = shlex.join(
        [
            str(BIN / "repo-new-conversation.py"),
            stream,
            "--target",
            job["target"],
            "--progress-token",
            job["token"],
            "--stage",
        ]
    )
    dest = job["destination"]
    resume = job.get("resume_from", "saving")
    extra = ""
    if job.get("handoff"):
        extra = f"Before committing, save your role progress in {handoffs.notes(stream, job['handoff'])}, including Checkpoint: {job['token']}. Keep shared context current and preserve all other role notes. The destination role is {job['handoff']['id']}; record next steps for it. The controller will open that role after verification, not continue this role."
    return f"""{extra}
The user selected Save checkpoint and start a new conversation in this SAME stream.
Resume from {resume}. This is attempt {job.get('attempt',1)} of the SAME checkpoint token. Inspect actual files first. Preserve the saved context if it still accurately captures progress. Do NOT repeat a successful commit or push: if the checkout/context is already committed, skip committing; if the exact current commit is already on the designated remote, skip pushing. If new changes invalidate that saved work, save only what is missing. Report only the stages you actually enter.
Do this bounded handoff now; do not continue implementation or start tests/review/helpers.
Before step 1 run: {report} saving
Before step 2 run: {report} committing
Before step 3 run: {report} pushing
If any step fails, run: {report} failed --detail "brief blocker (no secrets)" and explain it in chat. These are progress reports, not evidence of success.
1. Update docs/handoffs/{stream}/context.md with the actual current request, completed progress, decisions, unfinished work, next concrete steps, known failures, exact existing validation results/limitations, useful paths and how to resume. Preserve prior important context. Include the line Checkpoint: {job['token']}. Update implementation-plan.md if needed; do not overwrite handoff source documents or invent history.
2. Inspect Git status, staged changes and diffs. Commit all intentional source/docs/test changes for this stream, including unfinished work as an honest WIP checkpoint. Preserve existing staged work. Do not discard, stash, amend, reset, force-add ignored assets, add secrets, or commit unrelated/uncertain files. If ownership or sensitive content is unclear, explain the blocker and stop with the conversation open. Durable artifacts belong in tracked docs/assets; scratch and local runtime are NOT backed up by this checkpoint. Record any needed ignored artifacts as a limitation and ask if they must be preserved elsewhere.
3. Push ONLY the stream branch to remote {dest['remote']}, ref {dest['ref']}. You are explicitly authorized to commit and push this checkpoint. Never push to main, force-push, bypass hooks, merge/rebase, change remotes, deploy, reset Claude budgets or claim completion/review approval. If the push or hooks fail, report the error and stop; do not broaden the task to fix everything.
4. Run {command} as your LAST operation. It independently verifies clean tracked/untracked state, the saved context and the actual remote commit. If it fails, explain why and stop; no automatic test reruns. On success, end your turn and wait. The controller will exit this chat normally and start a fresh one with the selected role and shared handoff. Do not exit or start the new conversation yourself.
"""


STAGES = O.CHECKPOINT_STAGES
LABELS = O.CHECKPOINT_LABELS


def state(flow, job, phase, message):
    O.transition(job, phase, message)
    R.write(flow / "new-chat.json", job)


def report_progress(a, ctx, flow):
    job = R.read(flow / "new-chat.json", {})
    if (
        job.get("state") != "saving"
        or job.get("token") != a.progress_token
        or job.get("target") != a.target
        or os.environ.get("HC_TERMINAL_ID") != a.target
    ):
        raise RuntimeError(
            "Progress belongs to another agent or an inactive checkpoint"
        )
    with R.lock(flow / "progress.lock"):
        path = flow / ("progress-" + job["token"] + ".json")
        old = R.read(path, {})
        if old.get("stage") == "failed":
            raise RuntimeError("Checkpoint failure already reported")
        if a.stage != "failed" and STAGES.index(a.stage) < STAGES.index(
            old.get("stage", "saving")
        ):
            raise RuntimeError("Checkpoint progress cannot move backwards")
        R.write(
            path,
            dict(
                token=job["token"],
                stage=a.stage,
                failed_stage=old.get("stage", job.get("stage", "saving")),
                detail=(a.detail or "")[:500],
                at=R.now(),
            ),
        )
    print(json.dumps(dict(message="Checkpoint progress reported", stage=a.stage)))


def menu_ready(text):
    return "Choice:" in text and ("n: new chat" in text or "n / new: START NEW" in text)


def restart(target, start=True):
    sent = hc("send", target, "/exit", "--if", "idle")
    if sent.get("started") is False:
        raise RuntimeError("Agent was no longer idle; restart stopped")
    for _ in range(24):
        time.sleep(0.5)
        current = hc("get", target)
        if current.get("state") != "live":
            raise RuntimeError(
                "Terminal exited. Reopen with --new-chat; checkpoint is saved"
            )
        if not agent_running(current):
            r = sp.run(
                ["hc", "read", target], capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0 and menu_ready(r.stdout[-2000:]):
                if start:
                    hc("send", target, "n")
                return
    raise RuntimeError(
        "Checkpoint saved, but New chat menu was not confirmed. Exit normally and choose n; no automatic retry"
    )


def finish_checkpoint(root, stream, flow, job, at_menu=False):
    handoff = job.get("handoff")
    if not handoff:
        if at_menu:
            hc("send", job["target"], "n")
        else:
            restart(job["target"])
        return
    if job.get("handoff_dispatched"):
        raise RuntimeError(
            "Handoff launch was already requested. Inspect the destination conversation; it will not be launched twice."
        )
    handoffs.validate(root, handoff)
    import repo_herdr as H

    api = H.agent_api()
    # Check destination ownership again after the checkpoint, before exiting anything.
    source = hc("get", job["target"])
    handoffs.prepare(api, root, stream, source, handoff["id"], H.local_terminals(root))
    if not at_menu:
        restart(job["target"], start=False)
    # Persist dispatch before the side effect: uncertain acknowledgements must not replay.
    job["handoff_dispatched"] = True
    R.write(flow / "new-chat.json", job)
    if handoff["base"] == handoff["source_base"]:
        pref = api.preferences(root, stream, handoff["base"])
        profiles.select(root, pref, handoff["base"], handoff["id"])
        hc("send", job["target"], "n")
        job["destination_terminal"] = job["target"]
    else:
        sp.run(
            [
                sys.executable,
                str(BIN / "repo_herdr.py"),
                handoff["base"],
                stream,
                "--profile",
                handoff["id"],
                "--agent",
                handoff["agent"],
                "--new-chat",
            ],
            cwd=root,
            check=True,
        )
        rows = H.local_terminals(root)
        matches = [
            r
            for r in rows
            if r.get("state") == "live"
            and (r.get("labels") or {}).get("repo-tools.profile") == handoff["id"]
        ]
        if len(matches) == 1:
            job["destination_terminal"] = matches[0]["address"]


def receipt(a, ctx, flow):
    root, stream, review, packet, key = ctx
    job = R.read(flow / "new-chat.json", {})
    if (
        job.get("state") != "saving"
        or job.get("token") != a.checkpoint_ready
        or job.get("target") != a.target
        or os.environ.get("HC_TERMINAL_ID") != a.target
    ):
        raise RuntimeError(
            "Only the assigned current agent can acknowledge this pending checkpoint"
        )
    proof = verify_saved(root, stream, job)
    R.write(
        flow / ("checkpoint-" + job["token"] + ".json"),
        dict(proof, token=job["token"], at=R.now()),
    )
    print(
        json.dumps(
            dict(
                message="Context, clean checkout and remote commit verified. End your turn; the controller will restart this conversation."
            )
        )
    )


def retry_stage(root, stream, job):
    if R.git(root, "symbolic-ref", "--quiet", "--short", "HEAD") != "codex/" + stream:
        raise RuntimeError("Branch changed; retry refused")
    if push_destination(root, stream) != job["destination"]:
        raise RuntimeError("Push destination changed; inspect it before retrying")
    path = R.safe(root, "docs/handoffs/" + stream + "/context.md")
    if not path.is_file() or job["token"] not in path.read_text():
        return "saving"
    if R.git(root, "status", "--porcelain", "--untracked-files=all"):
        return "committing"
    try:
        verify_saved(root, stream, job)
    except (RuntimeError, sp.SubprocessError):
        return "pushing"
    return "verifying"


def retry_job(a, ctx, flow):
    root, stream, review, packet, key = ctx
    with R.lock(flow / "new-chat.lock"), R.lock(flow / "new-chat-worker.lock"), R.lock(
        flow / "launch.lock"
    ), R.lock(review / "launch.lock"):
        job = R.read(flow / "new-chat.json", {})
        O.require_retry("checkpoint", job, a.retry, target=a.target)
        guard(flow, review)
        row = hc("get", a.target)
        if job.get("failed_stage") == "restarting":
            # An accepted New chat command might already have started a new agent.
            if agent_running(row):
                raise RuntimeError(
                    "An agent is already running after restart. Inspect its conversation; it will not be exited again."
                )
            labels = row.get("labels") or {}
            if (
                row.get("state") != "live"
                or "repo_herdr.py" not in str(row.get("argv", []))
                or labels.get("repo-tools.role") not in ("studio", "work")
                or labels.get("repo-tools.repo") != key
                or labels.get("repo-tools.stream") != stream
                or not os.path.samefile(labels.get("repo-tools.checkout", ""), root)
            ):
                raise RuntimeError("Restart terminal identity changed")
            verify_saved(root, stream, job)
            r = sp.run(
                ["hc", "read", a.target], capture_output=True, text=True, timeout=10
            )
            if r.returncode or not menu_ready(r.stdout[-2000:]):
                raise RuntimeError(
                    "New chat menu is not available; inspect the terminal before retrying"
                )
            finish_checkpoint(root, stream, flow, job, at_menu=True)
            state(
                flow,
                job,
                "started",
                "Saved checkpoint verified. Fresh conversation requested from the existing menu.",
            )
            print(json.dumps(job))
            return
        validate(row, root, stream, key)
        job["resume_from"] = retry_stage(root, stream, job)
        job["attempt"] = job.get("attempt", 1) + 1
        job.pop("failed_stage", None)
        for name in ("progress-", "checkpoint-"):
            (flow / (name + job["token"] + ".json")).unlink(missing_ok=True)
        state(
            flow,
            job,
            "queued",
            "Retrying from "
            + job["resume_from"]
            + "; completed checkpoint work is preserved.",
        )
    launch_worker(root, stream, job)
    print(json.dumps(job))


def launch_worker(root, stream, job):
    args = [
        "run",
        "--bg",
        "--keep",
        "--no-parent",
        "--no-notify",
        "--name",
        "cp-" + job["token"] + "-" + str(job.get("attempt", 1)),
        "--cwd",
        str(root),
        "--label",
        "repo-tools.kind=checkpoint",
    ]
    try:
        hc(
            *args,
            "--",
            sys.executable,
            str(BIN / "repo-new-conversation.py"),
            stream,
            "--worker",
            job["token"],
        )
    except Exception:
        raise RuntimeError(
            "Checkpoint launch was not confirmed. Inspect status before retrying; no automatic replay."
        )


def worker(a, ctx, flow):
    root, stream, review, packet, key = ctx
    with R.lock(flow / "new-chat-worker.lock"), R.lock(flow / "launch.lock"), R.lock(
        review / "launch.lock"
    ):
        job = R.read(flow / "new-chat.json", {})
        if job.get("token") != a.worker or job.get("state") != "queued":
            raise RuntimeError("Checkpoint request changed; nothing sent")
        try:
            guard(flow, review)
            initial = hc("get", job["target"])
            validate(initial, root, stream, key)
            state(
                flow,
                job,
                "saving",
                "Saving context, committing intended changes and pushing the stream branch…",
            )
            if job.get("resume_from") == "verifying":
                state(
                    flow,
                    job,
                    "verifying",
                    "Rechecking the saved checkpoint; no context rewrite, commit or push needed…",
                )
                verify_saved(root, stream, job)
                state(
                    flow,
                    job,
                    "restarting",
                    "Checkpoint verified. Opening fresh conversation…",
                )
                finish_checkpoint(root, stream, flow, job)
                state(
                    flow,
                    job,
                    "started",
                    "Checkpoint verified. Fresh conversation requested.",
                )
                return
            job["stage"] = job.get("resume_from", "saving")
            sent = hc(
                "send", job["target"], checkpoint_prompt(stream, job), "--if", "idle"
            )
            if sent.get("started") is False:
                raise RuntimeError(
                    "Agent is no longer idle; no checkpoint task was started"
                )
            deadline = time.monotonic() + 1200
            while time.monotonic() < deadline:
                time.sleep(2)
                progress = R.read(flow / ("progress-" + job["token"] + ".json"), {})
                stage = progress.get("stage")
                if stage == "failed":
                    job["stage"] = progress.get(
                        "failed_stage", job.get("stage", "saving")
                    )
                    raise RuntimeError(
                        progress.get("detail")
                        or "Agent reported a checkpoint failure; inspect the conversation"
                    )
                if stage in ("saving", "committing", "pushing") and stage != job.get(
                    "stage"
                ):
                    job["stage"] = stage
                    job.setdefault("history", []).append(
                        dict(stage=stage, at=progress.get("at"))
                    )
                proof = R.read(flow / ("checkpoint-" + job["token"] + ".json"), {})
                row = hc("get", job["target"])
                st = (row.get("status") or {}).get("state")
                if row.get("state") != "live":
                    raise RuntimeError(
                        "Agent exited before checkpoint verification; reopen its saved conversation"
                    )
                if proof and st in ("idle", "done"):
                    validate(row, root, stream, key)
                    state(
                        flow,
                        job,
                        "verifying",
                        "Checking saved context and the remote commit before restart…",
                    )
                    current = verify_saved(root, stream, job)
                    if any(current[k] != proof.get(k) for k in current):
                        raise RuntimeError(
                            "Checkpoint changed after acknowledgement; restart refused"
                        )
                    state(
                        flow,
                        job,
                        "restarting",
                        "Checkpoint verified. Opening fresh conversation in the same stream…",
                    )
                    finish_checkpoint(root, stream, flow, job)
                    state(
                        flow,
                        job,
                        "started",
                        "Checkpoint committed and pushed. Fresh conversation requested in the same stream.",
                    )
                    return
                if (
                    not proof
                    and st in ("idle", "done")
                    and row.get("turn", 0) > initial.get("turn", 0)
                ):
                    raise RuntimeError(
                        "Agent ended without a verified checkpoint. Read its explanation; the conversation was not restarted"
                    )
                job["message"] = (
                    "Waiting for your approval/input in the current conversation…"
                    if st == "blocked"
                    else LABELS.get(job.get("stage"), "Saving checkpoint") + "…"
                )
                job["heartbeat"] = time.time()
                R.write(flow / "new-chat.json", job)
            raise RuntimeError(
                "Checkpoint was not confirmed within 20 minutes. Current agent was left running; inspect its progress before retrying"
            )
        except Exception as e:
            state(flow, job, "needs-you", str(e))
            raise


def main():
    p = argparse.ArgumentParser(
        description="Save context, commit and push the current stream before opening fresh chat context."
    )
    p.add_argument("stream")
    p.add_argument("--target")
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument(
        "--handoff-profile", help="Checkpoint then hand off to a configured role"
    )
    p.add_argument("--checkpoint-ready")
    p.add_argument("--worker")
    p.add_argument("--progress-token")
    p.add_argument("--stage", choices=["saving", "committing", "pushing", "failed"])
    p.add_argument("--detail")
    p.add_argument("--retry", metavar="CHECKPOINT_TOKEN")
    a = p.parse_args()
    ctx, flow = paths(a.stream)
    root, stream, review, packet, key = ctx
    if a.status:
        job = R.read(flow / "new-chat.json", {})
        print(json.dumps(O.describe("checkpoint", job)))
        return
    if a.worker:
        return worker(a, ctx, flow)
    if not a.target or not re.fullmatch("t[0-9a-z]+", a.target):
        p.error("Select an exact local terminal ID")
    if a.retry:
        return retry_job(a, ctx, flow)
    if a.progress_token:
        if not a.stage:
            p.error("--progress-token requires --stage")
        return report_progress(a, ctx, flow)
    if a.checkpoint_ready:
        return receipt(a, ctx, flow)
    with R.lock(flow / "new-chat.lock"):
        with R.lock(flow / "launch.lock"), R.lock(review / "launch.lock"):
            guard(flow, review)
            labels = validate(hc("get", a.target), root, stream, key)
            handoff = None
            if a.handoff_profile:
                import repo_herdr as H

                handoff = handoffs.prepare(
                    H.agent_api(),
                    root,
                    stream,
                    hc("get", a.target),
                    a.handoff_profile,
                    H.local_terminals(root),
                )
            destination = push_destination(root, stream)
            if not a.confirm:
                print(
                    json.dumps(
                        dict(
                            ready=True,
                            message="Ask the current agent to save context, commit intended changes and push this stream branch; restart only after verification.",
                        )
                    )
                )
                return
            old = R.read(flow / "new-chat.json", {})
            if old.get("state") in ACTIVE:
                raise RuntimeError(
                    "A checkpoint request is already pending; inspect its progress before retrying"
                )
            job = dict(
                token=uuid.uuid4().hex[:16],
                target=a.target,
                destination=destination,
                handoff=handoff,
                stream=stream,
            )
            state(
                flow,
                job,
                "queued",
                "Checkpoint requested; current conversation will save context and push before restart.",
            )
        launch_worker(root, stream, job)
        print(
            json.dumps(
                dict(
                    ready=True,
                    state="queued",
                    terminal=a.target,
                    message=job["message"],
                )
            )
        )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, sp.SubprocessError) as e:
        sys.exit("New conversation: " + str(e))
