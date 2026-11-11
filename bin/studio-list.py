#!/usr/bin/env python3
from pathlib import Path
import hashlib, os, re, signal, subprocess as sp

def git(*args):
    return sp.check_output(
        ['git', *args], stderr=sp.DEVNULL, text=True
    ).strip()

try:
    root = Path(git('rev-parse', '--show-toplevel')).resolve()
    os.chdir(root)
    common = Path(git('rev-parse', '--git-common-dir')).resolve()
except sp.CalledProcessError:
    raise SystemExit('studio: run inside a Git-controlled source tree')

prefix = 'refs/heads/codex/'
local = set(git(
    'for-each-ref', '--format=%(refname)', prefix
).splitlines())

cached_prefix = 'refs/remotes/origin/codex/'
cached = {
    prefix + ref[len(cached_prefix):]
    for ref in git(
        'for-each-ref', '--format=%(refname)', cached_prefix
    ).splitlines()
}

repo_id = hashlib.sha256(os.fsencode(common)).hexdigest()[:16]
state = Path(
    os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state'))
) / 'repo-tools/work' / repo_id
saved = {prefix + file.parent.name for file in state.glob('*/state.env')}

has_origin = sp.run(
    ['git', 'remote', 'get-url', 'origin'], capture_output=True
).returncode == 0

live = set()
online = False

if has_origin:
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    if 'GIT_SSH_COMMAND' not in env and 'GIT_SSH' not in env:
        env['GIT_SSH_COMMAND'] = (
            'ssh -o BatchMode=yes -o ConnectTimeout=3 '
            '-o ConnectionAttempts=1'
        )

    process = sp.Popen(
        ['git', 'ls-remote', '--heads', 'origin', 'refs/heads/codex/*'],
        stdout=sp.PIPE, stderr=sp.PIPE, text=True,
        env=env, start_new_session=True
    )

    try:
        output, _ = process.communicate(timeout=5)
        online = process.returncode == 0
        if online:
            live = {
                line.split('\t', 1)[1]
                for line in output.splitlines() if '\t' in line
            }
    except sp.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()

rows = []
for ref in sorted(local | saved | (live if online else cached)):
    if not ref.startswith(prefix):
        continue
    stream = ref[len(prefix):]
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', stream):
        continue

    branch = 'codex/' + stream

    if not has_origin:
        remote = 'no remote (origin not configured)'
    elif online:
        remote = 'origin/' + branch if ref in live else 'no remote'
    elif ref in cached:
        remote = 'origin/' + branch + ' (cached)'
    else:
        remote = 'unknown'

    rows.append((stream, branch, remote))

width1 = max([len('STREAM')] + [len(row[0]) for row in rows])
width2 = max([len('BRANCH')] + [len(row[1]) for row in rows])

print(f'{"STREAM":<{width1}}  {"BRANCH":<{width2}}  REMOTE')
for stream, branch, remote in rows:
    print(f'{stream:<{width1}}  {branch:<{width2}}  {remote}')

if not rows:
    print('No streams found.')

if has_origin and not online:
    print(
        '\nOrigin unavailable (network/authentication). '
        'Cached branches may be stale; unknown means unverified.'
    )
