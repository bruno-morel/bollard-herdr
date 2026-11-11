"""Atomic JSON replacement; callers own validation, directories and locking."""
import json
import os
from pathlib import Path
import tempfile


def write_json(path, data, *, indent=None):
    """Replace one file privately, leaving the previous value intact on failure.

    The temporary file lives beside the destination so rename stays atomic.
    This does not serialize read/modify/write operations: hold the caller's lock.
    """
    path = Path(path)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name + '-')
    pending = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, indent=indent)
            handle.write('\n')
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)
