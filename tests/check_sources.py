#!/usr/bin/env python3
"""Check publishable sources, excluding local caches and generated SDK files."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess as sp
import sys

PRIVATE = (
    rb"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----",
    rb"gh[pousr]_[A-Za-z0-9]{30,}",
    rb"sk-(?:ant-)?[A-Za-z0-9_-]{35,}",
    rb'/Users/[a-zA-Z][^/\s"\']*/',
    rb"192\.168\.\d+\.\d+",
)


def sources(root):
    """Include tracked files and new candidates; Git owns the ignore rules."""
    result = sp.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=True,
        capture_output=True,
    )
    for name in sorted(set(result.stdout.split(b"\0"))):
        if not name:
            continue
        path = root / os.fsdecode(name)
        if path.is_symlink():
            raise ValueError("Source symlink is not publishable: " + str(path))
        if path.is_file():
            yield path


def check(path):
    if path.suffix == ".png":
        return  # Gallery preview is visually inspected before publication.
    data = path.read_bytes()
    if b"\0" in data or any(re.search(pattern, data) for pattern in PRIVATE):
        raise ValueError("Unexpected binary/private configuration: " + str(path))
    first = data.split(b"\n", 1)[0]
    if path.suffix == ".py" or (first.startswith(b"#!") and b"python" in first):
        compile(data, str(path), "exec")
    elif path.suffix == ".zsh" or (first.startswith(b"#!") and b"sh" in first):
        shell = "zsh" if path.suffix == ".zsh" or b"zsh" in first else "sh"
        if not shutil.which(shell):
            raise ValueError("Install " + shell + " to validate shell sources")
        sp.run([shell, "-n", str(path)], check=True)
    elif path.suffix == ".json":
        json.loads(data)


def main():
    root = Path(__file__).resolve().parents[1]
    sp.run([sys.executable, str(root / "desktop_build.py"), "--check"], check=True)
    sp.run([sys.executable, str(root / "standalone_build.py"), "--check"], check=True)
    paths = list(sources(root))
    for path in paths:
        check(path)
    print(
        "Validated",
        len(paths),
        "publishable files (syntax and private-configuration scan).",
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, SyntaxError, sp.CalledProcessError) as exc:
        sys.exit(str(exc))
