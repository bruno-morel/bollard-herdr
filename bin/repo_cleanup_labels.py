import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess as sp
from repo_sessions import name as readable_name


def git(path, *args):
    try:
        p = sp.run(
            ['git', '-C', str(path), *args],
            capture_output=True, text=True, timeout=4
        )
        return p.stdout.strip() if p.returncode == 0 else ''
    except (OSError, sp.SubprocessError):
        return ''


def label(path, stream):
    listing = git(path, 'worktree', 'list', '--porcelain')
    first = listing.splitlines()[0] if listing else ''
    repo = Path(first[9:]).name if first.startswith('worktree ') else '?'
    return f'{repo} / {stream}  [{path}]'


def identities():
    found = {}
    roots = {str(Path.cwd())}
    runtime = Path(os.environ.get(
        'XDG_STATE_HOME', str(Path.home()/'.local/state')
    )) / 'repo-tools'

    for record in (runtime/'work').glob('*/*/state.env'):
        try:
            values = {}
            for line in record.read_text().splitlines():
                key, sep, value = line.partition('=')
                if sep and key in (
                    'WORKTREE_PATH', 'SESSION', 'SLUG', 'ENV_SOURCE_ROOT'
                ):
                    words = shlex.split(value, comments=False)
                    if len(words) == 1:
                        values[key] = words[0]

            path = values.get('WORKTREE_PATH')
            if not path:
                continue
            roots.add(path)
            if values.get('ENV_SOURCE_ROOT'):
                roots.add(values['ENV_SOURCE_ROOT'])

            stream = values.get('SLUG', record.parent.name)
            display = label(path, stream)
            if values.get('SESSION'):
                found[values['SESSION']] = display
            found['work-' + record.parent.parent.name + '-' + stream] = display
        except (OSError, ValueError):
            continue

    seen = set()
    for root in roots:
        records = git(root, 'worktree', 'list', '--porcelain', '-z')
        if not records or records in seen:
            continue
        seen.add(records)
        for record in records.split('\0\0'):
            fields = dict(
                x.split(' ', 1) for x in record.split('\0') if ' ' in x
            )
            path = fields.get('worktree')
            branch = fields.get('branch', '').removeprefix('refs/heads/')
            if not path or not branch:
                continue
            stream = branch.removeprefix('codex/')
            for role in ('studio', 'work'):
                try:
                    found[readable_name(role, path)] = label(path, stream)
                except (OSError, RuntimeError, sp.SubprocessError):
                    pass
            for spelling in {path, str(Path(path).resolve())}:
                key = hashlib.sha256(os.fsencode(spelling)).hexdigest()[:16]
                found['studio-' + key] = label(path, stream)
    return found


_cache = None


def describe_session(name, description):
    global _cache
    if _cache is None:
        _cache = identities()
    identity = _cache.get(name)

    if not identity and 'EXITED' not in description:
        try:
            p = sp.run(
                ['zellij', '--session', name, 'action', 'dump-layout'],
                capture_output=True, text=True, timeout=4
            )
            candidates = set()
            for raw in re.findall(
                r'\bcwd\s*(?:=\s*)?("(?:[^"\\]|\\.)*")', p.stdout
            ):
                path = json.loads(raw)
                root = git(path, 'rev-parse', '--show-toplevel')
                branch = git(
                    path, 'symbolic-ref', '--quiet', '--short', 'HEAD'
                )
                if root and branch:
                    candidates.add(label(root, branch.removeprefix('codex/')))
            if len(candidates) == 1:
                identity = candidates.pop()
        except (OSError, ValueError, sp.SubprocessError):
            pass

    if identity:
        suffix = description[len(name):] if description.startswith(name) else ''
        return identity + suffix
    return 'Unidentified repository/stream — ' + description
