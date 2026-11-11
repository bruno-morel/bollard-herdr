#!/usr/bin/env python3
"""Start only a stream's Docker stack in a durable, background Herdr terminal."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess as sp
import sys

BIN = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("docker_observe", BIN / "repo-observe.py")
O = importlib.util.module_from_spec(spec)
spec.loader.exec_module(O)


def hc(*args):
    result = sp.run(["hc", "--json", *args], capture_output=True, text=True, timeout=12)
    if result.returncode:
        raise RuntimeError(
            (result.stderr or result.stdout).strip()[-1800:] or "Herdr command failed"
        )
    return json.loads(result.stdout)


def context(stream=None):
    root = Path(O.run(["git", "rev-parse", "--show-toplevel"], ".").strip())
    branch = O.run(["git", "symbolic-ref", "--quiet", "--short", "HEAD"], root).strip()
    stream = stream or (branch[6:] if branch.startswith("codex/") else "")
    if (
        not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", stream)
        or branch != "codex/" + stream
    ):
        raise RuntimeError(
            "Select the matching stream checkout before starting Docker."
        )
    # Work verifies the saved checkout, branch, handoff identity and repository.
    values = json.loads(O.run([str(BIN / "work"), "_herdr-env", stream], root))
    project = values.get("COMPOSE_PROJECT_NAME")
    if not project:
        raise RuntimeError(
            "This stream has no saved Docker project. Prepare it with work prepare first."
        )
    return {
        "root": str(root),
        "stream": stream,
        "project": project,
        "name": "docker-" + hashlib.sha256(project.encode()).hexdigest()[:24],
    }


def belongs(row, ctx):
    labels = row.get("labels") or {}
    return (
        labels.get("repo-tools.role") == "docker-start"
        and labels.get("repo-docker.project") == ctx["project"]
        and labels.get("repo-tools.stream") == ctx["stream"]
        and Path(labels.get("repo-tools.checkout") or "/").resolve()
        == Path(ctx["root"]).resolve()
        and Path(row.get("cwd") or "/").resolve() == Path(ctx["root"]).resolve()
    )


def latest(ctx):
    matches = [
        r
        for r in hc("ls", "--all").get("terminals", [])
        if r.get("name") == ctx["name"] and "/" not in r["address"]
    ]
    matches.sort(
        key=lambda r: (r.get("state") == "live", r.get("created_ms", 0)), reverse=True
    )
    for row in matches:
        detail = hc("get", row["address"])
        if not belongs(detail, ctx):
            if detail.get("state") == "live":
                raise RuntimeError(
                    "A different command owns this Docker startup name; no command was sent."
                )
            continue
        return detail
    return None


def snapshot(ctx, row=None):
    if row is None:
        return {
            "state": "idle",
            "stream": ctx["stream"],
            "project": ctx["project"],
            "output": "",
        }
    state = (
        "running"
        if row["state"] == "live"
        else (
            "succeeded"
            if type(row.get("exit_code")) is int and row["exit_code"] == 0
            else "failed"
        )
    )
    # get.screen describes capture fidelity; read.text is the actual output.
    try:
        text = hc("read", row["address"], "--lines", "80").get("text", "")
    except (RuntimeError, OSError, ValueError, sp.SubprocessError):
        text = "Startup output is temporarily unavailable. Refresh to retry."
    output = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)[-16000:]
    return {
        "state": state,
        "stream": ctx["stream"],
        "project": ctx["project"],
        "terminal": row["address"],
        "exit_code": row.get("exit_code"),
        "finished_ms": row.get("finished_ms"),
        "output": output,
    }


def start(ctx):
    old = latest(ctx)
    if old and old["state"] == "live":
        return snapshot(ctx, old)
    argv = [
        "run",
        "--bg",
        "--no-parent",
        "--no-notify",
        "--name",
        ctx["name"],
        "--cwd",
        ctx["root"],
    ]
    for name, value in {
        "repo-tools.role": "docker-start",
        "repo-tools.stream": ctx["stream"],
        "repo-tools.checkout": ctx["root"],
        "repo-docker.project": ctx["project"],
    }.items():
        argv += ["--label", name + "=" + value]
    # No --keep or herdr.space/tab: an operation, not another shell or agent pane.
    try:
        row = hc(*argv, "--", str(BIN / "work"), "_herdr-start", ctx["stream"])
    except (RuntimeError, sp.TimeoutExpired):
        # A second window can win the name, or launch can time out after delivery.
        # Adopt that exact operation; never blindly replay the start command.
        found = latest(ctx)
        if found and (not old or found["address"] != old["address"]):
            return snapshot(ctx, found)
        raise
    detail = hc("get", row["address"])
    if not belongs(detail, ctx):
        raise RuntimeError(
            "Docker launch identity could not be verified. Inspect hc ls --all before retrying."
        )
    return snapshot(ctx, detail)


def main():
    parser = argparse.ArgumentParser(
        prog="work docker",
        description="Start the selected stream’s existing Docker stack without opening another agent or pane.",
    )
    parser.add_argument("action", choices=("start", "status"))
    parser.add_argument("stream", nargs="?")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    ctx = context(args.stream)
    result = start(ctx) if args.action == "start" else snapshot(ctx, latest(ctx))
    print(
        json.dumps(result)
        if args.json
        else f"{ctx['stream']}: Docker startup {result['state']}"
        + ("\n" + result["output"] if result["output"] else "")
    )


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except (RuntimeError, OSError, ValueError, sp.SubprocessError) as exc:
        sys.exit("work docker: " + str(exc))
