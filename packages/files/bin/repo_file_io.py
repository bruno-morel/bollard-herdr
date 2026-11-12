"""Small repository text reader/editor shared by full and standalone panels."""

import hashlib, os, re, stat, subprocess as sp, tempfile
from pathlib import Path


def safe(root, rel):
    if (
        not isinstance(rel, str)
        or not rel
        or "\0" in rel
        or Path(rel).is_absolute()
        or ".." in Path(rel).parts
        or ".git" in Path(rel).parts
    ):
        raise RuntimeError("Expected a repository-relative file path outside .git")
    p = root
    for part in Path(rel).parts:
        p /= part
        if p.is_symlink():
            raise RuntimeError("Refusing symlink: " + rel)
    return p


def root():
    result = sp.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    if result.returncode:
        raise sp.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr
        )
    return Path(result.stdout.strip()).resolve()


def file_data(path):
    r = root()
    p = safe(r, path)
    if not p.is_file() or p.stat().st_size > 100000:
        raise RuntimeError("Native editing supports text files up to 100 KB")
    raw = p.read_bytes()
    if b"\0" in raw:
        raise RuntimeError("Binary file; use a suitable external editor")
    text = raw.decode("utf-8")
    return dict(
        root=str(r), path=path, text=text, digest=hashlib.sha256(raw).hexdigest()
    )


def save(path, digest, text):
    if not re.fullmatch("[0-9a-f]{64}", digest):
        raise RuntimeError("Missing original file revision")
    if "\0" in text or len(text.encode()) > 100000:
        raise RuntimeError("Text exceeds the 100 KB editor limit")
    r = root()
    p = safe(r, path)
    before = file_data(path)
    if before["digest"] != digest:
        raise RuntimeError(
            "File changed on disk. Your edit is retained; compare it before reloading. Nothing was overwritten."
        )
    mode = stat.S_IMODE(p.stat().st_mode)
    fd, tmp = tempfile.mkstemp(prefix="." + p.name + ".edit-", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        if file_data(path)["digest"] != digest:
            raise RuntimeError("File changed while saving. Nothing was overwritten.")
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return file_data(path)
