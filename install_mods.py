#!/usr/bin/env python3
"""Install optional standalone mods without changing layouts, keys, agents or pins."""
import argparse
import json
import os
from pathlib import Path
from install import atomic_write, digest
from standalone_build import build

ROOT = Path(__file__).resolve().parent


def targets(selection, home, host_only=False):
    files = {}
    kinds = ("files", "docker") if selection == "all" else (selection,)
    for kind in kinds:
        package = ROOT / "packages" / kind
        for source in sorted(package.rglob("*")):
            if not source.is_file():
                continue
            rel = source.relative_to(package)
            if (
                source.name == "jsconfig.json"
                or source.name.endswith(".d.ts")
                or "__pycache__" in rel.parts
            ):
                continue
            if rel.parts[0] == "bin":
                dest = home / ".local/bin" / rel.name
            elif rel.parts[0] == "mods" and not host_only:
                dest = home / ".config/herdr-app" / rel
            else:
                continue
            if dest in files and files[dest].read_bytes() != source.read_bytes():
                raise ValueError("Conflicting packaged dependency: " + str(dest))
            files[dest] = source
    return [(source, dest) for dest, source in files.items()]


def install(selection, home, apply=False, verify=False, host_only=False):
    home = Path(home).resolve()
    build(check=True)
    state = (
        Path(os.environ.get("XDG_STATE_HOME", str(home / ".local/state")))
        / "bollard-mods/install.json"
    )
    previous = json.loads(state.read_text()) if state.exists() else {}
    entries = []
    for source, dest in targets(selection, home, host_only):
        if any(p.is_symlink() for p in (dest, *dest.parents)):
            raise ValueError("Refusing symlink destination: " + str(dest))
        data = source.read_bytes()
        old = dest.read_bytes() if dest.exists() else None
        if verify and old != data:
            raise ValueError("Installed copy differs: " + str(dest))
        if old is not None and old != data and digest(old) != previous.get(str(dest)):
            raise ValueError(
                "Edited outside the mod installer; reconcile first: " + str(dest)
            )
        mode = 0o755 if data.startswith(b"#!") else 0o644
        entries.append((dest, data, old, mode))
    if verify:
        print("Verified", len(entries), "standalone files.")
        return
    changes = [e for e in entries if e[1] != e[2]]
    print(
        "Installing" if apply else "Would update",
        len(changes),
        "standalone files; layouts and conversations stay unchanged.",
    )
    if not apply:
        for dest, *_ in changes:
            print(dest)
        return
    # Validate the whole plan first; roll back this installer if a write fails.
    applied = []
    try:
        for dest, data, old, mode in changes:
            old_mode = dest.stat().st_mode & 0o777 if dest.exists() else mode
            atomic_write(dest, data, mode)
            applied.append((dest, old, old_mode))
        record = {
            **previous,
            **{str(dest): digest(data) for dest, data, _, _ in entries},
        }
        atomic_write(state, (json.dumps(record, indent=2) + "\n").encode(), 0o600)
    except Exception:
        for dest, old, mode in reversed(applied):
            if old is None:
                dest.unlink(missing_ok=True)
            else:
                atomic_write(dest, old, mode)
        raise
    for dest, data, _, _ in entries:
        if dest.read_bytes() != data:
            raise ValueError("Post-install verification failed: " + str(dest))
    print(
        "Installed and verified",
        len(entries),
        "files. Open the mod explicitly when ready.",
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("selection", choices=("files", "docker", "all"))
    p.add_argument(
        "--host-only",
        action="store_true",
        help="Install only two small Python helpers on a remote agent host",
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true")
    group.add_argument("--verify", action="store_true")
    a = p.parse_args()
    try:
        install(a.selection, Path.home(), a.apply, a.verify, a.host_only)
    except (OSError, ValueError) as e:
        p.error(str(e))
