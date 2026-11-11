import hashlib
import os
from pathlib import Path
import re
import subprocess as sp
import sys


def git(root, *args):
    return sp.check_output(['git', '-C', str(root), *args], text=True,
                           stderr=sp.PIPE, timeout=10).strip()


def setup():
    helper = Path(__file__).with_name('repo-zellij-socket.py')
    if sys.platform == 'darwin' and helper.is_file():
        os.environ['ZELLIJ_SOCKET_DIR'] = sp.check_output(
            [sys.executable, str(helper)], text=True, timeout=10).strip()


def name(role, root):
    root = Path(root).resolve()
    records = git(root, 'worktree', 'list', '--porcelain', '-z')
    primary = records.split('\0', 1)[0].removeprefix('worktree ')
    branch = git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    slug = lambda s, n: re.sub(r'[^a-z0-9.-]+', '-', s.lower()).strip('-')[:n] or 'repo'
    key = hashlib.sha256(os.fsencode(str(root))).hexdigest()[:8]
    return f'{role}-{slug(Path(primary).name, 12)}-{slug(branch.removeprefix("codex/"), 20)}-{key}'


def listing():
    setup()
    p = sp.run(['zellij', 'list-sessions', '--no-formatting'],
               capture_output=True, text=True, timeout=10)
    if p.returncode:
        if any(x in (p.stdout+p.stderr).lower() for x in ('no active sessions', 'no sessions')):
            return {}
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or 'Cannot list sessions')
    return {s.split()[0]: s for s in p.stdout.splitlines() if s.strip()}


def resolve(role, root, legacy=''):
    setup()
    if role == 'studio':
        result = sp.check_output(
            [sys.executable, str(Path(__file__).with_name('studio-session.py')), str(root)],
            text=True, timeout=45
        ).strip()
        return result or name(role, root)
    candidates = {name(role, root)}
    if legacy:
        candidates.add(legacy)
    matches = [s for s, row in listing().items() if s in candidates and 'EXITED' not in row]
    if len(matches) > 1:
        raise RuntimeError('Multiple Work sessions match; resolve duplicates first: ' + ', '.join(matches))
    return matches[0] if matches else name(role, root)


if __name__ == '__main__':
    try:
        mode, role, root, *rest = sys.argv[1:]
        if mode not in ('name', 'resolve') or role not in ('studio', 'work'):
            raise ValueError('usage: repo_sessions.py name|resolve studio|work <checkout> [legacy-name]')
        print(name(role, root) if mode == 'name' else resolve(role, root, *rest))
    except (ValueError, RuntimeError, OSError, sp.SubprocessError) as exc:
        sys.exit('repo-sessions: ' + str(exc))
