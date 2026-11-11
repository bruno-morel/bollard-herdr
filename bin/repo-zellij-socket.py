#!/usr/bin/env python3
import os
from pathlib import Path
import sys

try:
    uid = os.getuid()
    target = Path(
        os.environ.get('ZELLIJ_SOCKET_DIR')
        or str(Path(os.environ.get('TMPDIR') or '/tmp') / f'zellij-{uid}')
    ).resolve()
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not target.is_dir() or target.stat().st_uid != uid:
        raise RuntimeError('socket directory is not owned by this user')

    short = Path('/tmp') / f'repo-zj-{uid}'
    if short.is_symlink():
        raise RuntimeError('socket parent must not be a symlink')
    short.mkdir(mode=0o700, exist_ok=True)
    if short.stat().st_uid != uid or short.stat().st_mode & 0o077:
        raise RuntimeError('socket parent must be private and owned by this user')

    alias = short / 's'
    if alias.is_symlink():
        if alias.resolve() != target:
            raise RuntimeError('socket alias points elsewhere: ' + str(alias))
    elif alias.exists():
        raise RuntimeError('socket alias is occupied: ' + str(alias))
    else:
        alias.symlink_to(target, target_is_directory=True)
    print(alias)
except (OSError, RuntimeError) as exc:
    sys.exit('repo-tools: ' + str(exc))
