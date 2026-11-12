#!/usr/bin/env python3
"""Standalone panel backend: text files and an existing repository Compose project.
No agents, worktrees, review calls, background daemons or workflow state.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess as sp
import sys
import time
from repo_file_io import root, file_data, save


def compose_root():
    here = Path.cwd().resolve()
    try:
        return root()
    except sp.CalledProcessError:
        return here


def compose_args(directory):
    # Explicit project directory prevents accidental discovery in parent folders.
    names = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")
    base = next(
        (directory / name for name in names if (directory / name).is_file()), None
    )
    if base is None:
        return None
    args = ["docker", "compose", "--project-directory", str(directory), "-f", str(base)]
    overrides = (
        ("compose.override.yaml", "compose.override.yml")
        if base.name.startswith("compose.")
        else ("docker-compose.override.yml", "docker-compose.override.yaml")
    )
    override = next(
        (directory / name for name in overrides if (directory / name).is_file()), None
    )
    if override:
        args += ["-f", str(override)]
    return args


def execute(args, directory, timeout=30):
    env = dict(os.environ)
    # An agent shell may carry another stream's Compose identity. Never inherit it.
    for key in ("COMPOSE_FILE", "COMPOSE_PROJECT_NAME", "COMPOSE_ENV_FILES"):
        env.pop(key, None)
    result = sp.run(
        args, cwd=directory, env=env, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Docker Compose command failed")
    return result.stdout


def rows(output):
    if not output.strip():
        return []
    try:
        value = json.loads(output)
        return value if isinstance(value, list) else [value]
    except json.JSONDecodeError:
        return [json.loads(line) for line in output.splitlines() if line.strip()]


def docker(action):
    directory = compose_root()
    args = compose_args(directory)
    if action == "docker-startup":
        return {"state": "idle"}
    if args is None:
        if action == "docker-start":
            raise RuntimeError(
                "Add a compose.yaml or docker-compose.yml in this repository first. This panel does not generate a stack."
            )
        return {
            "state": "unprepared",
            "services": [],
            "logs": "",
            "heartbeat": time.time(),
        }
    if action == "docker-start":
        output = execute(args + ["up", "-d"], directory, timeout=120)
        return {
            "state": "succeeded",
            "output": output[-100000:] or "Compose services started.",
        }
    if action == "docker-logs":
        output = execute(args + ["logs", "--no-color", "--tail", "400"], directory)
        return {"state": "active", "logs": output[-200000:], "heartbeat": time.time()}
    services = rows(execute(args + ["ps", "--all", "--format", "json"], directory))
    project = next((row.get("Project") for row in services if row.get("Project")), "")
    active = any(
        row.get("State") in ("running", "restarting", "paused") for row in services
    )
    return {
        "state": "active" if active else "stopped" if services else "empty",
        "services": services,
        "project": project,
        "observed_at": time.time(),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "action",
        choices=(
            "read",
            "save",
            "docker-status",
            "docker-logs",
            "docker-start",
            "docker-startup",
        ),
    )
    p.add_argument("path", nargs="?")
    p.add_argument("--digest")
    p.add_argument("--text")
    a = p.parse_args()
    if a.action == "read":
        value = file_data(a.path)
    elif a.action == "save":
        if a.digest is None or a.text is None:
            p.error("save requires --digest and --text")
        value = save(a.path, a.digest, a.text)
    else:
        value = docker(a.action)
    print(json.dumps(value))


if __name__ == "__main__":
    try:
        main()
    except sp.TimeoutExpired:
        sys.exit(
            "bollard-panel: command timed out; inspect Compose before retrying startup"
        )
    except (RuntimeError, OSError, ValueError, sp.CalledProcessError) as exc:
        sys.exit("bollard-panel: " + str(exc))
