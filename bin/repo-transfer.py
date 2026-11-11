#!/usr/bin/env python3
"""Preview/copy stream files into a new stream based on another repository."""
import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import subprocess as sp
import sys

BIN = Path(__file__).resolve().parent
DIRS = ('product/ideas product/research product/planning product/decisions '
        'brand/strategy brand/briefs brand/prompts brand/references '
        'marketing/briefs marketing/copy marketing/campaigns '
        'assets/projects presentations handoffs').split()
GUIDE = '''# Repository workflow

Persistent plans, research, decisions, marketing copy and handoffs belong in docs/.
Use docs/product/, docs/brand/, docs/marketing/, docs/assets/projects/ and
 docs/presentations/ as appropriate. Stream handoffs belong in docs/handoffs/<stream>/.
Temporary, intermediate and large generated files belong in ignored scratch/.
Keep credentials, machine state and session metadata outside this repository.

The launcher states the session role explicitly:
- STUDIO means planning and creative work. Do not implement application code unless asked.
- WORK means implementation. Read the stream handoff, inspect the code, and validate changes.

In both roles, check Git status, preserve existing changes, stay on the assigned
branch/worktree, and coordinate before editing files another agent is changing.
Existing repository-specific instructions remain applicable. If they conflict
with this workflow, surface the conflict rather than replacing them.
'''

def fail(message):
    raise RuntimeError(message)

def git(root, *args, check=True):
    p = sp.run(['git', '-C', str(root), *args], capture_output=True)
    if check and p.returncode:
        fail(p.stderr.decode(errors='replace').strip() or 'Git command failed')
    return p.stdout if check else p

def root_at(path):
    if git(path, 'rev-parse', '--is-inside-work-tree').strip() != b'true':
        fail('run inside a Git-controlled source tree')
    return Path(os.fsdecode(git(path, 'rev-parse', '--show-toplevel').strip())).resolve()

def common(root):
    p = Path(os.fsdecode(git(root, 'rev-parse', '--git-common-dir').strip()))
    return (root / p).resolve()

def safe(root, relative):
    p = PurePosixPath(relative)
    if p.is_absolute() or not p.parts or any(x in ('.', '..', '.git') for x in p.parts):
        fail('invalid relative path: ' + relative)
    current = root
    for part in p.parts:
        if current.exists() and not current.is_dir():
            fail("expected directory: " + str(current))
        current /= part
        if current.is_symlink():
            fail('symlink is not supported: ' + str(current))
    return current

def layout(root, apply=False, preserve_existing=False):
    """Check all required paths before creating any of them."""
    dirs = ['docs', 'scratch'] + ['docs/' + x for x in DIRS]
    for rel in dirs:
        p = safe(root, rel)
        if p.exists() and not p.is_dir():
            fail('expected directory: ' + str(p))
    for rel in ['AGENTS.md', 'CLAUDE.md', '.gitignore', 'docs/REPO-WORKFLOW.md']:
        p = safe(root, rel)
        if p.exists() and not p.is_file():
            fail('expected regular file: ' + str(p))
    if git(root, 'ls-files', '--', 'scratch').strip():
        fail('scratch contains tracked files; relocate or untrack them first')
    guide = root / 'docs/REPO-WORKFLOW.md'
    if not preserve_existing and guide.exists() and guide.read_text() != GUIDE:
        fail('docs/REPO-WORKFLOW.md already exists with different content; preserve and reconcile it first')
    marker = '\n<!-- repo-tools workflow -->\n'
    for name in ['AGENTS.md', 'CLAUDE.md']:
        p = root / name
        old = p.read_text() if p.exists() else ''
        if marker not in old:
            if apply:
                p.write_text(old + marker + '\nRead docs/REPO-WORKFLOW.md for the shared planning and implementation workflow.\n')
    if apply:
        for rel in dirs:
            (root / rel).mkdir(parents=True, exist_ok=True)
        guide = root / 'docs/REPO-WORKFLOW.md'
        if not guide.exists():
            guide.write_text(GUIDE)
        ignore = root / '.gitignore'
        old = ignore.read_text() if ignore.exists() else ''
        if '/scratch/' not in old.splitlines():
            ignore.write_text(old + '\n# Temporary and large generated assets\n/scratch/\n')
        if git(root, 'check-ignore', '--no-index', '-q', 'scratch/.probe', check=False).returncode:
            fail('scratch is not ignored; inspect Git ignore rules')

