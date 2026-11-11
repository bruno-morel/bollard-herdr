#!/usr/bin/env python3
from pathlib import Path
from repo_sessions import name as readable_name
import fcntl, os, re, shlex, subprocess as sp, sys

root, state, wtroot, runtime = map(
    lambda value: Path(value).resolve(), sys.argv[1:5]
)
slug = re.sub(r'[^a-z0-9]+', '-', sys.argv[5].lower()).strip('-')
existing_only = '--existing-only' in sys.argv[6:]

if not slug:
    sys.exit('work: invalid stream name')

branch = 'codex/' + slug
record = state / slug / 'state.env'

def fail(message):
    sys.exit('work: ' + message)

def git(*args, remote=False, check=True):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    if 'GIT_SSH_COMMAND' not in env and 'GIT_SSH' not in env:
        env['GIT_SSH_COMMAND'] = (
            'ssh -o BatchMode=yes -o ConnectTimeout=10 '
            '-o ConnectionAttempts=1'
        )
    try:
        return sp.run(
            ['git', '-C', str(root), *args],
            capture_output=True, text=True, env=env,
            timeout=30 if remote else None, check=check
        )
    except sp.TimeoutExpired:
        fail('remote lookup timed out; retry when connected.')
    except sp.CalledProcessError as exc:
        fail(exc.stderr.strip() or 'Git operation failed')

def read_state(file):
    keys = [
        'SLUG', 'SLOT', 'WORKTREE_PATH', 'BRANCH',
        'SESSION', 'ENV_SOURCE_ROOT', 'LEGACY_COMPOSE'
    ]
    command = 'set -e; source "$1"; printf "%s\\0" ' + ' '.join(
        '"${' + key + ':-}"' for key in keys
    )
    values = sp.check_output(
        ['zsh', '-c', command, 'state', str(file)], text=True
    ).split('\0')
    return dict(zip(keys, values))

def ref_exists(ref):
    return git(
        'show-ref', '--verify', '--quiet', ref, check=False
    ).returncode == 0

os.umask(0o077)
runtime.mkdir(parents=True, exist_ok=True)

