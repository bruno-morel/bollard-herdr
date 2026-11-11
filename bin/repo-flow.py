#!/usr/bin/env python3
"""Shared desktop/TUI workflow. Runtime records outside Git; review allowance owned by repo-review."""
import argparse
import repo_operations as O
from repo_risk_policy import POLICY as RISK_POLICY
from collections import deque
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess as sp
import sys
import time
import uuid
import repo_helper_context as C
from repo_flow_menu import run_menu

BIN = Path(__file__).resolve().parent
ACTIVE = O.WORKFLOW_ACTIVE


def module(name):
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), BIN / (name + ".py")
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


H = module("repo_herdr")
A = H.agent_api()
R = module("repo-review")
G = module("repo-completion")


def fail(text):
    raise RuntimeError(text)


def command(argv, **kw):
    return sp.run([str(x) for x in argv], check=True, **kw)


def launch_command(argv, cwd):
    """Stream setup logs and retain its diagnostic for the desktop/TUI status."""
    tail = deque(maxlen=24)
    diagnostic = None
    with sp.Popen(
        [str(x) for x in argv],
        cwd=cwd,
        stdout=sp.PIPE,
        stderr=sp.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    ) as process:
        for line in process.stdout:
            print(line, end="", flush=True)
            clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line).strip()
            if clean:
                tail.append(clean[:1000])
                if re.match(r"(?:repo-herdr|repo-agent|work|studio): ", clean):
                    diagnostic = clean[:1000]
        code = process.wait()
    if code:
        fail(
            diagnostic
            or (tail[-1] if tail else f"{Path(argv[0]).name} exited with status {code}")
        )


def read(p, default=None):
    return R.read(p, default)


def write(p, value):
    R.write(p, value)


def hc(*args):
    timeout = int(args[args.index("--timeout") + 1]) + 15 if "--timeout" in args else 25
    result = sp.run(
        ["hc", *args, "--json"], capture_output=True, text=True, timeout=timeout
    )
    if result.returncode:
        fail(result.stderr.strip() or result.stdout.strip() or "Herdr command failed")
    return json.loads(result.stdout)


def status(row):
    s = row.get("status") or {}
    return s.get("state") if isinstance(s, dict) else s


def context(stream=None):
    try:
        root = A.root_at()
    except RuntimeError:
        fail("run inside a Git-controlled source tree")
    stream = A.slug(stream) if stream else A.current(root)
    pref = A.preferences(root, stream, "work")
    return root, stream, pref.parent / "workflow", pref.parents[1].name


def details(root, stream, key):
    target = H.target_for(A, root, stream)
    rows = (
        [
            hc("get", r["address"])
            for r in hc("ls", "--all").get("terminals", [])
            if "/" not in r["address"]
        ]
        if target and target.is_dir()
        else []
    )
    return target, [
        r
        for r in rows
        if r.get("labels", {}).get("repo-tools.repo") == key
        and r.get("labels", {}).get("repo-tools.stream") == stream
    ]


def primary(rows, role):
    found = [
        r
        for r in rows
        if r["state"] == "live" and r.get("labels", {}).get("repo-tools.role") == role
    ]
    if len(found) > 1:
        fail("multiple " + role + " terminals; resolve them before continuing")
    return found[0] if found else None


def agent_foreground(row):
    from repo_process import agent_running

    return agent_running(row)


def idle(row):
    return (
        row
        and row["state"] == "live"
        and status(row) in ("idle", "done")
        and agent_foreground(row)
    )


def phase(runtime, job, state, message):
    O.transition(job, state, message)
    write(runtime / "state.json", job)
    print(message, flush=True)
    if os.environ.get("HC_TERMINAL_ID"):
        data = {
            k: job.get(k) for k in ("state", "message", "stream", "updated", "token")
        }
        command(
            [
                "hc",
                "label",
                os.environ["HC_TERMINAL_ID"],
                "repo-flow.status=" + json.dumps(data),
            ],
            stdout=sp.DEVNULL,
        )


def check_cancel(runtime, job):
    if (runtime / ("pause-" + job["token"])).exists():
        fail(
            "Paused. Existing agents and Docker remain running; no further task or review was started."
        )


