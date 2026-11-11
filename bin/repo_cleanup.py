import argparse
import json
import os
import re
import subprocess as sp
import sys
import time
from repo_sessions import listing
from repo_cleanup_labels import describe_session


def action(session, *args):
    p = sp.run(['zellij', '--session', session, 'action', *args],
               capture_output=True, text=True, timeout=5)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or 'Session inspection failed')
    return p.stdout


def clean(text):
    text = re.sub(r'\x1b\][^\x07]*(?:\x07|\x1b\\)', '', text)
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    return ''.join(c for c in text if c in '\n\t' or c.isprintable())


def inspect(session, seconds):
    panes = json.loads(action(session, 'list-panes', '--all', '--json'))
    if not isinstance(panes, list):
        raise RuntimeError('Unexpected pane response')
    clients = action(session, 'list-clients')
    connected = sum(bool(re.match(r'^\s*\d+\s', row)) for row in clients.splitlines())
    print(f'  Connected clients: {connected}')
    terminals = [p for p in panes if not p.get('is_plugin')]
    for p in terminals:
        command = p.get('pane_command') or p.get('terminal_command') or '?'
        print('  Pane: ' + clean(str(p.get('title', '?'))) + ' | ' + clean(str(command))
              + (' | process exited' if p.get('exited') else ''))
    agents = [p for p in terminals if not p.get('exited') and re.search(
        r'\b(codex|claude|cursor|cursor-agent|studio-agent|work-agent|ai)\b',
        str(p.get('pane_command', '')) + ' ' + str(p.get('title', ''))
        + ' ' + str(p.get('terminal_command', '')), re.I)]
    if not agents:
        print('  No agent pane identified. Inspect the commands above; this does not prove inactivity.')
        return []
    first = {p['id']: action(session, 'dump-screen', '--pane-id', 'terminal_' + str(p['id']))
             for p in agents}
    time.sleep(seconds)
    last = {p['id']: action(session, 'dump-screen', '--pane-id', 'terminal_' + str(p['id']))
            for p in agents}
    changed = any(first[k] != last[k] for k in first)
    print('  Agent output changed during inspection.' if changed else
          f'  Agent pane quiet for {seconds:g}s; it may still be working or awaiting input.')
    return [(str(p.get('title', 'Agent')), last[p['id']]) for p in agents]


def checked(*args):
    p = sp.run(['zellij', *args], capture_output=True, text=True, timeout=10)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or 'Zellij command failed')


def main(role):
    parser = argparse.ArgumentParser(description='Inspect and clean ' + role + ' sessions across repositories.')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--sample-seconds', type=float, default=2)
    args = parser.parse_args()
    if not 1 <= args.sample_seconds <= 10:
        parser.error('--sample-seconds must be between 1 and 10')
    current = os.environ.get('ZELLIJ_SESSION_NAME', '')
    entries = {s: row for s, row in listing().items() if s.startswith(role + '-')}
    if not entries:
        print('No ' + role + ' sessions found.')
        return
    print('All repositories. Age is creation age, not idle time. Project files and Docker are untouched.')
    failures = 0
    for session, row in entries.items():
        display = describe_session(session, row)
        print('\n' + display, flush=True)
        if session == current or '(current)' in row.lower():
            print('  Keeping current session.')
            continue
        try:
            latest = listing().get(session)
            if latest is None:
                continue
            if 'EXITED' not in latest:
                try:
                    previews = inspect(session, args.sample_seconds)
                except (RuntimeError, OSError, ValueError, KeyError, sp.SubprocessError) as exc:
                    print('  Activity unknown; keeping session: ' + clean(str(exc)))
                    continue
                if args.dry_run or not sys.stdin.isatty():
                    print('  Keeping running session; confirmation required.')
                    continue
                while True:
                    answer = input('  Close this session and stop its processes? [y/N/p=preview] ').strip().lower()
                    if answer != 'p':
                        break
                    if not previews:
                        print('  No agent preview available.')
                    for title, screen in previews:
                        print('\n  ' + clean(title) + '\n' + '\n'.join(clean(screen).splitlines()[-12:]))
                if answer not in ('y', 'yes'):
                    continue
                latest = listing().get(session)
                if latest is None:
                    continue
                if 'EXITED' not in latest:
                    checked('kill-session', session)
            if args.dry_run:
                print('  Would delete saved exited session.')
            else:
                checked('delete-session', session)
                print('  Deleted: ' + display)
        except (RuntimeError, OSError, sp.SubprocessError) as exc:
            failures += 1
            print('  Cleanup incomplete: ' + clean(str(exc)), file=sys.stderr)
    if failures:
        raise RuntimeError(str(failures) + ' cleanup operation(s) failed')


def run(role):
    try:
        main(role)
    except (RuntimeError, OSError, ValueError, sp.SubprocessError) as exc:
        sys.exit(role + ' cleanup: ' + str(exc))
    except (EOFError, KeyboardInterrupt):
        sys.exit('\nStopped; remaining sessions preserved.')
