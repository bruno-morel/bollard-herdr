#!/usr/bin/env python3
"""Repository-scoped native panels: safe file editing and reported agent telemetry."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess as sp
import sys
import tempfile
BIN=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('panel_review',BIN/'repo-review.py');R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)

def root():return Path(R.git('.', 'rev-parse','--show-toplevel')).resolve()
def file_data(path):
    r=root();p=R.safe(r,path)
    if not p.is_file() or p.stat().st_size>100000:raise RuntimeError('Native editing supports text files up to 100 KB')
    raw=p.read_bytes()
    if b'\0' in raw:raise RuntimeError('Binary file; use a suitable external editor')
    text=raw.decode('utf-8')
    return dict(root=str(r),path=path,text=text,digest=hashlib.sha256(raw).hexdigest())
def save(path,digest,text):
    if not re.fullmatch('[0-9a-f]{64}',digest):raise RuntimeError('Missing original file revision')
    if '\0' in text or len(text.encode())>100000:raise RuntimeError('Text exceeds the 100 KB editor limit')
    r=root();p=R.safe(r,path);before=file_data(path)
    if before['digest']!=digest:raise RuntimeError('File changed on disk. Your edit is retained; compare it before reloading. Nothing was overwritten.')
    mode=stat.S_IMODE(p.stat().st_mode)
    fd,tmp=tempfile.mkstemp(prefix='.'+p.name+'.edit-',dir=p.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='') as f:f.write(text);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,mode)
        if file_data(path)['digest']!=digest:raise RuntimeError('File changed while saving. Nothing was overwritten.')
        os.replace(tmp,p)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return file_data(path)

def terminal(address):
    if not re.fullmatch(r't[0-9a-z]+',address):raise RuntimeError('Expected a local terminal ID')
    p=sp.run(['hc','get',address,'--json'],capture_output=True,text=True,timeout=10)
    if p.returncode:raise RuntimeError(p.stderr.strip())
    row=json.loads(p.stdout);where=(row.get('labels') or {}).get('repo-tools.checkout') or row.get('cwd')
    if not where or not os.path.samefile(where,root()):raise RuntimeError('Terminal belongs to another checkout')
    return row

def metadata(address):
    row=terminal(address);labels=row.get('labels') or {};provider=labels.get('repo-tools.agent')
    report=row.get('reported') or {};report=report if isinstance(report,dict) else {}
    model=report.get('model');model=(model.get('display_name') or model.get('id')) if isinstance(model,dict) else model
    result=dict(model=model if isinstance(model,str) else None,reasoning=report.get('reasoning_effort') or report.get('effort'),provider=provider,reported_at=None,context=None,quota=None,compactions=None,note='No exact conversation telemetry available. No quotas or progress are inferred.')
    if provider!='codex':return result
    # Match an exact resume UUID, or a single session whose PID matches this process tree.
    argv=row.get('argv') or [];session=None
    if '--resume-id' in argv:session=argv[argv.index('--resume-id')+1]
    home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    if session and re.fullmatch('[0-9a-f-]{36}',session):candidates=list((home/'sessions').glob('*/*/*/*'+session+'*.jsonl'))
    else:
        # Use the live Codex process's open rollout file after a resume: session_meta
        # records the original PID, which no longer identifies the running process.
        proc=sp.check_output(['ps','-axo','pid=,ppid=,comm='],text=True,timeout=5)
        records=[line.split(None,2) for line in proc.splitlines() if len(line.split(None,2))==3]
        depth={row.get('pid'):0}
        for _ in range(32):
            new={int(p):depth[int(parent)]+1 for p,parent,cmd in records if int(parent) in depth and int(p) not in depth}
            if not new:break
            depth.update(new)
        pids=set(depth);live=[int(p) for p,parent,cmd in records if int(p) in depth and Path(cmd).name=='codex']
        candidates=[]
        if live:
            nearest=min(depth[p] for p in live);live=[p for p in live if depth[p]==nearest]
            try:
                opened=sp.run(['lsof','-a','-p',','.join(map(str,live)),'-Fn'],capture_output=True,text=True,timeout=5)
                folder=(home/'sessions').resolve()
                for line in opened.stdout.splitlines():
                    if not line.startswith('n') or not line.endswith('.jsonl'):continue
                    f=Path(line[1:]).resolve()
                    if folder in f.parents and f.is_file():candidates.append(f)
                candidates=list(set(candidates))
            except (OSError,sp.SubprocessError):pass
        if not candidates:
            # Fallback remains exact-PID matching, never a guess based on folder/latest.
            for f in sorted((home/'sessions').glob('*/*/*/*.jsonl'),reverse=True)[:200]:
                try:
                    with f.open('rb') as h:first=json.loads(h.readline(64000))
                    payload=first.get('payload') or {}
                    if payload.get('process_id') in pids or payload.get('pid') in pids:candidates.append(f)
                except (OSError,ValueError):pass
    if len(candidates)!=1:return result
    f=candidates[0];event=None;turn=None;compactions=0
    # Bounded scan. Context values describe the last completed request, not a live estimate.
    size=f.stat().st_size;limit=16_000_000
    with f.open('rb') as h:
        h.seek(max(0,size-limit))
        if size>limit:h.readline()
        for line in h:
            if len(line)>2_000_000:continue
            try:r=json.loads(line)
            except ValueError:continue
            if r.get('type')=='compacted':compactions+=1
            if r.get('type')=='turn_context':turn=r
            if r.get('type')=='event_msg' and (r.get('payload') or {}).get('type')=='token_count':event=r
    if turn:
        details=turn.get('payload') or {};settings=(details.get('collaboration_mode') or {}).get('settings') or {}
        result.update(model=details.get('model') or settings.get('model') or result.get('model'),reasoning=details.get('effort') or details.get('reasoning_effort') or settings.get('reasoning_effort') or result.get('reasoning'),model_reported_at=turn.get('timestamp'))
    if not event:return result
    payload=event['payload'];info=payload.get('info') or {};last=info.get('last_token_usage') or {}
    result.update(reported_at=event.get('timestamp'),session=session or f.stem[-36:],context=dict(input=last.get('input_tokens'),cached=last.get('cached_input_tokens'),output=last.get('output_tokens'),window=info.get('model_context_window')),quota=payload.get('rate_limits'),compactions=compactions,compactions_partial=size>limit,note='Codex reported snapshot for this exact conversation. Context is the last request; quota can be stale while idle.')
    return result

def main():
    p=argparse.ArgumentParser(description='Repository-scoped native panel support; read-only unless save is explicitly selected.')
    p.add_argument('action',choices=['read','save','metadata','streams']);p.add_argument('value',nargs='?');p.add_argument('--digest');p.add_argument('--text')
    a=p.parse_args()
    if a.action=='read':out=file_data(a.value)
    elif a.action=='save':out=save(a.value,a.digest or '',a.text or '')
    elif a.action=='metadata':out=metadata(a.value)
    else:
        r=root();rows=R.git(r,'worktree','list','--porcelain','-z',raw=True).split(b'\0\0');out=[]
        for row in rows:
            d=dict(x.split(b' ',1) for x in row.split(b'\0') if b' ' in x)
            branch=os.fsdecode(d.get(b'branch',b''));path=os.fsdecode(d.get(b'worktree',b''))
            if branch.startswith('refs/heads/codex/'):out.append(dict(stream=branch[17:],cwd=path,branch=branch[11:]))
    print(json.dumps(out))
if __name__=='__main__':
    try:main()
    except (RuntimeError,OSError,ValueError,sp.SubprocessError) as e:sys.exit('repo-panel: '+str(e))