def managed_open(root, stream, role, agent, task_file=None):
    args = [BIN / role, "herdr", stream, "--agent", agent]
    if task_file:
        args += ["--task-file", task_file, "--new-chat"]
    launch_command(args, cwd=root)
    target, rows = details(
        root, stream, A.preferences(root, stream, "work").parents[1].name
    )
    row = primary(rows, role)
    if not row:
        fail(
            "launch did not produce a managed "
            + role
            + " terminal; inspect hc ls --all"
        )
    return target, row


def wait_turn(row, runtime, job, started=False):
    deadline = time.monotonic() + 3600
    address = row["address"]
    initial_turn = row.get("turn", 0)
    while time.monotonic() < deadline:
        check_cancel(runtime, job)
        row = hc("get", address)
        state = status(row)
        # Launched with the task as the first prompt: wait for its first completed turn.
        if idle(row) and (started or row.get("turn", 0) > initial_turn):
            return row
        if row["state"] != "live" or state in ("blocked", "error"):
            fail(
                "Agent needs attention. Open its conversation; the workflow has stopped."
            )
        if row.get("reported") and not agent_foreground(row):
            fail(
                "Agent exited or is in its resume menu. Resume it before continuing the workflow."
            )
        result = hc("wait", address, "--timeout", "30")
        # Status is read again; an idle startup without a completed turn is not success.
        if result.get("reason") == "message":
            fail("Workflow received a message; inspect it before continuing.")
    fail("Agent did not finish within one hour. No review was started.")


def send_task(row, text, runtime, job):
    row = hc("get", row["address"])
    if not idle(row):
        fail(
            "The "
            + job["role"]
            + " agent is busy, blocked, or not at its prompt. Return to its pane first."
        )
    check_cancel(runtime, job)
    # Reserve before delivery. Never retry an ambiguous send automatically.
    job["delivery"] = "sending"
    write(runtime / "state.json", job)
    result = hc(
        "send", row["address"], text, "--if", "idle", "--wait", "--timeout", "45"
    )
    if (result.get("wait") or {}).get("reason") == "not_started" or result.get(
        "started"
    ) is not True:
        fail(
            "Task delivery was not confirmed. Inspect the agent conversation before trying again."
        )
    job["delivery"] = "sent"
    write(runtime / "state.json", job)
    return wait_turn(row, runtime, job, started=True)


def task_prompt(job, fix=False):
    task = job.get("task", "").strip()
    receipt = (
        f"work flow ready {job['stream']} --token {job['token']} --step {job['step']}"
    )
    return (
        RISK_POLICY
        + "\n\n"
        + f"""The user selected Implement through review for this stream. This authorizes the requested implementation and normal validation, within the handoff scope.
Read the current handoff, context, implementation plan, repository instructions and actual code. Preserve others' changes. {'Fix the concrete findings in the latest review report and failed check logs.' if fix else 'Implement the agreed feature and meaningful tests.'}
User task: {task or 'Use the existing implementation handoff; ask if its scope is incomplete.'}
Update implementation-plan.md and context.md; fill review-input.json with every acceptance criterion and real integration/e2e checks. Run those normal checks and inspect actual behavior before reporting ready.
Do not weaken assertions, skip tests, reduce acceptance criteria, add fake success, or claim 100% correctness. If evidence or a decision is missing, ask the user and stop.
A separate workflow controller owns the final review. Do not run Claude, work review, or start any other agents. Do not edit the review counter or workflow state. No merges, pushes or deployment.
When implementation, documentation and normal checks are complete, run `{receipt}` as your LAST operation, then end your turn and wait. If that command fails, resolve the stated issue or report a blocker. Do not modify files after that receipt. The controller will run the bounded Claude review and, if appropriate, send one focused fix task back to this same conversation.
"""
    )


def ready(args):
    root, stream, runtime, key = context(args.stream)
    job = read(runtime / "state.json")
    if (
        not job
        or job.get("token") != args.token
        or job.get("step") != args.step
        or job.get("state") not in ("implementing", "fixing")
    ):
        fail("receipt does not match an active implementation step")
    target = A.checkout(root, stream)
    if os.environ.get("HC_TERMINAL_ID") != job.get("lead"):
        fail("only the assigned Work terminal can report this step ready")
    check_cancel(runtime, job)
    c = R.load_config(target, stream)
    plan = G.assessment(target, stream)
    if not set(plan["checks"]) <= {x["id"] for x in c["checks"]}:
        fail("Validation plan check IDs must exist in review-input.json")
    if plan.get("limitations") or plan.get("review_deferred_reason"):
        fail(
            "Resolve declared limitations before requesting verified workflow completion"
        )
    write(
        runtime / ("ready-" + args.token + ".json"),
        {"step": args.step, "fingerprint": R.fingerprint(target, stream, c)},
    )
    print(
        "Risk assessment and source receipt recorded. End your turn; checks and independent review still must pass."
    )


