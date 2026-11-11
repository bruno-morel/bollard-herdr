#!/usr/bin/env python3
"""Preview and explicitly merge a recorded branch tip into the current stream."""
import argparse, fcntl, hashlib, importlib.util, json, os, re, subprocess as sp, sys, time, uuid
from pathlib import Path
BIN=Path(__file__).resolve().parent

def fail(message): raise RuntimeError(message)
def git(root,*args):
    p=sp.run(['git','--no-optional-locks','-C',str(root),*args],capture_output=True,text=True,timeout=20)
    if p.returncode: fail((p.stderr or p.stdout).strip())
    return p.stdout.rstrip('\n')
def read(path):
    try:return json.loads(path.read_text())
    except FileNotFoundError:return {}
def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(data));os.chmod(tmp,0o600);tmp.replace(path)
def trees(root):
    raw=git(root,'worktree','list','--porcelain','-z')
    return [dict(x.split(' ',1) for x in r.split('\0') if ' ' in x) for r in raw.split('\0\0') if r]
def context():
    try:root=Path(git(Path.cwd(),'rev-parse','--show-toplevel')).resolve()
    except RuntimeError:fail('run inside a Git-controlled source tree')
    branch=git(root,'symbolic-ref','--quiet','HEAD')
    if not re.fullmatch(r'refs/heads/codex/[a-z0-9]+(?:-[a-z0-9]+)*',branch):fail('select a Studio/Work stream checkout first')
    common=Path(git(root,'rev-parse','--git-common-dir'));common=(root/common).resolve()
    base=Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state'))).resolve()/'repo-tools'
    for tree in trees(root):
        p=Path(tree['worktree']).resolve()
        if base==p or p in base.parents:fail('runtime state must be outside all worktrees')
    key=hashlib.sha256(os.fsencode(common)).hexdigest()[:16];stream=branch[len('refs/heads/codex/'):]
    return root,branch,base,key,stream

def source_list(root):
    checked={t.get('branch'):t['worktree'] for t in trees(root)}
    rows=[]
    for line in git(root,'for-each-ref','--format=%(refname)%00%(objectname)%00%(symref)','refs/heads/','refs/remotes/').splitlines():
        ref,oid,sym=line.split('\0')
        if sym:continue
        rows.append({'ref':ref,'oid':oid,'label':ref.replace('refs/heads/','').replace('refs/remotes/',''),'worktree':checked.get(ref)})
    refs={r['ref'] for r in rows}
    try:default=git(root,'symbolic-ref','refs/remotes/origin/HEAD')
    except RuntimeError:default=None
    default=next((r for r in [default,'refs/remotes/origin/main','refs/heads/main','refs/remotes/origin/master','refs/heads/master'] if r in refs),None)
    return rows,default

def source(root,name):
    rows,default=source_list(root);name=default if name=='default' else name
    row=next((r for r in rows if r['ref']==name),None)
    if not row:fail('choose an existing branch from the source list')
    return row

def dirty(root):return git(root,'status','--porcelain=v1','--untracked-files=all')
def operation(root):
    for name in ('MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD','rebase-merge','rebase-apply','BISECT_LOG'):
        p=Path(git(root,'rev-parse','--git-path',name));p=p if p.is_absolute() else root/p
        if p.exists():return name
    return None

def preview(root,branch,name,fetch=False):
    row=source(root,name)
    if fetch:
        if not row['ref'].startswith('refs/remotes/'):fail('fetch is available for a remote branch; choose a remote source')
        tail=row['ref'][len('refs/remotes/'):];remote,remote_branch=tail.split('/',1)
        if remote not in git(root,'remote').splitlines():fail('remote is no longer configured')
        # No force, no tags, and no checkout/index changes. Fetch is explicit.
        git(root,'fetch','--no-tags','--no-recurse-submodules','--',remote,'refs/heads/'+remote_branch+':'+row['ref'])
        row=source(root,row['ref'])
    if git(root,'symbolic-ref','--quiet','HEAD')!=branch:fail('Checkout branch changed. Preview again.')
    head=git(root,'rev-parse','HEAD');blocks=[];changed=dirty(root)
    if row['ref']==branch:blocks.append('Source is the current branch.')
    if changed:blocks.append('Commit or resolve current changes before merging. Nothing will be stashed automatically.')
    op=operation(root)
    if op:blocks.append('Finish the current Git operation first: '+op)
    try:git(root,'merge-base',head,row['oid'])
    except RuntimeError:blocks.append('These branches do not share history.')
    ahead,behind=map(int,git(root,'rev-list','--left-right','--count',head+'...'+row['oid']).split())
    # Git's merge strategies do not consistently protect ignored files. Check
    # incoming paths explicitly, including file/directory prefix collisions.
    ignored=git(root,'ls-files','--others','--ignored','--exclude-standard','-z').split('\0')
    incoming_paths=git(root,'diff','--name-only','--diff-filter=ACMRT','-z',head+'...'+row['oid']).split('\0') if not any('history' in b for b in blocks) else []
    collisions=[p for p in ignored if p and any(q and (p==q or p.startswith(q+'/') or q.startswith(p+'/')) for q in incoming_paths)]
    if collisions:blocks.append('Move these ignored local assets before merging: '+', '.join(collisions[:10]))
    warnings=[]
    if row.get('worktree') and dirty(row['worktree']):warnings.append('Source worktree has uncommitted changes. Only its recorded commit will be merged.')
    if row['ref'].startswith('refs/remotes/') and not fetch:warnings.append('Using the last fetched remote tip. Fetch & preview to check the server.')
    return {'root':str(root),'branch':branch,'head':head,'source':row,'ahead':ahead,'incoming':behind,'kind':'up to date' if not behind else 'fast-forward' if not ahead else 'merge commit','blocked':blocks,'dirty':changed,'warnings':warnings,'commits':git(root,'log','--format=%h %s','-12',head+'..'+row['oid']),'diffstat':git(root,'diff','--stat',head+'...'+row['oid']) if not any('history' in b for b in blocks) else '', 'created':time.time()}

