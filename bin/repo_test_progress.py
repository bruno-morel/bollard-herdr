"""Shared desktop/TUI test progress. Agent reports never grant a passing result."""
import time

PHASES = ('investigating', 'fixing', 'awaiting-tests', 'blocked')
LABELS = {'investigating':'Investigating', 'fixing':'Fixing',
          'awaiting-tests':'Awaiting verification', 'blocked':'Blocked',
          'launching':'Starting diagnosis', 'waiting':'Waiting for lead',
          'working':'Agent working · stage not reported', 'sent':'Repair requested', 'uncertain':'Delivery unconfirmed',
          'interrupted':'Repair interrupted', 'failed':'Repair failed',
          'expired':'Repair expired', 'superseded':'Repair superseded'}


def report(T, ctx, run, phase, message=''):
    if phase not in PHASES:T.fail('Choose investigating, fixing, awaiting-tests or blocked')
    runtime=ctx[2]
    with T.R.lock(runtime/'repair-progress.lock'):
        job=T.R.read(runtime/'repair.json',{})
        evidence=T.R.read(runtime/'state.json',{})
        if not run or run not in (job.get('run'), evidence.get('token')):
            T.fail('Progress belongs to an older test run; refresh the Tests pane')
        out=dict(run=run,phase=phase,message=message[:500],updated=time.time())
        T.R.write(runtime/'repair-progress.json',out)
        return out


def view(s, progress=None):
    job=s.get('repair') or {}; progress=progress or {}
    rows=s.get('results') or []
    passed=sum(x.get('exit_code')==0 for x in rows)
    failed=sum(x.get('exit_code') not in (0,None,-1) for x in rows)
    incomplete=sum(x.get('exit_code') in (None,-1) for x in rows)
    running=int(s.get('state')=='running' and bool(s.get('current')) and not any(x.get('id')==s['current'] for x in rows))
    unrun=max(0,len(s.get('checks') or [])-len(rows)-running)
    state=s.get('state'); old=bool(job.get('run') and job['run']==s.get('token'))
    phase=job.get('state'); detail=job.get('message','')
    if progress.get('run') in (job.get('run'),s.get('token')) and progress.get('run') and phase in ('sent','uncertain',None):
        phase=progress['phase'];detail=progress.get('message','')
    if job.get('state')=='sent' and old and phase!='blocked':
        lead=job.get('lead_state')
        if lead in ('done','idle'):phase='awaiting-tests';detail='Agent finished; fresh verification is still needed.'
        elif lead in ('blocked','unavailable'):phase='blocked';detail='Open the lead conversation to resolve the blocker.'
        elif lead=='working' and phase=='sent':phase='working'
    tone='warning';active=False
    if state in ('queued','running','preparing'):
        label='Preparing tests' if state=='preparing' else 'Rerunning tests' if job else 'Running tests'
        phase='rerunning';active=True;detail=s.get('current') or s.get('message','')
    elif phase and old:
        label=LABELS.get(phase,'Repair in progress')
        active=phase in ('launching','investigating','fixing','waiting','working')
        if phase in ('failed','blocked','interrupted','uncertain'):tone='error'
    elif state=='passed':label='Checks passed';phase='verified';tone='success'
    elif state=='failed':label='Checks still failing' if job else 'Checks failed';phase='failed';tone='error'
    elif state=='stale':label='Results out of date';phase='stale'
    elif state=='incomplete':label='Verification incomplete';phase='incomplete';tone='error'
    else:label='Not run';phase='not-run';tone='muted'
    historical=state=='stale' or (old and bool(phase))
    counts=f'{passed} passed · {failed} failed · {incomplete} incomplete · {unrun} unrun'
    if running:counts+=f' · {running} running'
    return dict(phase=phase,label=label,tone=tone,active=active,
        counts=counts,historical=historical,
        summary=('Previous run: ' if historical else '')+counts,
        detail=detail,passed=passed,failed=failed,incomplete=incomplete,unrun=unrun,running=running)