def receipt_valid(root, stream, runtime, job):
    r = read(runtime / ("ready-" + job["token"] + ".json"), {})
    return r.get("step") == job["step"] and r.get("fingerprint") == R.fingerprint(
        root, stream, R.load_config(root, stream)
    )


def review_wait(root, stream, runtime, job, key):
    rr = R.resolve(stream)
    review_dir = rr[2]
    before = R.snapshot_status(root, stream, review_dir)
    if before.get("calls", 0) >= 2:
        fail("Both Claude calls are used. No new review cycle was authorized.")
    args = argparse.Namespace(
        base=None, follow_up=before.get("calls", 0) == 1, new_cycle=False
    )
    check_cancel(runtime, job)
    R.launch(*rr, args)
    state = read(review_dir / "state.json")
    if not state:
        fail("Review inputs are incomplete; no review started")
    expected = state["token"]
    cycle = state["cycle"]
    phase(
        runtime,
        job,
        "reviewing",
        "Running checks, then bounded Claude review; source edits are paused.",
    )
    terminal_name = "review-" + key[:8] + "-" + expected[:10]
    deadline = time.monotonic() + 2400
    while time.monotonic() < deadline:
        check_cancel(runtime, job)
        state = R.snapshot_status(root, stream, review_dir)
        if state.get("token") != expected or state.get("cycle") != cycle:
            fail("Review was replaced externally; inspect the report before continuing")
        if state["state"] not in ("preflight", "reviewing"):
            return state
        hc(
            "wait",
            terminal_name,
            "--output",
            "REPO_REVIEW_FINISHED:" + expected,
            "--timeout",
            "30",
        )
    fail(
        "Review is still running or unavailable. Inspect Review; no retry was launched."
    )


