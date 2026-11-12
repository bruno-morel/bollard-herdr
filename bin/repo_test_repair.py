"""One-click diagnosis and deferred repair; never write into a busy lead checkout."""
import os
import re
import sys
import time
import uuid

ACTIVE = ('launching', 'investigating', 'waiting')
SCHEMA = {'type':'object','additionalProperties':False,'properties':{
    'diagnosis':{'type':'string'}, 'limitations':{'type':'string'},
    'next_steps':{'type':'string'}},'required':['diagnosis','limitations','next_steps']}


def status(T, runtime):
    job = T.R.read(runtime/'repair.json', {})
    if job.get('state') in ACTIVE and time.time()-job.get('heartbeat', 0)>120:
        job = dict(job, state='interrupted', message='Repair coordinator stopped responding. Inspect its helper before retrying; it was not relaunched automatically.')
    return job


def parent(T, ctx, target):
    root, stream, runtime, review, packet, key = ctx
    if not target or not re.fullmatch(r't[0-9a-z]+', target):
        T.fail('Choose this stream’s current lead conversation')
    row = T.hc('get', target)
    labels = row.get('labels') or {}
    if labels.get('repo-tools.repo')!=key or labels.get('repo-tools.stream')!=stream or labels.get('repo-tools.role') not in ('studio','work'):
        T.fail('Target is not this stream’s lead conversation')
    if not os.path.samefile(labels.get('repo-tools.checkout',''), root):
        T.fail('Agent checkout does not match the selected stream')
    if row.get('state')!='live' or not T.agent_running(row):
        T.fail('Resume this stream’s lead conversation first; no agent was interrupted')
    return row, labels


def idle(row):
    s = row.get('status') or {}
    return isinstance(s, dict) and s.get('state') in ('idle','done') and bool(s.get('app'))


def request(T, ctx, target):
    root, stream, runtime, review, packet, key = ctx
    with T.R.lock(runtime/'repair-launch.lock'):
        row, labels = parent(T, ctx, target)
        evidence = T.snapshot(ctx)
        T.failure_prompt(evidence)  # Require captured failures, including stale ones.
        if evidence['state'] in ('queued','running','preparing'):
            T.fail('Wait for this test run to finish before requesting repair')
        old = status(T, runtime)
        if old.get('state') in ACTIVE or (old.get('run')==evidence.get('token') and old.get('state') in ('sent','uncertain','interrupted')):
            return dict(old, message=old['message']+' No duplicate request was started.')
        if idle(row):
            result = T.send(ctx,target,repair=True)
            job = dict(state='sent',run=evidence['token'],target=target,
                       message=result['message'],heartbeat=time.time())
            T.R.write(runtime/'repair.json',job)
            return job
        name = 'cursor' if labels.get('repo-tools.agent')=='cursor' else 'codex'
        binary = T.agents.executable(name)
        token = uuid.uuid4().hex[:12]
        job = dict(state='launching',token=token,run=evidence['token'],target=target,
            agent=name,binary=binary,heartbeat=time.time(),started=T.R.now(),
            message='Starting a read-only '+name+' diagnosis; repair will go to the lead when idle.')
        T.R.write(runtime/'repair.json',job)
        space = labels.get('herdr.space') or 'stream-'+key+'-'+stream
        argv = ['run','--bg','--keep','--parent',target,'--outlive-parent','--no-notify',
                '--name','test-repair-'+token,'--cwd',str(root)]
        tags = {'repo-tools.repo':key,'repo-tools.stream':stream,'repo-tools.role':'helper',
                'repo-tools.checkout':str(root),'repo-tools.agent':name,'repo-tools.task':'test-repair',
                'herdr.space':space,'herdr.tab':space+'-repair-'+token[:4]}
        for k,v in tags.items(): argv += ['--label',k+'='+v]
        try:
            result=T.hc(*argv,'--',sys.executable,str(T.BIN/'repo-tests.py'),'_repair-worker',stream,token)
        except Exception:
            # The worker may have launched despite a lost reply. Never replay.
            T.fail('Repair launch acknowledgement was lost. Refresh to inspect progress; do not launch another helper.')
        return dict(job, terminal=result.get('address'))


def worker(T, stream, token):
    ctx=T.context(stream);root,stream,runtime,review,packet,key=ctx
    with T.R.lock(runtime/'repair-worker.lock'):
        job=T.R.read(runtime/'repair.json',{})
        if job.get('token')!=token or job.get('state')!='launching':
            T.fail('Repair request changed; nothing started')
        def tick(state=None,message=None):
            if state: job['state']=state
            if message: job['message']=message
            job['heartbeat']=time.time()
            T.R.write(runtime/'repair.json',job)
        try:
            parent(T,ctx,job['target'])
            job['terminal']=os.environ.get('HC_TERMINAL_ID')
            folder=runtime/('repair-'+token);folder.mkdir()
            T.R.write(folder/'schema.json',SCHEMA)
            evidence=T.snapshot(ctx)
            prompt=T.failure_prompt(evidence)+'''\nThis is a READ-ONLY diagnosis while the lead edits this checkout. Do not edit files or run tests, install packages, change Docker, commit, push, spawn agents, or message the lead. Compare captured failures with current check configuration and relevant project tooling. Files may change while you read; state that limitation. Distinguish stale evidence and runner errors from confirmed product defects. Return JSON with diagnosis, limitations, next_steps. Keep it focused; no full regression. The controller will ask the lead to verify and repair when idle.'''
            (folder/'prompt.txt').write_text(prompt)
            tick('investigating','Read-only '+job['agent']+' helper is investigating. Your main agent continues working.')
            argv=T.setup_argv(job['agent'],job['binary'],root,folder,prompt)
            code=T.R.process(argv,root,folder/'agent.log',300,tick=tick)
            if code: T.fail('Diagnosis stopped (exit '+str(code)+'). Inspect the helper log; no repair was sent.')
            result=T.agents.structured_result(job['agent'],folder)
            if not isinstance(result,dict) or any(not isinstance(result.get(k),str) for k in SCHEMA['required']):
                T.fail('Diagnosis did not return a usable report; no repair was sent')
            report='\n'.join(k+': '+result[k] for k in SCHEMA['required'])[:12000]
            T.R.write(folder/'report.json',result)
            tick('waiting','Diagnosis ready. Waiting for the current lead to become idle; repair will be sent automatically.')
            deadline=time.monotonic()+24*60*60
            while time.monotonic()<deadline:
                row,_=parent(T,ctx,job['target'])
                current=T.snapshot(ctx)
                if current.get('token')!=job['run'] or not current.get('failure_prompt'):
                    tick('superseded','Test evidence changed. This repair request was retired; inspect the latest results.')
                    return
                if idle(row) and current['state'] not in ('queued','running','preparing'):
                    try: T.active_guard(root,stream,review,key)
                    except RuntimeError: pass  # Wait for the existing workflow/review too.
                    else:
                        # Mark delivery uncertain before send: a crash must not replay it.
                        tick('uncertain','Sending the repair request; inspect the lead if acknowledgement is lost.')
                        T.send(ctx,job['target'],repair=True,diagnosis=report)
                        tick('sent','Repair requested in the original conversation. Follow its progress there; test results are not yet verified.')
                        return
                tick()
                time.sleep(5)
            tick('expired','Lead did not become available within 24 hours. No repair was sent; click again when ready.')
        except (RuntimeError,OSError,ValueError,T.sp.SubprocessError) as exc:
            tick('uncertain' if job.get('state')=='uncertain' else 'failed',str(exc))
        finally:
            print(job.get('message','Repair stopped'),flush=True)
