#!/usr/bin/env python3
import argparse
from repo_roles import roles, selected as selected_role
from repo_risk_policy import POLICY as RISK_POLICY
import fcntl
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess as sp
import sys
from repo_sessions import resolve as resolve_session, setup as setup_sessions

AGENTS = ('codex', 'claude', 'cursor')

def fail(message):
    raise RuntimeError(message)

def git(root, *args):
    p = sp.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    if p.returncode:
        fail(p.stderr.strip() or 'Git command failed')
    return p.stdout.strip()

def root_at(path='.'):
    return Path(git(path, 'rev-parse', '--show-toplevel')).resolve()

def slug(value):
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', value):
        fail('invalid stream name: ' + value)
    return value

def current(root):
    branch = git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    if not branch.startswith('codex/'):
        fail('run inside a stream or supply its name')
    return slug(branch[6:])

def checkout(root, stream):
    raw = sp.check_output([
        'git', '-C', str(root), 'worktree', 'list', '--porcelain', '-z'
    ])
    found = []
    for record in raw.split(b'\0\0'):
        fields = dict(
            x.split(b' ', 1) for x in record.split(b'\0') if b' ' in x
        )
        if fields.get(b'branch') == ('refs/heads/codex/' + stream).encode():
            found.append(Path(os.fsdecode(fields[b'worktree'])).resolve())
    if len(found) != 1:
        fail('stream must have one existing worktree; open/prepare it first')
    if not found[0].is_dir():
        fail('stream checkout is unavailable')
    return found[0]

def file_at(root, rel):
    p = root
    for part in Path(rel).parts:
        if p.exists() and not p.is_dir():
            fail('expected directory: ' + str(p))
        p /= part
        if p.is_symlink():
            fail('refusing symlink: ' + str(p))
    return p

def packet(root, stream):
    if current(root) != stream:
        fail('checkout branch does not match stream')
    p = file_at(root, 'docs/handoffs/' + stream)
    identity = file_at(root, str(p.relative_to(root)/'branch.txt'))
    if identity.exists() and identity.read_text().strip() != 'codex/' + stream:
        fail('handoff branch does not match the checkout')
    return p

def context(root, stream):
    p = packet(root, stream)
    p.mkdir(parents=True, exist_ok=True)
    identity = p/'branch.txt'
    if not identity.exists():
        identity.write_text('codex/' + stream + '\n')
    f = file_at(root, str(p.relative_to(root)/'context.md'))
    if not f.exists():
        f.write_text(
            '# Stream context\n\n'
            'Maintain this file manually; handoff builds never overwrite it.\n\n'
            '## Current progress\n\n'
            'Not yet summarized. Read the existing stream documents.\n\n'
            '## Open questions\n\n## Next steps\n\n'
            '## Validation and useful references\n'
        )

