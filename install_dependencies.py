"""Read-only prerequisite checks; never install software or start services."""

import os
from pathlib import Path
import shutil
import subprocess
import sys


def inspect(profile):
    desktop = profile in ("desktop", "all", "laptop")
    tui = profile != "desktop"
    search = os.environ.get("PATH", "")
    fallback = os.pathsep.join(
        [search, str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin"]
    )
    rows = []

    def command(name, hint, required=True):
        path = shutil.which(name, path=search)
        found = path or shutil.which(name, path=fallback)
        ok = bool(path)
        detail = path or (
            "Installed at " + found + "; add its directory to PATH." if found else hint
        )
        rows.append((name, ok, required, detail))
        return found

    rows.append(
        (
            "Python 3.9+",
            sys.version_info >= (3, 9),
            True,
            (
                sys.version.split()[0]
                if sys.version_info >= (3, 9)
                else "Install Python 3.9+: brew install python"
            ),
        )
    )
    command(
        "git", "macOS: brew install git; Linux: install git with your package manager."
    )
    command(
        "zsh", "macOS: brew install zsh; Linux: install zsh with your package manager."
    )
    command("ssh", "Install the OpenSSH client with your system package manager.")
    command(
        "hc",
        "Install herdr-core: curl -fsSL https://releases.herdr.dev/core/install.sh | sh",
    )
    if desktop:
        command(
            "herdr-app",
            "Apple Silicon macOS: brew install --cask herdr-app, then open -a Herdr. Other platforms: https://herdr.dev/download/",
        )
    if tui:
        command(
            "herdr",
            "macOS: brew install herdr; other platforms: https://herdr.dev/tui/docs/install/",
        )
        command(
            "glow",
            "macOS: brew install glow; other platforms: https://github.com/charmbracelet/glow#installation",
        )
    agents = [
        name
        for name in ("codex", "claude", "cursor-agent", "agent")
        if shutil.which(name, path=search)
    ]
    rows.append(
        (
            "Agent CLI (on the agent host)",
            bool(agents),
            False,
            (
                ", ".join(agents)
                if agents
                else "Install and sign in to at least one provider on the agent host; see docs/agents.md. Not needed on a viewing-only laptop."
            ),
        )
    )
    docker = command(
        "docker",
        "Optional for Work stacks: install Docker + Compose on the development host; https://docs.docker.com/get-started/get-docker/",
        False,
    )
    if docker:
        try:
            result = subprocess.run(
                [docker, "compose", "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            ok = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        rows.append(
            (
                "Docker Compose",
                ok,
                False,
                (
                    "Available"
                    if ok
                    else "Install the Docker Compose v2 plugin on the development host."
                ),
            )
        )
    return rows


def check(profile):
    rows = inspect(profile)
    print("\nPrerequisites for " + profile + " (this machine):")
    for name, ok, required, detail in rows:
        mark = "OK" if ok else "MISSING" if required else "OPTIONAL"
        print("  [" + mark + "] " + name + " — " + detail)
    missing = [name for name, ok, required, _ in rows if required and not ok]
    if missing:
        print("\nInstall the missing prerequisites, then rerun the same command.")
        print('For ~/.local/bin tools: export PATH="$HOME/.local/bin:$PATH"')
        print(
            "Keep that entry in ~/.zshrc. Check Homebrew PATH with brew shellenv if needed."
        )
    print(
        "No software was installed, no login attempted, and no Docker daemon or agent started."
    )
    print(
        "Complete walkthrough: docs/setup.md (desktop, terminal, hc and remote hosts).\n"
    )
    return not missing
