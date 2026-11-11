#!/usr/bin/env python3
"""Studio/Work terminals in herdr-core; all runtime data stays outside Git."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from repo_state import write_json
from pathlib import Path
import re
import shutil
import subprocess as sp
import sys

BIN = Path(__file__).resolve().parent
AGENTS = ('codex', 'claude', 'cursor')


def agent_api():
    spec = importlib.util.spec_from_file_location('repo_agent', BIN/'repo-agent.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fail(message):
    raise RuntimeError(message)


def call(args, **kwargs):
    return sp.run([str(x) for x in args], check=True, **kwargs)


def hc_json(*args):
    p = sp.run(['hc', *args, '--json'], capture_output=True, text=True, timeout=20)
    if p.returncode:
        fail(p.stderr.strip() or p.stdout.strip() or 'cannot inspect Herdr')
    return json.loads(p.stdout)


def trees(api, root):
    raw = sp.check_output(['git', '-C', str(root), 'worktree', 'list', '--porcelain', '-z'])
    return [dict(os.fsdecode(x).split(' ', 1) for x in record.split(b'\0') if b' ' in x)
            for record in raw.split(b'\0\0') if record]


def target_for(api, root, stream):
    matches = [x for x in trees(api, root) if x.get('branch') == 'refs/heads/codex/'+stream]
    if len(matches) > 1:
        fail('multiple worktrees use codex/'+stream)
    return Path(matches[0]['worktree']).resolve() if matches else None


def same_path(left, right):
    try:
        return os.path.samefile(left, right)
    except OSError:
        return Path(left).resolve() == Path(right).resolve()


def agent_lock_message(path, role, stream):
    """Describe a live owner without signalling it or changing the lock."""
    location = 'another terminal'
    try:
        result = sp.run(['lsof', '-t', '--', str(path)],
                        capture_output=True, text=True, timeout=2)
        # Our failed lock attempt also has this file open. Ignore that handle.
        owners = {int(x) for x in result.stdout.split() if x.isdigit()} - {os.getpid()}
        for pid in sorted(owners)[:4]:
            seen = set()
            for _ in range(8):
                if pid <= 1 or pid in seen:
                    break
                seen.add(pid)
                proc = sp.run(['ps', '-p', str(pid), '-o', 'ppid=', '-o', 'comm='],
                              capture_output=True, text=True, timeout=1)
                fields = proc.stdout.strip().split(None, 1)
                if proc.returncode or len(fields) != 2 or not fields[0].isdigit():
                    break
                if Path(fields[1]).name == 'zellij':
                    location = 'Zellij'
                    break
                pid = int(fields[0])
            if location == 'Zellij':
                break
    except (OSError, sp.SubprocessError):
        pass  # Inspection is optional; the live lock always remains authoritative.
    return (f'{role.title()} for {stream} is already running in {location}. '
            'Exit that agent normally before opening it in Herdr. '
            'The existing agent and Docker were left running.')


@contextmanager
def locked(path, message):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail(message() if callable(message) else message)
        yield


def read_record(pref):
    path = pref.with_suffix('.herdr.json')
    return json.loads(path.read_text()) if path.exists() else {}


def write_record(pref, data):
    path = pref.with_suffix('.herdr.json')
    write_json(path, data, indent=2)


def local_terminals(target):
    result = []
    for row in hc_json('ls', '--all').get('terminals', []):
        if '/' in row['address'] or not same_path(row.get('cwd') or '/', target):
            continue
        result.append(hc_json('get', row['address']))
    return result


def role_of(row, repo_id, stream, repo, target):
    labels = row.get('labels') or {}
    if labels.get('repo-tools.repo') == repo_id and labels.get('repo-tools.stream') == stream:
        return labels.get('repo-tools.role')
    # Adopt the old pilot and the one-time recovery command, only in its exact checkout.
    key = hashlib.sha256(os.fsencode(str(target.resolve()))).hexdigest()[:6]
    for role in ('studio', 'work'):
        legacy = {f'{role}-{repo[:6]}-{stream[:10]}-{key}', f'{role}-{stream}'}
        if row.get('name') in legacy:
            return role
    return None


def terminal_labels(role, repo_id, stream, target, name, space, tab):
    return {'herdr.space': space, 'herdr.tab': tab,
            'repo-tools.repo': repo_id, 'repo-tools.stream': stream,
            'repo-tools.role': role, 'repo-tools.agent': name,
            'repo-tools.checkout': str(target)}


def show_terminal(address, role, stream, attach):
    print(f'{role.title()} {stream}: {address}. Select its space in the Herdr app.', flush=True)
    print(f'Terminal access: hc attach {address}  (Ctrl+\\ detaches)', flush=True)
    if attach:
        if os.environ.get('HC_TERMINAL_ID') or os.environ.get('ZELLIJ'):
            fail('select the pane in the app; use --attach from a shell outside Herdr/Zellij')
        os.execvp('hc', ['hc', 'attach', address])


def open_stream(args):
    api = agent_api()
    try:
        root = api.root_at()
    except RuntimeError:
        fail('run this command inside a Git-controlled source tree')
    stream = api.slug(args.stream) if args.stream else api.current(root)
    role = args.role
    if args.take and role != 'work':
        fail('--take is available with work herdr only')
    if not shutil.which('hc'):
        fail('hc is not installed/on PATH')
    if args.attach and (os.environ.get('HC_TERMINAL_ID') or os.environ.get('ZELLIJ')):
        fail('--attach is for a shell outside Herdr/Zellij; select the stream in the app here')
    pref = api.preferences(root, stream, role)
    repo_id = pref.parents[1].name
    repo = re.sub('[^a-z0-9-]+', '-', Path(trees(api, root)[0]['worktree']).name.lower()).strip('-') or 'repo'
    in_place = None
    # Shared by both roles, so first registration gives them one space per stream.
    with locked(pref.parent/'herdr-launch.lock', 'another launcher is opening this stream; retry shortly'):
        target = target_for(api, root, stream)
        rows = local_terminals(target) if target and target.is_dir() else []
        matches = [r for r in rows if role_of(r, repo_id, stream, repo, target) == role]
        live = [r for r in matches if r['state'] == 'live']
        if len(live) > 1:
            fail('multiple live terminals match this role/stream; inspect hc ls before continuing')
        record = read_record(pref)
        name = args.agent or api.selected(pref)
        if live:
            row = live[0]
            api.packet(target, stream)
            foreground = (row.get('foreground') or {}).get('name')
            old_agent = (row.get('labels') or {}).get('repo-tools.agent')
            old_agent = old_agent or (foreground if foreground in AGENTS else None) or record.get('agent') or name
            current = os.environ.get('HC_TERMINAL_ID') == row['address']
            # No injected keystrokes or restarts of a running program.
            requested = args.resume is not None or args.new_chat or args.take or args.task_file or (args.agent and args.agent != old_agent)
            if requested and not current:
                fail('this terminal is already live; use its Resume/New chat menu or shell to change agents/chats')
            space = (row.get('labels') or {}).get('herdr.space') or 'stream-'+repo_id+'-'+stream
            tab = (row.get('labels') or {}).get('herdr.tab') or space+'-'+role
            labels = terminal_labels(role, repo_id, stream, target, old_agent, space, tab)
            call(['hc', 'label', row['address'], *[k+'='+v for k, v in labels.items()]], stdout=sp.DEVNULL)
            call(['hc', 'keep', row['address']], stdout=sp.DEVNULL)
            write_record(pref, dict(record, address=row['address'], agent=old_agent, started=True))
            if current:
                # Invoked from this pane's shell: run in place, preserving its parent supervisor.
                mode = 'new' if args.new_chat or args.take else 'resume'
                in_place = (api, target, role, stream, name, mode, args.resume or '', args.take)
            address = row['address']
        else:
            api.executable(name)
            if name == 'codex':
                help_result = sp.run([api.executable(name), '--help'], capture_output=True, text=True, timeout=15)
                if '--no-daemon' not in help_result.stdout + help_result.stderr:
                    fail('this Codex version does not support --no-daemon; update it before using Herdr')
            with locked(pref.with_suffix('.lock'),
                        lambda: agent_lock_message(pref.with_suffix('.lock'), role, stream)):
                # Reuses work's Git recovery and slot allocation, preserving current docs and changes.
                call([BIN/'work', 'prepare', stream], cwd=root)
                target = api.checkout(root, stream)
                api.packet(target, stream)
                call([sys.executable, BIN/'repo-transfer.py', 'init', target], cwd=target)
                if role == 'studio' and not (target/'docs/handoffs'/stream).exists():
                    call([BIN/'studio', 'handoff', 'new', stream], cwd=target)
                api.context(target, stream)
                if role == 'work':
                    packet = api.packet(target, stream)
                    if (args.take or any((packet/x).is_file() for x in ('brief.md', 'acceptance.md'))) and not any(
                        (packet/x).is_file() and (packet/x).read_text().strip()
                        for x in ('implementation.md', 'codex-prompt.md')):
                        fail('build the implementation handoff first: studio handoff')
                    call([BIN/'work', '_herdr-start', stream], cwd=target)
                pref.write_text(name+'\n')
            # Reuse the space of the other role or a finished terminal, when one exists.
            related = [r for r in rows if role_of(r, repo_id, stream, repo, target) in ('studio', 'work')]
            spaces = {(r.get('labels') or {}).get('herdr.space') for r in related} - {None, ''}
            if len(spaces) > 1:
                fail('this stream has conflicting Herdr spaces; reconcile its terminal labels first')
            space = next(iter(spaces), 'stream-'+repo_id+'-'+stream)
            tabs = {(r.get('labels') or {}).get('herdr.tab') for r in matches} - {None, ''}
            tab = next(iter(tabs)) if len(tabs) == 1 else space+'-'+role
            labels = terminal_labels(role, repo_id, stream, target, name, space, tab)
            key = hashlib.sha256((repo_id+'/'+stream).encode()).hexdigest()[:10]
            terminal_name = f'{role}-{repo[:5]}-{stream[:7]}-{key}' # <=31 ASCII chars
            pane = [sys.executable, str(BIN/'repo_herdr.py'), '_pane', role, stream, '--agent', name]
            if role == 'work':
                # Load this stream's Compose environment inside the new terminal as well.
                pane = [str(BIN/'work'), '_herdr-pane', stream, '--agent', name]
            mode = 'new' if args.new_chat or args.take else 'resume' if args.resume is not None or record.get('started') else 'new'
            pane += ['--mode', mode]
            if args.resume:
                pane += ['--resume-id', args.resume]
            if args.take:
                pane += ['--take']
            if args.task_file:
                pane += ['--task-file', str(args.task_file)]
            command = ['hc', 'run', '--bg', '--keep', '--no-parent', '--name', terminal_name, '--cwd', str(target)]
            for k, v in labels.items():
                command += ['--label', k+'='+v]
            result = sp.run(command+['--']+pane, cwd=target)
            if result.returncode:
                fail('Herdr launch did not confirm success; inspect hc ls --all before retrying. Stream preserved.')
            row = hc_json('get', terminal_name)
            if row.get('state') != 'live':
                fail('terminal ended during startup; inspect hc read '+row['address'])
            address = row['address']
            write_record(pref, dict(record, address=address, agent=name, started=True))
    if in_place:
        return run_once(*in_place)
    show_terminal(address, role, stream, args.attach)
    return 0


def run_once(api, root, role, stream, name, mode, resume_id='', take=False, task_file=None):
    # Separate process: an agent update is picked up on the very next launch.
    command = [sys.executable, str(BIN/'repo-agent.py'), 'run', role, stream, '--agent', name, '--once']
    if mode == 'resume':
        command += ['--resume', resume_id]
    if take:
        command += ['--take-handoff']
    if task_file:
        command += ['--task-file', str(task_file)]
    try:
        return sp.run(command, cwd=root).returncode
    except KeyboardInterrupt:
        return 130


def pane_main(argv):
    p = argparse.ArgumentParser()
    p.add_argument('role', choices=('studio', 'work'))
    p.add_argument('stream')
    p.add_argument('--agent', choices=AGENTS, required=True)
    p.add_argument('--mode', choices=('new', 'resume'), default='new')
    p.add_argument('--resume-id', default='')
    p.add_argument('--take', action='store_true')
    p.add_argument('--task-file')
    a = p.parse_args(argv)
    api = agent_api()
    root = api.root_at()
    stream = api.slug(a.stream)
    api.packet(root, stream)
    name, mode, resume_id, take = a.agent, a.mode, a.resume_id, a.take
    while True:
        code = run_once(api, root, a.role, stream, name, mode, resume_id, take, a.task_file)
        a.task_file = None
        print(f'\n{name} exited ({code}). {a.role.upper()} / {stream} remains open.', flush=True)
        if not sys.stdin.isatty():
            return code
        while True:
            print('Enter/r: resume picker | r <ID>: resume chat | n: new chat | s: shell')
            print('codex / claude / cursor: switch agent and open its resume picker')
            try:
                choice = input('Choice: ').strip()
            except KeyboardInterrupt:
                print()
                continue
            except EOFError:
                return 0
            mode, resume_id, take = 'resume', '', False
            if choice in ('', 'r', 'resume'):
                break
            if choice.startswith('r ') and choice[2:].strip():
                resume_id = choice[2:].strip()
                break
            if choice in ('n', 'new'):
                mode = 'new'
                break
            if choice in AGENTS:
                name = choice
                break
            if choice in ('s', 'shell'):
                print('Opening a shell in this checkout. Exit the shell to return to this menu.')
                shell = os.environ.get('SHELL') or '/bin/zsh'
                try:
                    sp.run([shell, '-l'], cwd=root)
                except KeyboardInterrupt:
                    pass
                continue
            print('Choose r, n, s, or an agent name.')


def guard_remove(path):
    api = agent_api()
    root = api.root_at(path)
    stream = api.current(root)
    records = [api.preferences(root, stream, role).with_suffix('.herdr.json') for role in ('studio', 'work')]
    if not any(p.exists() for p in records):
        return 0
    live = [r for r in local_terminals(root) if r['state'] == 'live' and
            (r.get('labels') or {}).get('repo-tools.role') in ('studio', 'work')]
    if live:
        fail('close this stream\'s Herdr panes before removing its worktree: '+', '.join(r['address'] for r in live))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == '_pane':
        return pane_main(argv[1:])
    if argv and argv[0] == '_guard-remove':
        return guard_remove(argv[1])
    role = argv.pop(0) if argv and argv[0] in ('studio', 'work') else None
    if role is None:
        fail('invoke through studio herdr or work herdr')
    p = argparse.ArgumentParser(prog=role+' herdr', description='Create, reopen, or resume a shared stream in the Herdr app.')
    p.add_argument('stream', nargs='?', help='defaults to the current codex/<stream> branch')
    p.add_argument('--agent', choices=AGENTS)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--resume', nargs='?', const='', default=None, metavar='CHAT_ID', help='resume by ID, or open the agent\'s picker')
    mode.add_argument('--new-chat', action='store_true', help='start with fresh role/handoff context')
    mode.add_argument('--take', action='store_true', help='Work: prepare the latest handoff before implementation')
    p.add_argument('--task-file', help=argparse.SUPPRESS)
    p.add_argument('--attach', action='store_true', help='attach from a terminal outside Herdr/Zellij')
    args = p.parse_args(argv)
    args.role = role
    return open_stream(args)


if __name__ == '__main__':
    os.umask(0o077)
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, sp.SubprocessError) as exc:
        sys.exit('repo-herdr: '+str(exc))