def same(a,b):
    try:return os.path.samefile(a,b)
    except (OSError,TypeError):return False

def ensure_idle(root,base,key,stream):
    # Workflow workers must never be rebased underneath their evidence.
    states=[(base/'agents'/key/stream/'workflow/state.json',('queued','preparing','implementing','fixing','reviewing')),
            (base/'review'/key/stream/'state.json',('preflight','reviewing')),
            (base/'tests'/key/stream/'state.json',('queued','running'))]
    for path,active in states:
        if read(path).get('state') in active:fail('A workflow, review or test run is active. Wait or pause it before updating this stream.')
    p=sp.run(['hc','ls','--json'],capture_output=True,text=True,timeout=8)
    if p.returncode:fail('Cannot verify Herdr agents are idle; no merge was attempted.')
    rows=json.loads(p.stdout).get('terminals',[]);idle_roles=set()
    from repo_process import agent_running
    for brief in rows:
        if '/' in brief['address']:continue
        labels=brief.get('labels',{})
        if not (same(brief.get('cwd'),root) or same(labels.get('repo-tools.checkout'),root)):continue
        p=sp.run(['hc','get',brief['address'],'--json'],capture_output=True,text=True,timeout=5)
        if p.returncode:fail('Cannot check a stream terminal; no merge was attempted.')
        row=json.loads(p.stdout);s=row.get('status') or {};s=s.get('state') if isinstance(s,dict) else s
        if row.get('state')!='live':continue
        if agent_running(row):
            if s not in ('idle','done'):fail('An agent is working or awaiting input. Finish its turn before updating this stream.')
            idle_roles.add(row.get('labels',{}).get('repo-tools.role'))
        elif s=='working':fail('A command is still working in this checkout.')
    # Locks also catch agent owners outside Herdr, including Zellij.
    for role in ('studio','work'):
        path=base/'agents'/key/stream/(role+'.lock')
        if path.exists():
            with path.open('a') as f:
                try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:
                    if role not in idle_roles:fail('A '+role+' agent outside a verified idle Herdr terminal owns this stream.')

def apply(root,branch,base,key,stream,token):
    if not re.fullmatch('[a-f0-9]{32}',token):fail('invalid preview token')
    folder=base/'sync'/key/stream;folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (folder/'apply.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        path=folder/(token+'.json');p=read(path)
        if not p or p.get('used') or time.time()-p['created']>900:fail('Preview expired or already used. Preview again.')
        if not same(p['root'],root) or p['branch']!=branch:fail('The selected checkout/branch changed. Preview again.')
        ensure_idle(root,base,key,stream)
        now=preview(root,branch,p['source']['ref'])
        if now['head']!=p['head'] or now['source']['oid']!=p['source']['oid']:fail('The current or source branch changed. Preview again.')
        if now['blocked']:fail(' '.join(now['blocked']))
        p['used']=True;write(path,p)
        # Native merge preserves shared history; refuse ignored-file overwrites too.
        result=sp.run(['git','-C',str(root),'merge','--ff','--no-edit','--no-overwrite-ignore',p['source']['oid']],capture_output=True,text=True,timeout=60,env={**os.environ,'GIT_MERGE_AUTOEDIT':'no'})
        return {'ok':result.returncode==0,'message':(result.stdout+result.stderr).strip(),'head':git(root,'rev-parse','HEAD'),'conflicts':git(root,'diff','--name-only','--diff-filter=U'),'note':'If conflicts remain, resolve them in this checkout before continuing. Nothing was pushed or reset.' if result.returncode else 'Review the result and rerun relevant checks before asking an agent to continue.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['sources','preview','apply']);p.add_argument('--source',default='default');p.add_argument('--fetch',action='store_true');p.add_argument('--token');p.add_argument('--json',action='store_true');a=p.parse_args()
    if a.fetch and a.action!='preview':fail('--fetch requires preview')
    root,branch,base,key,stream=context()
    if a.action=='sources':
        rows,default=source_list(root);out={'root':str(root),'branch':branch,'sources':[r for r in rows if r['ref']!=branch],'default':default}
    elif a.action=='preview':
        out=preview(root,branch,a.source,a.fetch);out['token']=uuid.uuid4().hex
        write(base/'sync'/key/stream/(out['token']+'.json'),out)
    else:out=apply(root,branch,base,key,stream,a.token or '')
    print(json.dumps(out,ensure_ascii=False,indent=2));return 0 if out.get('ok',True) else 2
if __name__=='__main__':
    os.umask(0o077)
    try:sys.exit(main())
    except (RuntimeError,OSError,ValueError,sp.SubprocessError) as e:sys.exit('repo-sync: '+str(e))
