#!/usr/bin/env python3
"""Install maintained sources; reject unreviewed drift and verify every window copy.

Usage: python3 install.py laptop|jumpbox [--apply | --verify]
Without either flag, validate and print the installation plan only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

SOURCE = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".repo-tools-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def targets(profile, home):
    for source in sorted((SOURCE / "bin").rglob("*")):
        if source.is_file():
            yield source, home / ".local/bin" / source.relative_to(SOURCE / "bin")
    for source in sorted((SOURCE / "zellij/layouts").glob("*.kdl")):
        yield source, home / ".config/zellij/layouts" / source.name
    yield SOURCE / "tui/studio-work-v2.toml", home / ".config/herdr/studio-work-v2.toml"
    if profile != "laptop":
        return
    app = home / ".config/herdr-app"
    for base in [app, *sorted(p for p in (app / "screens").glob("*") if p.is_dir() and not p.is_symlink())]:
        for folder in ("mods", "helpers"):
            for source in sorted((SOURCE / "herdr" / folder).rglob("*")):
                if source.is_file() and source.suffix in (".js", ".json", ".svg", ".py") and source.name != "jsconfig.json":
                    yield source, base / folder / source.relative_to(SOURCE / "herdr" / folder)
    # Layouts contain personal pins and terminal IDs after use. Seed once only.
    for source in sorted((SOURCE / "herdr/layouts").glob("*.json")):
        destination = app / "layouts" / source.name
        if not destination.exists():
            yield source, destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=["laptop", "jumpbox"])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    home = Path.home()
    manifest = Path(os.environ.get("XDG_STATE_HOME", str(home / ".local/state"))) / "repo-tools/source-install.json"
    baseline = json.loads((SOURCE / "baseline.json").read_text())
    previous = json.loads(manifest.read_text()) if manifest.exists() else {}
    plan = []
    for source, destination in targets(args.profile, home):
        if destination.is_symlink():
            raise SystemExit("Refusing to replace symlink: " + str(destination))
        data = source.read_bytes()
        if source.suffix == ".toml":
            data = data.replace(b"@HOME@", str(home).encode())
        if source.suffix == ".py" or source.name == "repo-workflow":
            compile(data, str(source), "exec")
        old = destination.read_bytes() if destination.exists() else None
        changed = old != data
        if args.verify and changed:
            raise SystemExit("Installed copy differs: " + str(destination))
        expected = {
            baseline.get(str(source.relative_to(SOURCE))),
            previous.get(str(destination)),
        }
        if changed and old is not None and digest(old) not in expected:
            raise SystemExit(
                "Edited outside maintained sources; reconcile first: "
                + str(destination)
            )
        mode = (
            destination.stat().st_mode & 0o777
            if destination.exists()
            else 0o755 if data.startswith(b"#!") else 0o644
        )
        plan.append((destination, data, old, mode))
    if args.verify:
        print(
            "Verified", len(plan), "installed files; all managed window copies match."
        )
        return
    changes = [entry for entry in plan if entry[1] != entry[2]]
    print(("Installing" if args.apply else "Would update"), len(changes), "files.")
    if not args.apply:
        for destination, *_ in changes:
            print(destination)
        return
    applied = []
    try:
        # Install shared Python/JS dependencies before their callers.
        changes.sort(
            key=lambda entry: entry[0].name
            not in ("repo_operations.py", "operations.js")
        )
        for destination, data, old, mode in changes:
            atomic_write(destination, data, mode)
            applied.append((destination, old, mode))
        record = {**previous, **{str(destination): digest(data) for destination, data, _, _ in plan}}
        atomic_write(manifest, (json.dumps(record, indent=2) + "\n").encode(), 0o600)
    except Exception:
        for destination, old, mode in reversed(applied):
            if old is None:
                destination.unlink(missing_ok=True)
            else:
                atomic_write(destination, old, mode)
        raise
    for destination, data, _, _ in plan:
        if destination.read_bytes() != data:
            raise SystemExit("Post-install verification failed: " + str(destination))
    print(
        "Installed and verified", len(plan), "files. Running agents were not restarted."
    )


if __name__ == "__main__":
    main()