def perform(runtime, job):
    root = Path(job["root"])
    stream = job["stream"]
    key = job["key"]
    role = job["role"]
    action = job["action"]
    os.chdir(root)
    check_cancel(runtime, job)
    phase(runtime, job, "preparing", "Preparing " + role.title() + " / " + stream)
    target, rows = details(root, stream, key)
    if action in ("prepare", "implement"):
        other = primary(rows, "studio")
        if (
            other
            and not idle(other)
            and (other.get("foreground") or {}).get("name")
            not in ("zsh", "bash", "sh", "fish")
        ):
            fail(
                "Studio is still working or needs attention. Finish its current edits before handing off."
            )
    if action == "prepare":
        target = A.checkout(root, stream)
        command([BIN / "studio", "handoff"], cwd=target)
        text = (
            A.prompt(target, stream, "work")
            + "\nRead the latest handoff. Update implementation-plan.md with scope, steps, tests and unresolved questions. Preserve implementation progress. Report readiness, then wait for approval before coding.\n"
        )
    elif action == "implement":
        target = A.checkout(root, stream)
        A.packet(target, stream)
        if not any(
            (target / "docs/handoffs" / stream / f).is_file()
            for f in ("implementation.md", "codex-prompt.md")
        ):
            fail(
                "Prepare implementation first; this stream has no implementation handoff."
            )
        job["step"] = 1
        phase(runtime, job, "implementing", "Implementing and running normal checks")
        text = task_prompt(job)
    else:
        text = ""
    row = primary(rows, role)
    if row and (
        job.get("agent")
        and row.get("labels", {}).get("repo-tools.agent") != job["agent"]
    ):
        fail(
            "This role is already using another agent. Switch it from its pane before continuing."
        )
    if (
        action == "implement"
        and row
        and row.get("labels", {}).get("repo-tools.agent") == "claude"
    ):
        fail(
            "Automated implementation uses Codex or Cursor; Claude is reserved for final review."
        )
    if action == "open":
        target, row = managed_open(root, stream, role, job["agent"])
        os.chdir(target)
        command(
            [
                "hc",
                "label",
                os.environ["HC_TERMINAL_ID"],
                "repo-tools.checkout=" + str(target),
            ],
            stdout=sp.DEVNULL,
        )
        job["lead"] = row["address"]
        phase(
            runtime,
            job,
            "ready",
            "Opened " + role.title() + ". Continue in its conversation.",
        )
        return
    taskfile = runtime / (job["token"] + "-task.txt")
    taskfile.write_text(text)
    if row:
        if not idle(row):
            fail(
                "The existing "
                + role.title()
                + " agent is busy or in its resume menu. Continue there first."
            )
        job["lead"] = row["address"]
        write(runtime / "state.json", job)
        send_task(row, text, runtime, job)
    else:
        # The first task is part of startup, never pasted into a booting terminal.
        target, row = managed_open(root, stream, role, job["agent"], taskfile)
        job["lead"] = row["address"]
        write(runtime / "state.json", job)
        wait_turn(dict(row, turn=0), runtime, job)
    os.chdir(target)
    command(
        [
            "hc",
            "label",
            os.environ["HC_TERMINAL_ID"],
            "repo-tools.checkout=" + str(target),
        ],
        stdout=sp.DEVNULL,
    )
    if action == "prepare":
        if not (target / "docs/handoffs" / stream / "implementation-plan.md").is_file():
            fail("Agent stopped without an implementation plan; read its questions.")
        phase(
            runtime,
            job,
            "ready",
            "Implementation preparation finished. Read its plan and questions before implementing.",
        )
        return
    # At most four lead turns. Failed checks consume no Claude allowance; never unbounded retries.
    for step in range(1, 5):
        if not receipt_valid(target, stream, runtime, job):
            fail(
                "Agent finished without current, complete implementation evidence. Read its questions; no Claude review started."
            )
        result = review_wait(target, stream, runtime, job, key)
        if result["state"] == "verified":
            completion = G.evaluate(G.T.context(stream), require_review=True)
            write(runtime / "completion.json", completion)
            phase(
                runtime,
                job,
                "verified",
                "Verified for this version. Review the changes; merging remains your decision.",
            )
            return
        if result["state"] != "changes-required":
            fail(
                result.get("reason")
                or "Review incomplete; open Review before continuing."
            )
        if result.get("calls", 0) >= 2:
            fail(
                "The follow-up still found issues. Both Claude calls are used; inspect the report."
            )
        if step == 4:
            fail(
                "Automatic fix limit reached. Inspect the remaining failures; no further agent turn started."
            )
        job["step"] = step + 1
        phase(runtime, job, "fixing", "Fixing review findings or failing normal checks")
        send_task(hc("get", job["lead"]), task_prompt(job, fix=True), runtime, job)


