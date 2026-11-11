#!/usr/bin/env python3
"""Safe provider connection summaries, interactive sign-in and reported quota capture."""
from urllib.parse import urlparse, parse_qs
import argparse, concurrent.futures, fcntl, json, math, os, re, shlex, shutil, selectors, subprocess as sp, sys, time, uuid
from repo_state import write_json
from pathlib import Path
from repo_claude_usage import refresh as refresh_claude_usage
PROVIDERS=('codex','claude','cursor','gemini')
def fail(s):raise RuntimeError(s)
def runtime():
    p=Path(os.environ.get('XDG_STATE_HOME',str(Path.home()/'.local/state'))).resolve()/'repo-tools/providers'
    r=sp.run(['git','worktree','list','--porcelain'],capture_output=True,text=True,timeout=3)
    for line in r.stdout.splitlines():
        if line.startswith('worktree '):
            t=Path(line[9:]).resolve()
            if p==t or t in p.parents:fail('account state must be outside all worktrees')
    return p

def read(p):
    try:return json.loads(p.read_text())
    except FileNotFoundError:return {}
def write(p,data):
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_json(p, data, indent=2)
def binary(provider):return next((shutil.which(n) for n in (('cursor-agent','agent') if provider=='cursor' else (provider,)) if shutil.which(n)),None)
def normalize_codex_limits(result):
    raw=(result.get('rateLimitsByLimitId') or {}).get('codex') or result.get('rateLimits') or {};windows={}
    for name in ('primary','secondary'):
        w=raw.get(name) or {};used=w.get('usedPercent')
        if type(used) in (int,float) and math.isfinite(used) and 0<=used<=100:
            windows[name]={'used_percent':used,'window_minutes':w.get('windowDurationMins'),'resets_at':w.get('resetsAt')}
    return {'quota':windows or None,'plan':raw.get('planType'),'reported_at':time.time()}

def codex_limits(executable):
    # The documented account-only RPC. Never create/resume a thread or turn.
    proc=sp.Popen([executable,'app-server','--listen','stdio://'],stdin=sp.PIPE,stdout=sp.PIPE,stderr=sp.DEVNULL,bufsize=0,cwd=Path.home())
    selector=selectors.DefaultSelector();selector.register(proc.stdout,selectors.EVENT_READ);buf=b'';deadline=time.monotonic()+9
    def send(v):proc.stdin.write((json.dumps(v)+'\n').encode());proc.stdin.flush()
    try:
        send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'repo_tools_usage','title':'Studio Work Usage','version':'1.0'}}})
        while time.monotonic()<deadline:
            if not selector.select(max(0,deadline-time.monotonic())):break
            chunk=os.read(proc.stdout.fileno(),65536)
            if not chunk:break
            buf+=chunk
            if len(buf)>1048576:fail('Unexpected account response')
            while b'\n' in buf:
                line,buf=buf.split(b'\n',1)
                try:message=json.loads(line)
                except ValueError:continue
                if message.get('id')==1:
                    if 'error' in message:fail('Account interface unavailable')
                    send({'method':'initialized'});send({'id':2,'method':'account/rateLimits/read'})
                if message.get('id')==2:
                    if 'error' in message:fail('Account limits unavailable')
                    return normalize_codex_limits(message.get('result',{}))
        fail('Account limit check timed out')
    finally:
        selector.close();proc.stdin.close()
        try:proc.wait(timeout=.5)
        except sp.TimeoutExpired:
            proc.terminate()
            try:proc.wait(timeout=2)
            except sp.TimeoutExpired:proc.kill();proc.wait()
        proc.stdout.close()

def auth(provider):
    b=binary(provider);out={'provider':provider,'installed':bool(b),'connected':None}
    if not b:return out
    args={'codex':['login','status'],'claude':['auth','status'],'cursor':['status'],'gemini':None}[provider]
    if args is None:
        out['note']='Open Gemini to verify sign-in. Subscription limits are not exposed here.';return out
    try:
        p=sp.run([b,*args],capture_output=True,text=True,timeout=7)
        if provider=='claude':
            d=json.loads(p.stdout);out.update(connected=d.get('loggedIn') is True,plan=d.get('subscriptionType'),method=d.get('authMethod'))
        else:
            text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',p.stdout+'\n'+p.stderr).lower()
            if any(s in text for s in ('not logged','not authenticated','logged out')):out['connected']=False
            elif 'logged in' in text or 'authenticated' in text:out['connected']=True
            elif p.returncode:out['note']='Sign-in status unavailable. Open the account to check.'
    except (sp.SubprocessError,OSError,ValueError):out['note']='Sign-in check unavailable; existing credentials were left unchanged.'
    if provider=='codex' and out.get('connected'):
        try:out.update(codex_limits(b))
        except (RuntimeError,OSError,ValueError,sp.SubprocessError):out['note']='Account limit check unavailable; use the provider usage page or refresh.'
    return out