def prompt(root, stream, role):
    takeover = preferences(root, stream, role).with_suffix('.take')
    taking = role == 'work' and takeover.is_file()
    if taking:
        recorded = Path(takeover.read_text().strip())
        if not recorded.is_dir() or not os.path.samefile(recorded, root):
            fail('take request belongs to a different checkout')
    take_rules = ''
    if role == 'work':
        take_rules = f"""HANDOFF PREPARATION
When asked to take the handoff, perform this preparation now:
1. Verify codex/{stream}, inspect Git status, and preserve existing changes.
2. Reread the latest implementation handoff, context, brief, decisions, acceptance
   and references from disk every time, even when you reviewed them earlier. Read
   any existing implementation-plan.md and compare it with the current code.
   Treat proposed actions as scope, not permission to skip preparation.
3. Inspect relevant source files, tests, project commands and repository guidance.
   Identify stale assumptions, missing decisions, dependencies and blockers.
4. Write or carefully update docs/handoffs/{stream}/implementation-plan.md with
   the understood scope, affected code, ordered coding steps, acceptance checks,
   proposed validation commands, and unresolved questions. Preserve completed steps
   and useful prior work. Record what changed since the previous review and the
   SHA-256 of the handoff you reviewed. Flag revised requirements that conflict
   with existing code or decisions rather than undoing prior work silently.
5. Update context.md with the preparation status and a link to the plan. Report
   whether you are ready or blocked and what approval or decisions are needed.
Do not change application code, install dependencies, run migrations, commit,
push, or start implementation during preparation. Do not claim exclusive ownership;
Studio may still be active on this shared checkout. Coordinate overlapping edits.
Preserve handoff source documents and existing application changes. Never reset,
clean, stash, revert, switch branches or replace the worktree as part of take.
Reread shared documents immediately before editing and make focused updates; do
not overwrite newer Studio changes in context.md or the implementation plan.
Before starting or resuming implementation, recheck the handoff against the plan.
If it changed, reassess the affected steps and surface conflicts before coding.
Do not treat preparation as completed implementation or as completed validation.
Follow the file-review instructions for this session when asked to show the plan.
"""
    startup = (
        "The user invoked work take. Carry out HANDOFF PREPARATION now, then stop "
        "and wait for the user's go-ahead before implementation."
        if taking else
        "For this startup message, read the relevant context, briefly confirm your role, "
        "branch and readiness, then wait for the user's task. Do not begin implementation."
    )
    p = packet(root, stream)
    implementation = p/'implementation.md'
    if not implementation.is_file():
        implementation = p/'codex-prompt.md'
    rules = (
        'Plan, research, and develop product or marketing material under docs/. '
        'Do not implement application code unless the user explicitly changes scope. '
        'An implementation handoff is context, not authorization to start coding.'
        if role == 'studio' else
        'Implement the user-requested work. Read the implementation handoff, inspect '
        'the actual code, follow acceptance criteria, and run relevant validation. '
        'If scope or acceptance criteria are missing, clarify before implementing.'
    )
    profile_id, profile = selected_role(root, preferences(root, stream, role), role)
    if profile['instructions']:
        rules += '\n\nAdditional role guidance (preserve the workflow rules below):\n' + profile['instructions']
    if role == 'work':
        rules += (' For MEDIUM/HIGH changes or an explicit review request, before declaring ready to merge, prepare every acceptance criterion '
                  'and the repository-specific finite validation commands with work review --prepare. '
                  'Fill docs/handoffs/' + stream + '/review-input.json using review-guide.md. '
                  'Run normal checks and exercise the actual feature first; preserve failures and fix causes. '
                  'Then use work review for the independent final review (Claude by default; choose a different provider from the implementation agent). This end-stage review is '
                  'authorized; do not launch additional Claude agents during implementation. '
                  'Pause overlapping edits while reviewing. Use work review --status to check the verdict. '
                  'Fix findings without weakening tests or silently reducing acceptance scope. '
                  'One --follow-up is allowed; --new-cycle needs an explicit user request. '
                  'Quota limits, missing evidence and unavailable services mean incomplete, never passed. '
                  'Only Verified for this version is review approval. It does not authorize a merge or push. '
                  'Reports live in the handoff reviews/ directory; raw evidence belongs in ignored scratch/.')
        rules += "\n\n" + RISK_POLICY
    rules += f'\n\nROLE PROFILE: {profile_id}. Read docs/handoffs/{stream}/roles/{profile_id}.md if present. Maintain your own role progress there; preserve other role notes and keep shared context.md current.'
    handoff = (
        str(implementation.relative_to(root))
        if implementation.is_file() else '(not built)'
    )
    # Herdr-core startup v1
    reader_rules = f'HERDR SESSION\nThis agent runs in herdr-core. Keep the {role.upper()} role and shared handoff rules.\nHERDR DOCS / FILES PANEL\nWhen the user asks to open or show a repository file, run:\nrepo-read --show \'<repository-relative-path>\'\nQuote the actual path correctly for the shell. This routes the full file to the\nseparate Docs (Markdown/.txt) or Files panel in Herdr desktop or the Studio/Work TUI. Keep the conversation separate; each viewer uses its own file presentation.\nKeep your agent process and conversation in the current STUDIO or WORK terminal.\nDo not start a reader in your own terminal, split panes, or run Zellij commands.\nOnly report the file opened if the command says Opened; Queued means the user must\nselect this stream in the Studio Work layout. Report routing errors accurately.\nAfter substantially updating a document, offer to show it; do not send file requests\nunprompted during background work. If execution requires approval, request it normally.\nDo not run studio open or work open from this terminal; they still launch Zellij.\nDo not start other agents unless the user explicitly asks. If authorized to delegate,\nread hc --skill first and use its installed-version instructions.\nCore restarts do not guarantee conversation resumption. Maintain context.md for recovery.\n' if os.environ.get('HC_TERMINAL_ID') else "READ PANE ROUTING\nWhen the user asks to open or show a repository file, run:\nrepo-read --show '<repository-relative-path>'\nQuote the actual path correctly for the shell. This sends the file to the\nexisting READ pane in this Zellij session and focuses it. Keep your agent\nprocess and conversation in the current STUDIO or WORK pane.\nDo not launch an interactive reader in your own pane or create another pane.\nAfter creating or substantially updating a document, offer to show it; do not\nswitch tabs automatically while continuing background work.\nIf routing fails, report the error rather than claiming the file opened.\nIf execution requires approval, request the normal command approval."
    return f'''SESSION ROLE: {role.upper()} — {profile['label']}
Checkout: {root}
Expected branch: codex/{stream}
Stream: {stream}

Read AGENTS.md, CLAUDE.md, and applicable instructions for any files you edit.
Read docs/REPO-WORKFLOW.md if present. Keep existing repository conventions.
Your role is {role.upper()}: {rules}

Read docs/handoffs/{stream}/context.md and the brief, decisions, acceptance,
and references documents if present. Implementation handoff: {handoff}
Prefer implementation.md; codex-prompt.md is the legacy fallback.

ITERATIVE HANDOFF
Planning and implementation may alternate repeatedly on this same stream.
In the planning role, read current context, any existing implementation plan and
relevant implemented code before revising requirements. Preserve implementation
progress; make changed decisions explicit instead of silently replacing them.
The brief, decisions, acceptance and references are the durable handoff sources.
implementation.md is regenerated by studio handoff; do not keep unique notes only
in that generated file. implementation-plan.md records the coding plan and progress.
Both roles must preserve each other's changes and reread shared documents before
making focused edits. A handoff or take does not reset the checkout or its history.

Use this checkout and branch. Do not create another worktree or switch branches.
Check Git status and preserve existing changes. Coordinate with other agents
before changing overlapping files. Keep persistent artifacts under docs/ and
intermediate/large generated assets in ignored scratch/. Never store credentials
or machine/session state in the repository.

Update context.md with progress, open questions, next steps and validation before
handing work to another agent. Do not replace it with an invented conversation summary.
Use studio handoff when asked to build the implementation document; it does not
change the session role. Conversation history is not shared between agents.

{reader_rules}

{take_rules}
{startup}
'''