def launch(args):
    root, stream, runtime, key = context(args.stream)
    with H.locked(
        runtime / "launch.lock", "Another workflow is launching for this stream"
    ):
        R.ensure_tests_idle(runtime.parents[3] / "review" / key / stream)
        old = read(runtime / "state.json", {})
        if getattr(args, "retry_token", None):
            O.require_retry("workflow", old, args.retry_token)
            args.action = "open"
            args.role = old["role"]
            args.agent = old["agent"]
        if old.get("state") in ACTIVE:
            address = old.get("terminal")
            if address:
                row = hc("get", address)
                if row["state"] == "live" and "repo-flow.py" in " ".join(
                    (row.get("foreground") or {}).get("argv", [])
                ):
                    fail(
                        "A workflow already owns this stream. Use status or Pause first."
                    )
            # A kept recovery shell is not a live controller; no automatic prompt replay.
            fail(
                "A previous workflow needs attention. Use work flow pause, inspect its agent, then retry explicitly."
            )
        agent = args.agent or "codex"
        if args.action == "implement" and agent == "claude":
            fail(
                "Claude is reserved for bounded review; use Codex or Cursor for implementation"
            )
        target, rows = details(root, stream, key)
        if args.action != "open" and target is None:
            fail("Open a stream first")
        role = "work" if args.action in ("prepare", "implement") else args.role
        existing = primary(rows, role)
        if args.action != "open" and existing and not idle(existing):
            fail("The " + role + " agent is busy or needs attention; no task was sent")
        if args.action in ("implement", "prepare"):
            review = R.resolve(stream)
            if R.snapshot_status(review[0], stream, review[2])["state"] in (
                "preflight",
                "reviewing",
            ):
                fail("A review is active; wait before changing this stream.")
        if args.action == "implement":
            review = R.resolve(stream)
            if read(review[2] / "state.json", {}).get("calls", 0) >= 2:
                fail(
                    "Both Claude calls are used. Inspect Review; only an explicit new review cycle can grant more."
                )
            for r in rows:
                if (
                    r.get("labels", {}).get("repo-tools.role") == "helper"
                    and r["state"] == "live"
                    and status(r) in ("working", "blocked", None)
                ):
                    fail(
                        "Finish the helper before starting implementation through review"
                    )
        token = uuid.uuid4().hex
        job = dict(
            root=str(root),
            stream=stream,
            key=key,
            role=role,
            action=args.action,
            agent=agent,
            task=args.task or "",
            token=token,
            state="queued",
            updated=time.time(),
            step=0,
        )
        write(runtime / "state.json", job)
        labelspace = next(
            (
                r.get("labels", {}).get("herdr.space")
                for r in rows
                if r.get("labels", {}).get("herdr.space")
            ),
            "stream-" + key + "-" + stream,
        )
        name = "flow-" + key[:8] + "-" + token[:10]
        labels = {
            "herdr.space": labelspace,
            "herdr.tab": labelspace + "-workflow",
            "repo-tools.repo": key,
            "repo-tools.stream": stream,
            "repo-tools.role": "workflow",
            "repo-tools.checkout": str(target or root),
        }
        argv = [
            "hc",
            "run",
            "--bg",
            "--keep",
            "--no-parent",
            "--no-notify",
            "--name",
            name,
            "--cwd",
            str(root),
        ]
        for k, v in labels.items():
            argv += ["--label", k + "=" + v]
        try:
            command(
                argv
                + [
                    "--",
                    sys.executable,
                    str(BIN / "repo-flow.py"),
                    "_worker",
                    str(runtime),
                    token,
                ],
                stdout=sp.DEVNULL,
                timeout=20,
            )
            row = hc("get", name)
            # Worker may already have updated its state; do not overwrite it.
            # The worker alone updates its state after launch.
        except Exception:
            # Never replay a possibly-delivered launch.
            raise
        print(
            json.dumps(
                {
                    "state": "queued",
                    "terminal": row["address"],
                    "stream": stream,
                    "message": "Follow the Workflow tab.",
                }
            )
        )


def worker(runtime, token):
    with H.locked(runtime / "worker.lock", "Another workflow is active"):
        job = read(runtime / "state.json")
        if job["token"] != token:
            fail("workflow token changed before startup")
        job["terminal"] = os.environ.get("HC_TERMINAL_ID")
        try:
            perform(runtime, job)
        except (RuntimeError, OSError, ValueError, sp.SubprocessError) as e:
            phase(runtime, job, "needs-you", str(e))
    if job.get("state") in ("ready", "verified"):
        print(
            "Workflow complete. Continue in the agent conversation or Review.",
            flush=True,
        )
        return
    print("\nWorkflow stopped. Agents and this pane remain available.", flush=True)
    if sys.stdin.isatty():
        os.execv("/bin/zsh", ["zsh", "-l"])