def status(force=False):
    folder=runtime();cache=read(folder/'status.json')
    if force or time.time()-cache.get('checked',0)>120:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(auth,PROVIDERS))
        cache={'checked':time.time(),'providers':rows};write(folder/'status.json',cache)
    for p in cache.get('providers',[]):
        if p['provider']=='claude':
            q,check={},{}
            if p.get('connected') and p.get('method')=='claude.ai':
                q,check=refresh_claude_usage(binary('claude'),folder)
            p['quota']=q.get('windows');p['reported_at']=q.get('reported_at')
            p['quota_source']=q.get('source');p['quota_check']=check
            settings=read(claude_settings());p['meters_enabled']=(settings.get('statusLine') or {}).get('command')==capture_command()
    return cache

def claude_settings():return Path(os.environ.get('CLAUDE_CONFIG_DIR',str(Path.home()/'.claude')))/'settings.json'
def capture_command():return shlex.join([sys.executable,str(Path(__file__).resolve()),'_capture'])
def enable_meters():
    folder=runtime();folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (folder/'settings.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        p=claude_settings()
        if p.is_symlink():fail('Claude settings is a symlink; configure the status-line command manually.')
        s=read(p);old=s.get('statusLine')
        if old and (not isinstance(old,dict) or old.get('type')!='command'):fail('Unrecognized status-line configuration; nothing changed.')
        if old and old.get('command')==capture_command():return {'message':'Claude quota capture is already enabled.'}
        write(folder/'claude-statusline.json',{'previous':old})
        s['statusLine']={**(old or {}),'type':'command','command':capture_command()};write(p,s)
    return {'message':'Claude meters enabled. The next interactive Claude session can report account limits after its next response. Existing status-line output is preserved. No model call was made.'}

def capture():
    raw=sys.stdin.read(1048576);folder=runtime();data=json.loads(raw);limits=data.get('rate_limits') or {};windows={}
    for name in ('five_hour','seven_day'):
        d=limits.get(name) or {};used=d.get('used_percentage');reset=d.get('resets_at')
        if type(used) in (int,float) and math.isfinite(used) and 0<=used<=100:
            windows[name]={'used_percent':used,'resets_at':reset if type(reset) in (int,float) and math.isfinite(reset) and reset>0 else None}
    if windows:write(folder/'claude-quota.json',{'windows':windows,'reported_at':time.time(),'source':'claude-statusline'})
    old=read(folder/'claude-statusline.json').get('previous') or {};cmd=old.get('command')
    if cmd and cmd!=capture_command():
        p=sp.run(cmd,shell=True,input=raw,capture_output=True,text=True,timeout=2);print(p.stdout,end='')
    else:
        print(' · '.join(('5h' if n=='five_hour' else '7d')+': '+str(round(w['used_percent']))+'% used' for n,w in windows.items()) or 'Claude · quota awaiting provider report')

def extract_login_link(screen,provider="claude"):
    # hc read returns the original logical line: never copy a wrapped screen selection.
    clean=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '',screen)
    candidates=re.findall(r'https://[^\s<>"\x1b]+',clean)
    for url in candidates:
        try:d=urlparse(url);q=parse_qs(d.query);port=d.port
        except ValueError:continue
        if provider=='cursor':
            if d.scheme!='https' or d.hostname!='cursor.com' or d.username or d.password or port not in (None,443):continue
            if d.path!='/loginDeepControl' or not all(q.get(k) for k in ('challenge','uuid')):continue
            if any(ch.isspace() for ch in url):continue
            return url
        if d.hostname not in ('claude.com','claude.ai') or d.username or d.password or port not in (None,443):continue
        if d.path not in ('/cai/oauth/authorize','/oauth/authorize'):continue
        if not all(q.get(k) for k in ('client_id','redirect_uri','state','code_challenge')):continue
        target=q['redirect_uri'][0]
        if target not in ('https://platform.claude.com/oauth/code/callback','https://console.anthropic.com/oauth/code/callback'):continue
        if any(ch.isspace() for ch in url):continue
        return url
    fail('No intact '+provider.title()+' sign-in link is available yet. Wait for the login prompt, or request a fresh sign-in.')

def login_link(address,provider=None):
    if not re.fullmatch(r't[a-z0-9]+',address or ''):fail('Choose a local account terminal')
    p=sp.run(['hc','get',address,'--json'],capture_output=True,text=True,timeout=6)
    if p.returncode:fail('Account terminal is unavailable; sign in again')
    row=json.loads(p.stdout)
    actual=row.get('labels',{}).get('repo-tools.account')
    if row.get('state')!='live' or actual not in ('claude','cursor') or (provider and provider!=actual):fail('This is not a matching live account terminal')
    p=sp.run(['hc','read',address],capture_output=True,text=True,timeout=6)
    if p.returncode:fail('Cannot read the sign-in link; retry shortly')
    return {'url':extract_login_link(p.stdout,actual),'provider':actual}