def build(root, stream):
    p = packet(root, stream)
    parts = []
    for name in ('brief', 'decisions', 'acceptance', 'references'):
        f = file_at(root, str(p.relative_to(root)/(name + '.md')))
        if not f.is_file():
            fail('missing handoff source: ' + str(f))
        parts.append(f.read_text())
    out = file_at(root, str(p.relative_to(root)/'implementation.md'))
    context(root, stream)
    text = (
        f'# Implementation handoff — {stream}\n\n'
        f'Expected branch: codex/{stream}\n\n'
        'This document is agent-neutral. Read repository guidance and context.md first.\n'
        'It describes implementation scope; it does not switch a planning session into\n'
        'implementation mode. Inspect the current code and verify old assumptions.\n\n'
        '---\n\n' + '\n\n---\n\n'.join(parts) +
        '\n\n---\n\nReport changes, validation results, unresolved issues and next steps.\n'
    )
    out.write_text(text)
    print('Built: ' + str(out))

def preferences(root, stream, role):
    common = (root/Path(git(root, 'rev-parse', '--git-common-dir'))).resolve()
    key = hashlib.sha256(os.fsencode(common)).hexdigest()[:16]
    runtime = (
        Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state')))
        /'repo-tools'
    ).resolve()
    records = sp.check_output([
        'git', '-C', str(root), 'worktree', 'list', '--porcelain', '-z'
    ])
    for record in records.split(b'\0'):
        if record.startswith(b'worktree '):
            tree = Path(os.fsdecode(record[9:])).resolve()
            if tree == runtime or tree in runtime.parents:
                fail('runtime state must be outside all worktrees')
    return runtime/'agents'/key/stream/(role + '.agent')

def selected(f):
    name = f.read_text().strip() if f.exists() else 'codex'
    if name not in AGENTS:
        fail('invalid saved agent: ' + name)
    return name

def executable(name):
    candidates = ('cursor-agent', 'agent') if name == 'cursor' else (name,)
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path
    fail(name + ' CLI is not installed/on PATH; install and sign in on JumpBox first')