def transfer(a):
    here = root_at('.')
    dest = root_at(a.destination)
    if common(here) == common(dest):
        fail('source and destination must be different repositories')
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', a.stream):
        fail('use the exact stream slug, for example marketing-plan')
    branch = 'codex/' + a.stream
    entries = git(here, 'worktree', 'list', '--porcelain', '-z').split(b'\0\0')
    sources = []
    for entry in entries:
        fields = dict(x.split(b' ', 1) for x in entry.split(b'\0') if b' ' in x)
        if fields.get(b'branch') == ('refs/heads/' + branch).encode():
            sources.append(Path(os.fsdecode(fields[b'worktree'])))
    if len(sources) != 1:
        fail('source stream must have one existing worktree; open/recover it first')
    src = root_at(sources[0])
    if git(src, 'diff', '--name-only', '--diff-filter=U').strip():
        fail('resolve source merge conflicts first')
    if git(dest, 'status', '--porcelain').strip():
        fail('destination checkout must be clean; commit or stash its changes first')
    if git(dest, 'show-ref', '--verify', '--quiet', 'refs/heads/' + branch, check=False).returncode == 0:
        fail('destination stream already exists; choose a different destination or resolve it first')
    if git(dest, 'show-ref', '--verify', '--quiet', 'refs/remotes/origin/' + branch, check=False).returncode == 0:
        fail('destination has a cached remote stream of the same name; resolve it first')
    dest_branch = git(dest, 'symbolic-ref', '--quiet', '--short', 'HEAD').decode().strip()
    if dest_branch not in ('main', 'master'):
        fail('run against the destination main/master checkout')
    tip = git(dest, 'rev-parse', 'HEAD').decode().strip()
    base = a.source_base
    if base is None:
        for ref in ('refs/remotes/origin/main', 'refs/heads/main', 'refs/heads/master'):
            if git(src, 'rev-parse', '--verify', ref, check=False).returncode == 0:
                base = ref
                break
    if base is None:
        fail('cannot find source base; supply --source-base <ref>')
    ancestor = git(src, 'merge-base', 'HEAD', base).decode().strip()
    changed = git(src, 'diff', '--name-only', '--no-renames', '-z', ancestor, '--', 'docs')
    untracked = git(src, 'ls-files', '--others', '--exclude-standard', '-z', '--', 'docs')
    names = set(os.fsdecode(x) for x in (changed + untracked).split(b'\0') if x)
    packet = 'docs/handoffs/' + a.stream
    handoff = safe(src, packet)
    if handoff.exists() and not handoff.is_dir():
        fail('source handoff is not a directory')
    if handoff.exists():
        names.update(str(p.relative_to(src)) for p in handoff.rglob('*') if not p.is_dir() or p.is_symlink())
    for rel in a.include:
        p = safe(src, rel)
        if not p.exists():
            fail('included path does not exist: ' + rel)
        names.update(str(f.relative_to(src)) for f in ([p] if p.is_file() else p.rglob('*')) if not f.is_dir() or f.is_symlink())
    names.discard(packet + '/branch.txt')
    names.discard('docs/REPO-WORKFLOW.md')
    # Never import handoffs belonging to other streams.
    names = {n for n in names if not n.startswith('docs/handoffs/') or n.startswith(packet + '/')}
    for reserved in ('transfer.md', 'implementation.md'):
        if safe(dest, packet + '/' + reserved).exists():
            fail('destination handoff already has ' + reserved)
    if packet + '/transfer.md' in names:
        fail('source already has transfer.md; reconcile the prior transfer first')
    copies = {}
    originals = {}
    skipped = []
    for rel in sorted(names):
        if any(x.startswith('.env') or x in ('.git', '.local', '.codex', '.claude', '.cursor', 'node_modules') for x in PurePosixPath(rel).parts) or rel in ('AGENTS.md', 'CLAUDE.md', '.gitignore'):
            fail('runtime/configuration path cannot be transferred: ' + rel)
        path = safe(src, rel)
        if not path.exists():
            skipped.append(rel)
            continue
        if not stat.S_ISREG(path.stat().st_mode):
            fail('only regular files can be copied: ' + rel)
        if path.stat().st_size > 50 * 1024 * 1024:
            fail('file exceeds 50 MiB; move large scratch assets separately: ' + rel)
        data = path.read_bytes()
        out = packet + '/original-implementation.md' if rel == packet + '/implementation.md' else rel
        existing = safe(dest, out)
        if existing.exists():
            if not existing.is_file() or existing.read_bytes() != data:
                fail('destination conflict: ' + out + '; nothing copied')
        if out in copies and copies[out][0] != data:
            fail('two selected files map to ' + out)
        copies[out] = (data, stat.S_IMODE(path.stat().st_mode))
        originals[rel] = data
    if not copies:
        fail('no transferable files found; use --include <relative-path> if needed')
    layout(dest)
    main = os.fsdecode(git(dest, 'worktree', 'list', '--porcelain', '-z').split(b'\0')[0][9:])
    target = Path(main + '-worktrees') / a.stream
    if target.exists() or target.is_symlink() or target.parent.is_symlink():
        fail('destination worktree path already exists or is a symlink: ' + str(target))
    if git(target.parent.parent, 'rev-parse', '--is-inside-work-tree', check=False).returncode == 0:
        fail('destination worktree parent is inside another repository')
    runtime = Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state'))).resolve() / 'repo-tools'
    for root in (src, dest, target):
        if runtime == root or root in runtime.parents:
            fail('runtime state must be outside all checkouts')
    if (runtime/'work'/hashlib.sha256(os.fsencode(common(dest))).hexdigest()[:16]/a.stream).exists():
        fail('destination runtime stream already exists; resolve it first')
    print('Source:      ' + str(src))
    print('Destination: ' + str(target))
    print('Branch:      ' + branch + ' from destination ' + dest_branch)
    print('Files:')
    for rel in copies:
        print('  ' + rel)
    for rel in skipped:
        print('  OMIT DELETION: ' + rel)
    print('Add/verify docs hierarchy, scratch ignore, AGENTS.md and CLAUDE.md guidance.')
    print('Source preserved. No commits, pushes, Docker starts or session moves.')
    if not a.apply:
        print('Preview only. Pause the source agent, then repeat with --apply.')
        return
    for rel, data in originals.items():
        if safe(src, rel).read_bytes() != data:
            fail('source changed during preview; retry after pausing the agent')
    if git(dest, 'rev-parse', 'HEAD').decode().strip() != tip or git(dest, 'status', '--porcelain').strip():
        fail('destination changed during preview; retry')
    target.parent.mkdir(parents=True, exist_ok=True)
    git(dest, 'worktree', 'add', '-b', branch, str(target), tip)
    print('Created ' + str(target) + '; this path is retained if a later step fails.', flush=True)
    for rel, (data, mode) in copies.items():
        path = safe(target, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
    layout(target, apply=True)
    handoff = target / packet
    handoff.mkdir(parents=True, exist_ok=True)
    (handoff/'branch.txt').write_text(branch + '\n')
    note = ('# Transferred stream\n\nSource checkout: ' + str(src) + '\n\n'
            'Destination checkout: ' + str(target) + '\n\n'
            'Branch: ' + branch + '\n\n'
            'These files are a snapshot, not a migrated agent conversation. Read the destination\n'
            'AGENTS.md and CLAUDE.md first. Source repository paths, architecture and commands\n'
            'in copied documents are historical context; verify them against this repository.\n'
            'Review copied material and summarize decisions and remaining tasks before continuing.\n\n'
            '## Copied files\n\n' + ''.join('- `' + x + '`\n' for x in copies))
    for name, content in [('transfer.md', note), ('implementation.md', note)]:
        p = handoff / name
        if p.exists():
            fail('reserved transfer file already exists: ' + str(p))
        p.write_text(content)
    for name, content in {
        'brief.md': note,
        'decisions.md': '# Decisions\n\nReview the transferred documents and record confirmed decisions here.\n',
        'acceptance.md': '# Acceptance criteria\n\n- [ ] Review and confirm the transferred scope for this repository.\n',
        'references.md': '# References\n\nRead transfer.md and the copied files listed there.\n',
    }.items():
        if not (handoff/name).exists():
            (handoff/name).write_text(content)
    sp.run([str(BIN/'work'), 'prepare', a.stream], cwd=dest, check=True)
    print('\nReady to review: ' + str(target))
    print('Then: cd ' + shlex.quote(str(target)) + ' && studio open ' + a.stream)

try:
    if len(sys.argv) == 3 and sys.argv[1] == 'init':
        layout(root_at(sys.argv[2]), apply=True, preserve_existing=True)
    else:
        p = argparse.ArgumentParser(description=__doc__)
        p.add_argument('stream')
        p.add_argument('destination')
        p.add_argument('--apply', action='store_true')
        p.add_argument('--include', action='append', default=[], metavar='RELATIVE_PATH')
        p.add_argument('--source-base', help='base ref used to identify source documentation changes')
        transfer(p.parse_args())
except (RuntimeError, OSError, ValueError, sp.CalledProcessError) as exc:
    prefix = 'repo-init' if len(sys.argv) > 1 and sys.argv[1] == 'init' else 'transfer'
    sys.exit(prefix + ': ' + str(exc))

# Preserve existing guidance during initialization v1