def login_unlocked(provider,lead=None,fresh=False):
    b=binary(provider)
    if not b:fail(provider+' CLI is not installed; use its install guide first')
    # A successful SSH/terminal login is the same account used by Herdr.
    # Do not reopen an old OAuth attempt once this machine is authenticated.
    if provider in ('claude','cursor') and not fresh:
        account=auth(provider)
        if account.get('connected') and (provider=='cursor' or account.get('method')=='claude.ai'):
            plan=account.get('plan')
            return {'connected':True,'provider':provider,'plan':plan,
                    'message':provider.title()+(' '+plan.title() if isinstance(plan,str) else '')+' is already connected on this machine. No new sign-in is needed.'}
    args={'codex':['login'],'claude':['auth','login'],'cursor':['login'],'gemini':[]}[provider]
    # A dedicated account pane. No prompt sent and no lead process interrupted.
    p=sp.run(['hc','ls','--json'],capture_output=True,text=True,timeout=8)
    if p.returncode:fail('cannot inspect account terminals')
    for item in json.loads(p.stdout).get('terminals',[]):
        if fresh or '/' in item['address'] or item.get('state')!='live':continue
        if not (item.get('name','').startswith(provider+'-account-') or item.get('labels',{}).get('repo-tools.account')==provider):continue
        got=sp.run(['hc','get',item['address'],'--json'],capture_output=True,text=True,timeout=5)
        if got.returncode:continue
        row=json.loads(got.stdout)
        if row.get('labels',{}).get('repo-tools.account')!=provider:continue
        pid=row.get('pid')
        if not isinstance(pid,int):continue
        proc=sp.run(['ps','-p',str(pid),'-o','comm='],capture_output=True,text=True,timeout=3)
        # A kept recovery shell is not a sign-in process.
        if Path(proc.stdout.strip()).name not in ('zsh','bash','sh','fish',''):
            return {'terminal':row['address'],'reused':True}
    labels={'repo-tools.role':'account','repo-tools.account':provider,'herdr.space':'accounts','herdr.tab':provider+'-account'}
    if lead:
        if not re.fullmatch(r't[a-z0-9]+',lead):fail('invalid lead terminal')
        p=sp.run(['hc','get',lead,'--json'],capture_output=True,text=True,timeout=6)
        if p.returncode:fail('cannot locate the selected stream terminal')
        l=json.loads(p.stdout).get('labels',{});labels['herdr.space']=l.get('herdr.space','accounts');labels['herdr.tab']=labels['herdr.space']+'-'+provider+'-account'
    argv=['hc','run','--bg','--keep','--no-parent','--no-notify','--name',provider+'-account-'+uuid.uuid4().hex[:6],'--cwd',str(Path.home())]
    for k,v in labels.items():argv+=['--label',k+'='+v]
    argv+=['--','env','NO_OPEN_BROWSER=1',b,*args]
    p=sp.run(argv,capture_output=True,text=True,timeout=15)
    if p.returncode:fail('account launch did not return success; inspect Herdr before retrying')
    p=sp.run(['hc','get',argv[argv.index('--name')+1],'--json'],capture_output=True,text=True,timeout=5)
    if p.returncode:fail('account launched; inspect Herdr terminals for its status')
    address=json.loads(p.stdout).get('address')
    if not address:fail('account launched but returned an unfamiliar response; inspect Herdr terminals')
    return {'terminal':address,'reused':False}

def login(provider,lead=None,fresh=False):
    folder=runtime();folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (folder/(provider+'-login.lock')).open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:fail('Account sign-in is already opening. Wait a moment, then click again.')
        return login_unlocked(provider,lead,fresh)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['status','connection','login','login-link','enable-meters','_capture']);p.add_argument('provider',nargs='?',choices=PROVIDERS);p.add_argument('--lead');p.add_argument('--terminal');p.add_argument('--fresh',action='store_true');p.add_argument('--force',action='store_true');a=p.parse_args()
    if a.action=='_capture':capture();return
    if a.action=='status':result=status(a.force)
    elif a.action=='login-link':result=login_link(a.terminal,a.provider)
    elif a.action=='enable-meters':result=enable_meters()
    elif not a.provider:fail('choose a provider')
    elif a.action=='connection':result=auth(a.provider)
    else:result=login(a.provider,a.lead,a.fresh)
    print(json.dumps(result))
if __name__=='__main__':
    os.umask(0o077)
    try:main()
    except (RuntimeError,OSError,ValueError,sp.SubprocessError) as e:
        if '_capture' not in sys.argv:sys.exit('repo-provider: '+str(e))
