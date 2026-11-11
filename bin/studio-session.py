#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess as sp
import sys
from repo_sessions import name as readable_name


def session_for(path):
    return 'studio-' + hashlib.sha256(os.fsencode(path)).hexdigest()[:16]


def find(target):
    if not target.is_dir():
        raise RuntimeError('checkout is unavailable: ' + str(target))
    result = sp.run(
        ['zellij', 'list-sessions', '--no-formatting'],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode:
        message = (result.stdout + result.stderr).strip()
        if not message or any(
            phrase in message.lower() for phrase in ('no active', 'no sessions')
        ):
            return ''
        raise RuntimeError(message)

    live = [
        line.split()[0] for line in result.stdout.splitlines()
        if line.startswith('studio-') and 'EXITED' not in line
    ]
    expected = session_for(str(target))
    matches = [s for s in live if s in (expected, readable_name('studio', target))]
    if len(matches) > 1:
        raise RuntimeError('Multiple Studio sessions match this checkout: ' + ', '.join(matches))
    if matches:
        return matches[0]

    matches, unavailable = [], []
    for name in live:
        try:
            result = sp.run(
                ['zellij', '--session', name, 'action', 'dump-layout'],
                capture_output=True, text=True, timeout=5
            )
        except sp.TimeoutExpired:
            unavailable.append(name)
            continue
        if result.returncode:
            unavailable.append(name)
            continue

        for quoted in re.findall(
            r'\bcwd(?:\s*=\s*|\s+)("(?:[^"\\]|\\.)*")', result.stdout
        ):
            try:
                cwd = Path(json.loads(quoted))
            except ValueError:
                continue
            if not cwd.is_absolute():
                continue
            for candidate in (cwd, *cwd.parents):
                if session_for(str(candidate)) != name:
                    continue
                try:
                    if os.path.samefile(candidate, target):
                        matches.append(name)
                except OSError:
                    pass

    matches = sorted(set(matches))
    if len(matches) > 1:
        raise RuntimeError(
            'multiple Studio sessions match this checkout: ' + ', '.join(matches)
        )
    if matches:
        return matches[0]
    if unavailable:
        raise RuntimeError(
            'could not inspect these Studio sessions: ' + ', '.join(unavailable)
        )
    return ''


if __name__ == '__main__':
    try:
        print(find(Path(sys.argv[1])))
    except (RuntimeError, OSError, IndexError, sp.SubprocessError) as exc:
        sys.exit('studio: ' + str(exc))