def sessions():
    setup_sessions()
    p = sp.run(['zellij', 'list-sessions', '-n'], capture_output=True, text=True)
    if p.returncode:
        if any(x in (p.stdout + p.stderr).lower() for x in ('no active', 'no sessions')):
            return []
        if not p.stdout.strip() and not p.stderr.strip():
            return []
        fail('cannot inspect Zellij sessions: ' + p.stderr.strip())
    return [
        line.split()[0] for line in p.stdout.splitlines()
        if line.strip() and 'EXITED' not in line
    ]

def configure(root, stream, role, requested):
    f = preferences(root, stream, role)
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if requested and requested != selected(f):
                fail('agent is running; exit it and use its pane chooser to switch')
            return
        old = selected(f)
        name = requested or old
        if name not in AGENTS:
            fail('agent must be codex, claude, or cursor')
        live = sessions()
        try:
            target = checkout(root, stream)
        except RuntimeError:
            target = None
        key = f.parents[1].name
        session = (
            'studio-' + hashlib.sha256(os.fsencode(target)).hexdigest()[:16]
            if role == 'studio' and target else 'work-' + key + '-' + stream
        )
        if role == 'work':
            record = f.parents[3]/'work'/key/stream/'state.env'
            if record.is_file():
                session = sp.check_output([
                    'zsh', '-c', 'source "$1"; printf "%s" "$SESSION"',
                    'read-session', str(record)
                ], text=True)
        if target:
            session = resolve_session(role, target, session)
        if session in live:
            if name != old:
                fail(
                    'session is running with ' + old +
                    '. Exit its agent first; use the agent chooser in that pane. '
                    'No session was interrupted.'
                )
            return
        executable(name)
        f.write_text(name + '\n')

def run_agent(root, stream, role, requested, resume=None, once=False, take=False, task_file=None):
    f = preferences(root, stream, role)
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail('an agent launcher already owns this stream/role; return to its pane')
        name = requested or selected(f)
        if take:
            p = packet(root, stream)
            if role != 'work' or not any((p/x).is_file() and (p/x).read_text().strip()
                                       for x in ('implementation.md', 'codex-prompt.md')):
                fail('build the Work handoff first: studio handoff')
            f.with_suffix('.take').write_text(str(root)+'\n')
        while True:
            if name not in AGENTS:
                fail('agent must be codex, claude, or cursor')
            binary = executable(name)
            packet(root, stream)
            context(root, stream)
            p = packet(root, stream)
            if (
                role == 'work'
                and any((p/x).is_file() for x in ('brief.md', 'acceptance.md'))
                and not any((p/x).is_file() for x in ('implementation.md', 'codex-prompt.md'))
            ):
                fail('build the handoff first: studio handoff')
            f.write_text(name + '\n')
            text = prompt(root, stream, role)
            if task_file:
                task_path = Path(task_file)
                if task_path.is_symlink(): fail('workflow task must not be a symlink')
                task_path = task_path.resolve()
                allowed = (f.parent/'workflow').resolve()
                if task_path.parent != allowed or task_path.is_symlink() or task_path.stat().st_size > 64000:
                    fail('workflow task must be a bounded file in this stream runtime directory')
                text += '\nEXPLICIT USER WORKFLOW TASK (supersedes startup wait only):\n' + task_path.read_text()
            takeover = f.with_suffix('.take')
            pending_take = takeover.read_text() if role == 'work' and takeover.is_file() else None
            if pending_take is not None and resume == '':
                fail('pending handoff preparation: use a new Work chat or an explicit resume ID')
            if pending_take is not None:
                takeover.unlink()
            args = (
                [binary] + (['--no-daemon'] if os.environ.get('HC_TERMINAL_ID') else []) + ['--cd', str(root), text]
                if name == 'codex' else [binary, text]
            )
            if resume is not None:
                if name == 'codex':
                    args = [binary, 'resume', '--cd', str(root)]
                    if os.environ.get('HC_TERMINAL_ID'):
                        args += ['--no-daemon']
                else:
                    args = [binary, '--resume']
                # An empty ID opens the native picker. Never choose --last/--continue:
                # Studio and Work intentionally share a checkout, not a conversation.
                if resume:
                    args += [resume, text]
                print('Select the saved ' + role.upper() + ' conversation for ' + stream + '.', flush=True)
            if once and os.environ.get('HC_TERMINAL_ID') and shutil.which('hc'):
                sp.run(['hc', 'label', os.environ['HC_TERMINAL_ID'], 'repo-tools.agent='+name, 'repo-tools.profile='+selected_role(root, f, role)[0]],
                       stdout=sp.DEVNULL, stderr=sp.DEVNULL)
            print('Starting ' + name + ' in ' + role.upper() + ' role.', flush=True)
            try:
                result = sp.run(args, cwd=root)
            except OSError:
                if pending_take is not None:
                    takeover.write_text(pending_take)
                raise
            except KeyboardInterrupt:
                result = sp.CompletedProcess(args, 130)
            if once:
                return result.returncode
            resume = None
            if not sys.stdin.isatty():
                break
            try:
                name = input(
                    '\nAgent exited. Start codex / claude / cursor, or Enter for a shell: '
                ).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not name:
                break