# This lock is automatically released if the process crashes.
with (runtime / 'recovery.lock').open('a') as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fail('another stream is being prepared; retry shortly')

    saved = read_state(record) if record.exists() else None
    if saved and (
        saved['SLUG'] != slug or saved['BRANCH'] != branch
    ):
        fail('runtime record does not match ' + branch)

    entries = []
    output = git('worktree', 'list', '--porcelain', '-z').stdout
    for chunk in output.split('\0\0'):
        entry = {}
        for line in chunk.split('\0'):
            key, _, value = line.partition(' ')
            entry[key] = value
        if 'worktree' in entry:
            entries.append(entry)

    matches = [
        entry for entry in entries
        if entry.get('branch') == 'refs/heads/' + branch
    ]
    if len(matches) > 1:
        fail('multiple checkouts use ' + branch + '; resolve them first')

    if saved and Path(saved['WORKTREE_PATH']).exists():
        target = Path(saved['WORKTREE_PATH']).resolve()
        registered = next(
            (entry for entry in entries
             if Path(entry['worktree']).resolve() == target),
            None
        )
        if not registered or registered.get('branch') != 'refs/heads/' + branch:
            fail('recorded checkout is not on ' + branch + '; nothing changed')
        sys.exit(0)

    if saved and saved['LEGACY_COMPOSE'] not in ('', '0'):
        fail('missing legacy checkout needs manual recovery; state preserved')

    if matches:
        target = Path(matches[0]['worktree']).resolve()
        if not target.is_dir():
            fail(
                'Git still registers an unavailable worktree at ' + str(target)
                + '. Restore its location or repair its registration first; '
                'metadata was preserved.'
            )
        if target == Path(entries[0]['worktree']).resolve():
            fail(
                'feature is checked out in the primary checkout; '
                'switch that checkout to main first'
            )
        print('Recovering existing checkout ' + str(target), file=sys.stderr)
    elif saved:
        target = Path(saved['WORKTREE_PATH']).resolve()
    else:
        target = wtroot / slug

    create = not matches
    if create and target.exists():
        fail('destination exists but is not this stream: ' + str(target))

    used = set()
    records = list((runtime / 'work').glob('*/*/state.env'))
    records += list(runtime.parent.glob('*/*/state.env'))

    for other in records:
        if other.resolve() == record.resolve():
            continue
        found = re.search(r'^SLOT=(\d+)\s*$', other.read_text(), re.M)
        if found:
            used.add(int(found[1]))

    slot = int(saved['SLOT']) if saved and saved['SLOT'].isdigit() else None
    envfile = record.parent / 'compose.env'

    if slot is None and envfile.exists():
        match = re.search(
            r'^VITE_API_BASE_URL=http://localhost:(\d+)/api\s*$',
            envfile.read_text(), re.M
        )
        if match and (int(match[1]) - 5173) % 100 == 0:
            slot = (int(match[1]) - 5173) // 100

    if slot is not None and (not 1 <= slot < 100 or slot in used):
        fail('recovered port slot conflicts with another stream')
    if slot is None:
        slot = next((n for n in range(1, 100) if n not in used), None)
    if slot is None:
        fail('no free port slots')

    if create:
        local = 'refs/heads/' + branch
        remote_ref = 'refs/remotes/origin/' + branch

        if ref_exists(local):
            base = None
            print('Recovering local branch ' + branch, file=sys.stderr)
        elif ref_exists(remote_ref):
            base = remote_ref
            print(
                'Recovering cached origin/' + branch + '; no network required',
                file=sys.stderr
            )
        else:
            probe = git(
                'ls-remote', '--exit-code', '--heads',
                'origin', 'refs/heads/' + branch,
                remote=True, check=False
            )
            if probe.returncode == 0:
                git(
                    'fetch', 'origin',
                    '+refs/heads/' + branch + ':' + remote_ref,
                    remote=True
                )
                base = remote_ref
                print('Recovering pushed stream ' + branch, file=sys.stderr)
            elif probe.returncode == 2:
                if existing_only or saved:
                    fail('no local or remote branch found; no replacement created')
                git(
                    'fetch', 'origin',
                    '+refs/heads/main:refs/remotes/origin/main',
                    remote=True
                )
                base = 'refs/remotes/origin/main'
                print('Creating new stream ' + branch, file=sys.stderr)
            else:
                fail(
                    'cannot reach origin or authenticate, and no local/cached '
                    'stream exists. Retry when connected; no branch was created.'
                )

        target.parent.mkdir(parents=True, exist_ok=True)
        if base:
            git('worktree', 'add', '-b', branch, str(target), base)
        else:
            git('worktree', 'add', str(target), branch)

    exclude = Path(git(
        '-C', str(target), 'rev-parse', '--git-path', 'info/exclude'
    ).stdout.strip())
    if not exclude.is_absolute():
        exclude = target / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    ignored = exclude.read_text() if exclude.exists() else ''
    if '/scratch/' not in ignored.splitlines():
        exclude.write_text(ignored + '\n/scratch/\n')
    (target / 'scratch').mkdir(exist_ok=True)

    # Refresh generated Docker configuration at the next Work startup.
    # Keep the existing file usable until then.
    if (record.parent / 'compose.work.json').exists():
        (record.parent / 'compose.refresh').touch()

    record.parent.mkdir(parents=True, exist_ok=True)
    values = dict(
        SLUG=slug,
        SLOT=str(slot),
        WORKTREE_PATH=str(target),
        BRANCH=branch,
        SESSION=(saved or {}).get('SESSION') or readable_name('work', target),
        ENV_SOURCE_ROOT=(saved or {}).get('ENV_SOURCE_ROOT') or str(root)
    )
    for key, port in [
        ('TENHUMANS', 5173), ('TENGAYS', 5174), ('TENLEZ', 5175),
        ('POSTGRES', 5432), ('REDIS', 6379)
    ]:
        values['PORT_' + key] = str(port + slot * 100)

    pending = record.with_name('state.env.pending')
    pending.write_text(''.join(
        key + '=' + shlex.quote(value) + '\n'
        for key, value in values.items()
    ))
    pending.replace(record)
    print('Stream ready: ' + str(target), file=sys.stderr)
