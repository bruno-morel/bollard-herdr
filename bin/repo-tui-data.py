#!/usr/bin/env python3
"""Bounded, read-only file and agent data for the terminal dashboard."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess as sp
import sys

LIMIT = 512*1024
DOCS = {'.md', '.markdown', '.mdown', '.mkd', '.txt'}
BIN = Path(__file__).resolve().parent

def run(argv, allowed=(0,), limit=LIMIT):
    with sp.Popen(argv, stdout=sp.PIPE, stderr=sp.PIPE) as p:
        # Git output can be large; stream only a bounded preview, then stop the reader.
        import threading
        timer = threading.Timer(20, p.kill)
        timer.start()
        try:
            out = p.stdout.read(limit+1)
            truncated = len(out)>limit
            if truncated: p.kill()
            _, err = p.communicate(timeout=5)
        finally: timer.cancel()
    if not truncated and p.returncode not in allowed:
        raise RuntimeError(err.decode(errors='replace').strip() or 'Read failed')
    return out[:limit], truncated

def git(*args, limit=8*1024*1024):
    out, truncated = run(['git', '--no-optional-locks', '--literal-pathspecs', '-c', 'core.fsmonitor=false', *args], limit=limit)
    if truncated: raise RuntimeError('Repository index is too large to list safely; narrow the checkout')
    return out

def root():
    p = Path(os.fsdecode(git('rev-parse', '--show-toplevel')).rstrip('\n')).resolve()
    if Path.cwd().resolve()!=p: raise RuntimeError('Use the selected checkout root')
    return p

def index(mode):
    r = root()
    changed = {}
    for item in git('status', '--porcelain=v1', '-z', '--no-renames', '--untracked-files=all').split(b'\0'):
        if item: changed[os.fsdecode(item[3:])] = item[:2].decode('ascii')
    paths = {os.fsdecode(p) for p in git('ls-files', '--cached', '--others', '--exclude-standard', '-z').split(b'\0') if p}
    rows = []
    for path in sorted(paths | set(changed)):
        if mode=='git' and path not in changed: continue
        if mode=='docs' and Path(path).suffix.lower() not in DOCS: continue
        rows.append(dict(path=path, changed=path in changed, status=changed.get(path,'')))
    return dict(root=str(r), files=rows[:20000], truncated=len(rows)>20000,
                branch=os.fsdecode(git('branch', '--show-current')).strip())

def safe_path(rel):
    r = root()
    p = Path(rel)
    if p.is_absolute() or '..' in p.parts or not p.parts: raise RuntimeError('Use a repository-relative file')
    q = r
    for part in p.parts:
        q /= part
        if q.is_symlink(): raise RuntimeError('Symlink previews are disabled')
    return q

def preview(mode, rel):
    q = safe_path(rel)
    if mode=='git':
        sections=[];truncated=False;remaining=LIMIT
        for title,flags in [('Staged',['--cached']),('Unstaged',[])]:
            out,cut=run(['git','--no-optional-locks','--literal-pathspecs','diff','--no-ext-diff','--no-textconv','--no-color',*flags,'--',rel],limit=remaining)
            if out:sections.append(title+'\n'+out.decode(errors='replace'))
            truncated=truncated or cut;remaining-=len(out)
            if remaining<=0:truncated=True;break
        if sections:return dict(path=rel,text='\n\n'.join(sections),truncated=truncated)
        # An untracked file has no HEAD diff. Show its complete proposed content.
    if not q.exists(): return dict(path=rel,text='File deleted. No current contents.',truncated=False)
    if not q.is_file(): raise RuntimeError('Select a regular file')
    with q.open('rb') as f: data=f.read(LIMIT+1)
    if b'\0' in data: return dict(path=rel,text='Binary file · use the desktop Files pane to open it.',truncated=False)
    return dict(path=rel,text=data[:LIMIT].decode('utf-8',errors='replace'),truncated=len(data)>LIMIT)

def hc(*args):
    r=sp.run(['hc',*args,'--json'],capture_output=True,text=True,timeout=15)
    if r.returncode: raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return json.loads(r.stdout)

def agents(lead):
    r=root()
    if not re.fullmatch('t[a-z0-9]+',lead): raise RuntimeError('Invalid terminal ID')
    parent=hc('get',lead)
    labels=parent.get('labels') or {}
    if not os.path.samefile(labels.get('repo-tools.checkout') or parent['cwd'],r):
        raise RuntimeError('Conversation belongs to another checkout')
    listing=hc('ls','--label','repo-tools.stream='+labels['repo-tools.stream']).get('terminals',[])
    rows=[]
    for entry in listing[:50]:
        row=parent if entry['address']==lead else hc('get',entry['address'])
        tags=row.get('labels') or {}
        if tags.get('repo-tools.repo')!=labels.get('repo-tools.repo'): continue
        if row.get('state')!='live': continue
        rows.append({k:row.get(k) for k in ('address','status','state','title','parent','labels','cwd')})
    return dict(agents=rows,lead=lead)

def main():
    os.environ['PATH']=os.pathsep.join([str(Path.home()/'.local/bin'),'/opt/homebrew/bin','/usr/local/bin',os.environ.get('PATH','/usr/bin:/bin')])
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['docs','files','git','preview','agents'])
    p.add_argument('value',nargs='?');p.add_argument('--mode',choices=['docs','files','git'],default='files')
    a=p.parse_args()
    if a.action=='preview': result=preview(a.mode,a.value or '')
    elif a.action=='agents': result=agents(a.value or '')
    else: result=index(a.action)
    print(json.dumps(result,ensure_ascii=True))

if __name__=='__main__':
    try: main()
    except (RuntimeError,OSError,ValueError,sp.SubprocessError) as exc: sys.exit('TUI data: '+str(exc))