def helper(args):
    root, stream, runtime, key = context(args.stream)
    target = A.checkout(root, stream)
    packet = C.prepare(args, target, stream)
    if packet:
        args.scope = packet["scope"]
    if not args.scope or not args.scope.strip():
        fail("Give the helper a focused task/scope")
    if getattr(args, "preview", False):
        if not packet:
            fail("--preview requires a pane preset")
        print(json.dumps(packet, ensure_ascii=False))
        return
    if args.agent not in (None, "codex", "cursor"):
        fail("Helpers use Codex or Cursor; Claude is reserved for review")
    with H.locked(runtime / "helper.lock", "Another helper is launching"):
        job = read(runtime / "state.json", {})
        if job.get("state") in ACTIVE:
            fail(
                "Wait for the current implementation/review workflow before adding a helper"
            )
        _, rows = details(root, stream, key)
        lead = primary(rows, args.role)
        if not lead:
            fail("Open the " + args.role + " lead before adding a helper")
        expected_parent = packet["evidence"].get("parent") if packet else None
        if expected_parent and expected_parent != lead["address"]:
            fail(
                "The pane lead changed. Reopen Ask a helper from the intended conversation."
            )
        helpers = [
            r
            for r in rows
            if r["state"] == "live"
            and r.get("labels", {}).get("repo-tools.role") == "helper"
        ]
        if helpers:
            fail(
                "One helper is already open. Read/close its pane before starting another."
            )
        name = args.agent or "codex"
        A.executable(name)  # Fail before creating helper state if the CLI is missing.
        token = uuid.uuid4().hex[:10]
        base = A.git(target, "rev-parse", "HEAD")
        helper_root = target
        if args.kind == "code":
            if A.git(target, "status", "--porcelain"):
                fail(
                    "Commit the lead checkout first. A coding helper starts from a clean recorded checkpoint; nothing was stashed or committed automatically."
                )
            main = Path(H.trees(A, root)[0]["worktree"])
            helper_root = Path(str(main) + "-worktrees") / (stream + "-helper-" + token)
            branch = "codex/" + stream + "-helper-" + token
            command(
                [
                    "git",
                    "-C",
                    target,
                    "worktree",
                    "add",
                    "-b",
                    branch,
                    helper_root,
                    base,
                ]
            )
            command(
                [sys.executable, BIN / "repo-transfer.py", "init", helper_root],
                cwd=helper_root,
            )
        else:
            branch = A.git(target, "symbolic-ref", "--short", "HEAD")
        space = lead["labels"]["herdr.space"]
        address = lead["address"]
        text = f"""You are a scoped {'read-only investigator' if args.kind=='research' else 'coding helper in an isolated worktree'} for {args.role.upper()} / {stream}.
Task: {args.scope}
Parent terminal: {address}. Parent checkout: {target}. Recorded base commit: {base}.
Read applicable repository instructions and docs/handoffs/{stream}/ context and acceptance. Preserve existing work. Do not spawn agents, call Claude, run review, deploy, push, merge, switch branches or create another worktree. Do not use the main Work/Studio launcher or take its ownership lock.
{'Do not modify any files. Report findings and evidence in this conversation.' if args.kind=='research' else 'Edit only the assigned scope in this child checkout. Run relevant checks. Do not change the parent checkout. Leave changes for the lead to inspect; report the child branch, file list, tests, limitations, and whether changes are committed. Use isolated test resources; do not start or reuse the parent Docker stack.'}
The lead/user will collect your report in this helper tab. Do not send input to a busy agent. Stop when done and remain available for follow-up. Your completion is not final feature verification.
"""
        text += C.instructions(packet)
        promptfile = runtime / ("helper-" + token + ".json")
        write(
            promptfile,
            dict(
                agent=name,
                root=str(helper_root),
                prompt=text,
                kind=args.kind,
                parent=address,
                base=base,
                branch=branch,
                pane_context=packet,
            ),
        )
        labels = {
            "herdr.space": space,
            "herdr.tab": space + "-helper-" + token,
            "repo-tools.repo": key,
            "repo-tools.stream": stream,
            "repo-tools.role": "helper",
            "repo-tools.checkout": str(helper_root),
            "repo-tools.parent-checkout": str(target),
            "repo-tools.agent": name,
        }
        if packet:
            labels["repo-tools.helper-preset"] = packet["preset"]
            labels["repo-tools.helper-source"] = packet["evidence"]["pane"]
        argv = [
            "hc",
            "run",
            "--bg",
            "--keep",
            "--parent",
            address,
            "--outlive-parent",
            "--no-notify",
            "--name",
            "helper-" + key[:8] + "-" + token,
            "--cwd",
            str(helper_root),
        ]
        for k, v in labels.items():
            argv += ["--label", k + "=" + v]
        command(
            argv
            + [
                "--",
                sys.executable,
                str(BIN / "repo-flow.py"),
                "_helper",
                str(promptfile),
            ],
            timeout=20,
        )
        print(
            "Helper opened in this stream. Its own conversation contains its report. Coding helpers must be integrated and tested by the lead before review."
        )


