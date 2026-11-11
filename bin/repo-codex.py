#!/usr/bin/env python3
from pathlib import Path
import hashlib
import json
import os
import subprocess as sp
import sys

if len(sys.argv) not in (2, 3) or sys.argv[1] not in ('studio', 'work'):
    sys.exit('Usage: repo-codex.py studio|work [--print-prompt]')
if len(sys.argv) == 3 and sys.argv[2] != '--print-prompt':
    sys.exit('Only --print-prompt is supported as an extra argument.')

role = sys.argv[1]

def git(*args):
    return sp.check_output(
        ['git', *args], stderr=sp.DEVNULL, text=True
    ).strip()

try:
    root = Path(git('rev-parse', '--show-toplevel')).resolve()
    os.chdir(root)
    branch = git('symbolic-ref', '--quiet', '--short', 'HEAD')
    common = Path(git('rev-parse', '--git-common-dir')).resolve()
except sp.CalledProcessError:
    sys.exit('Start inside a Git checkout with a checked-out branch.')

repo_id = hashlib.sha256(os.fsencode(common)).hexdigest()[:16]
state = Path(
    os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state'))
) / 'repo-tools/work' / repo_id

stream = None

# Match the checkout to its saved stream, rather than guessing from its name.
for record in state.glob('*/state.env'):
    values = sp.check_output([
        'zsh', '-c',
        'source "$1"; printf "%s\\0" "$WORKTREE_PATH" "$SLUG" "$BRANCH"',
        'read-state', str(record)
    ], text=True).split('\0')

    if Path(values[0]).resolve() == root:
        if stream is not None:
            sys.exit('Multiple stream records point to this checkout.')

        stream, expected = values[1:3]
        if not stream or Path(stream).name != stream or stream in ('.', '..'):
            sys.exit('Invalid stream name in runtime state.')

        if branch != expected:
            sys.exit(
                'Stream branch mismatch: expected '+expected+'; found '+branch
            )

packet = root/'docs/handoffs'/stream if stream else None

if packet:
    identity = packet/'branch.txt'
    if identity.exists() and identity.read_text().strip() != branch:
        sys.exit('Handoff branch does not match the current Git branch.')

    if role == 'work' and packet.exists():
        if not (packet/'codex-prompt.md').is_file():
            sys.exit('Build the handoff first: run studio handoff.')

role_rules = {
    'studio': """Your role is product planning and creative work.
The Studio section of repository guidance applies to this session.
Develop ideas, research, briefs, decisions, acceptance criteria and handoffs
under docs/. Use scratch/ for intermediate or large generated assets.
Do not implement application changes unless the user explicitly changes
your scope. After changing handoff sources, run studio handoff when the
user asks to prepare or update the handoff.""",

    'work': """Your role is implementation.
The Work section of repository guidance applies to this session.
Before implementing the user's task, read the matching handoff and its
codex-prompt.md when present. Inspect relevant code, follow acceptance
criteria, and run appropriate validation. Keep implementation and related
documentation on this stream. Report conflicts or missing product decisions."""
}

prompt = f"""SESSION ROLE: {role.upper()}
Checkout: {json.dumps(str(root))}
Stream: {json.dumps(stream) if stream else '(repository-wide session; no managed stream)'}
Expected Git branch: {json.dumps(branch)}
Handoff directory: {json.dumps(str(packet)) if packet else '(none selected)'}

{role_rules[role]}

Read AGENTS.md and any more specific applicable repository instructions.
Shared rules apply in both roles. The other role's section describes the other
session; it is not an instruction to switch your own role.

Use this checkout. Do not create a second worktree or switch branches as part
of this workflow. Check Git status and preserve existing changes. Another
agent may share these files, so coordinate before editing overlapping files.

Keep the role in this conversation; do not write a global current-mode file.
If there is no managed stream, do not invent a stream or handoff location.

For this startup message, inspect the repository guidance and relevant handoff
if present, briefly confirm your role, branch and readiness, then await the
user's task. Opening this pane alone does not request implementation or changes.
"""

if len(sys.argv) == 3:
    print(prompt)
else:
    os.execvp('codex', ['codex', '--cd', str(root), prompt])