# Work take v1
def take_work(root, stream, requested):
    if os.environ.get('ZELLIJ') or os.environ.get('ZELLIJ_SESSION_NAME'):
        fail('detach first, then run work take; or ask the existing Work agent to take the handoff')
    target = checkout(root, stream)
    p = packet(target, stream)
    implementation = file_at(target, str(p.relative_to(target)/'implementation.md'))
    if not implementation.is_file():
        implementation = file_at(target, str(p.relative_to(target)/'codex-prompt.md'))
    if not implementation.is_file() or not implementation.read_text().strip():
        fail('build the handoff first: run studio handoff inside this stream')
    f = preferences(target, stream, 'work')
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail('Work agent already running; ask it to read the handoff and prepare an implementation plan, without coding yet')
        key = f.parents[1].name
        session = 'work-' + key + '-' + stream
        record = f.parents[3]/'work'/key/stream/'state.env'
        if record.is_file():
            session = sp.check_output([
                'zsh', '-c', 'source "$1"; printf "%s" "$SESSION"',
                'read-session', str(record)
            ], text=True)
        session = resolve_session('work', target, session)
        if session in sessions():
            fail('Work session already running; open it and ask its agent to take the handoff. No session was interrupted.')
        executable(requested or selected(f))
        f.with_suffix('.take').write_text(str(target) + '\n')
    command = str(Path(__file__).with_name('work'))
    args = [command, 'open', stream]
    if requested:
        args += ['--agent', requested]
    print('Opening Work to prepare the handoff for ' + stream + '.', flush=True)
    os.execv(command, args)

def main():
    try:
        os.umask(0o077)
        p = argparse.ArgumentParser()
        p.add_argument('action', choices=('prompt', 'build', 'context', 'configure', 'run', 'take'))
        p.add_argument('role', choices=('studio', 'work'))
        p.add_argument('stream', nargs='?')
        p.add_argument('--agent', choices=AGENTS)
        p.add_argument('--task-file', help=argparse.SUPPRESS)
        p.add_argument('--resume', nargs='?', const='', default=None)
        p.add_argument('--once', action='store_true')
        p.add_argument('--take-handoff', action='store_true')
        a = p.parse_args()
        if (a.resume is not None or a.once or a.take_handoff or a.task_file) and a.action != 'run':
            p.error('--resume, --once and --take-handoff are supported with run only')
        if a.take_handoff and (a.role != 'work' or a.resume is not None):
            p.error('--take-handoff requires a new Work chat')
        if a.resume and a.resume.startswith('-'):
            p.error('invalid conversation ID')
        root = root_at()
        stream = slug(a.stream) if a.stream else current(root)
        if a.action == 'take':
            if a.role != 'work':
                fail('take is a Work command')
            take_work(root, stream, a.agent)
        elif a.action == 'configure':
            configure(root, stream, a.role, a.agent)
        else:
            root = checkout(root, stream)
            if a.action == 'prompt':
                print(prompt(root, stream, a.role))
            elif a.action == 'build':
                build(root, stream)
            elif a.action == 'context':
                context(root, stream)
            else:
                return run_agent(root, stream, a.role, a.agent, a.resume, a.once, a.take_handoff, a.task_file)
    except (RuntimeError, OSError, ValueError, sp.CalledProcessError) as exc:
        sys.exit('repo-agent: ' + str(exc))


if __name__ == '__main__':
    sys.exit(main())