def helper_pane(path):
    job = read(path)
    binary = A.executable(job["agent"])
    root = Path(job["root"])
    if job["agent"] == "codex":
        argv = [
            binary,
            "--no-daemon",
            "--cd",
            str(root),
            "--sandbox",
            "read-only" if job["kind"] == "research" else "workspace-write",
        ]
        if job["kind"] == "research":
            argv += ["--ask-for-approval", "never"]
    else:
        argv = [binary, "--workspace", str(root), "--sandbox", "enabled"]
        if job["kind"] == "research":
            argv += ["--mode", "ask"]
    try:
        sp.run(argv + [job["prompt"]], cwd=root)
    except KeyboardInterrupt:
        pass
    print(
        "\nHelper exited. This shell stays in its checkout; no work was merged.",
        flush=True,
    )
    os.chdir(root)
    os.execv("/bin/zsh", ["zsh", "-l"])


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "_worker":
        return worker(Path(argv[1]), argv[2])
    if argv and argv[0] == "_helper":
        return helper_pane(Path(argv[1]))
    role = argv.pop(0) if argv and argv[0] in ("studio", "work") else "work"
    p = argparse.ArgumentParser(
        prog=role + " flow",
        description="Shared Herdr desktop/TUI workflow. Omit the subcommand to open the menu. Claude: one final review and one follow-up; no automatic new cycle.",
    )
    p.add_argument(
        "action",
        nargs="?",
        choices=["open", "prepare", "implement", "helper", "status", "pause", "ready"],
    )
    p.add_argument("stream", nargs="?")
    p.add_argument("--role", choices=["studio", "work"], default=role)
    p.add_argument(
        "--retry-token",
        help="Retry exactly this failed opening; reuse its checkout and agent",
    )
    p.add_argument("--agent", choices=["codex", "cursor"])
    p.add_argument("--task")
    p.add_argument("--scope")
    p.add_argument(
        "--preset",
        choices=list(C.PRESETS),
        help="On-demand, read-only pane helper (Codex/Cursor)",
    )
    selected = p.add_mutually_exclusive_group()
    selected.add_argument(
        "--context-json", help="Bounded pane evidence JSON, schema version 1"
    )
    selected.add_argument(
        "--context-file",
        help="UTF-8 JSON with version=1, pane, cwd, stream, source and text; optional parent/captured_at/head/draft/truncated",
    )
    p.add_argument("--period", help="Campaign inclusive dates: YYYY-MM-DD..YYYY-MM-DD")
    p.add_argument(
        "--compare-period", help="Non-overlapping comparison dates of equal length"
    )
    p.add_argument(
        "--preview",
        action="store_true",
        help="Validate/print helper context without launching anything",
    )
    p.add_argument("--kind", choices=["research", "code"], default="research")
    p.add_argument("--token")
    p.add_argument("--step", type=int)
    a = p.parse_args(argv)
    if a.retry_token and a.action != "open":
        p.error("--retry-token is only for open")
    if a.action != "helper" and any(
        (
            a.preset,
            a.context_json,
            a.context_file,
            a.period,
            a.compare_period,
            a.preview,
        )
    ):
        p.error("pane helper options require the helper action")
    if a.action is None:
        return run_menu(role, main)
    if a.action == "ready":
        return ready(a)
    if a.action == "helper":
        return helper(a)
    if a.action in ("status", "pause"):
        root, stream, runtime, key = context(a.stream)
        s = read(
            runtime / "state.json",
            {
                "state": "not-started",
                "stream": stream,
                "message": "No workflow started.",
            },
        )
        if a.action == "status" and s.get("state") == "verified":
            rr = R.resolve(stream)
            review = R.snapshot_status(rr[0], stream, rr[2])
            if review["state"] != "verified":
                s = dict(
                    s,
                    state="stale",
                    message="Files or review evidence changed. Open Review; this workflow no longer verifies the current version.",
                )
        if a.action == "pause" and s.get("token"):
            (runtime / ("pause-" + s["token"])).touch()
            # Pause is a request; worker relinquishes ownership before another run may launch.
            try:
                with H.locked(
                    runtime / "worker.lock", "Controller is finishing its pause"
                ):
                    s.update(
                        state="needs-you",
                        message="Paused. Inspect existing conversations before restarting.",
                    )
                    write(runtime / "state.json", s)
            except RuntimeError:
                s["message"] = (
                    "Pause requested; waiting for the current bounded operation to return."
                )
        print(json.dumps(O.describe("workflow", s)))
        return
    return launch(a)


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except (RuntimeError, OSError, ValueError, sp.SubprocessError) as e:
        sys.exit("repo-flow: " + str(e))
