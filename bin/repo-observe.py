#!/usr/bin/env python3
"""Read an existing stream's Docker status/logs; never create or start resources."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess as sp
import sys

BIN = Path(__file__).resolve().parent

def run(argv, root, env=None, timeout=8):
    p = sp.run(argv, cwd=root, env=env, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip()[-1800:] or 'Inspection failed')
    return p.stdout

def rows(raw):
    raw=raw.strip()
    return json.loads(raw) if raw.startswith('[') else [json.loads(x) for x in raw.splitlines() if x.strip()]

def enrich(services, root, env):
    """Inspect only these Compose containers; never read container environment values."""
    ids=[s['ID'] for s in services if re.fullmatch(r'[a-f0-9]{12,64}',s.get('ID',''))]
    errors=[]
    if not ids:return errors
    fmt='{"ID":{{json .Id}},"StartedAt":{{json .State.StartedAt}},"RestartCount":{{.RestartCount}},"Running":{{.State.Running}},"MemoryLimitBytes":{{.HostConfig.Memory}}}'
    try:
        details=rows(run(['docker','inspect','--format',fmt,*ids],root,env,timeout=4))
        for s in services:
            d=next((x for x in details if x['ID'].startswith(s.get('ID','!'))),None)
            if not d:continue
            s.update(StartedAt=d['StartedAt'],Restarts=d['RestartCount'],UptimeSeconds=None,MemoryLimitBytes=d.get('MemoryLimitBytes'))
            if d['Running']:
                try:
                    stamp=re.sub(r'(\.\d{6})\d+(?=[+-]\d{2}:\d{2}$)',r'\1',d['StartedAt'].replace('Z','+00:00'))
                    started=datetime.fromisoformat(stamp)
                    s['UptimeSeconds']=max(0,int((datetime.now(timezone.utc)-started).total_seconds()))
                except ValueError:pass
    except (RuntimeError,ValueError,OSError,sp.SubprocessError):errors.append('Uptime and restart readings unavailable.')
    live=[s['ID'] for s in services if s.get('State')=='running' and s.get('ID') in ids]
    if live:
        try:
            stats=rows(run(['docker','stats','--no-stream','--format','{{json .}}',*live],root,env,timeout=5))
            for s in services:
                d=next((x for x in stats if x.get('ID','!')==s.get('ID') or x.get('Name')==s.get('Name')),None)
                if d:s['Metrics']={k:d.get(k) for k in ('CPUPerc','MemPerc','MemUsage','NetIO','BlockIO','PIDs')}
        except (RuntimeError,ValueError,OSError,sp.SubprocessError):errors.append('Resource readings unavailable; container status is still current.')
    return errors

def prepared_environment(values, root):
    """Studio allocates state.env before it ever generates a Compose environment.

    Only that exact, wholly absent generated pair is an expected empty state.
    Partial configurations, custom paths and unreadable files stay errors.
    """
    compose = values.get('COMPOSE_FILE', '')
    envfile = values.get('COMPOSE_ENV_FILES', '')
    if not values.get('COMPOSE_PROJECT_NAME') or not compose:
        raise RuntimeError('This stream has no valid saved Docker environment.')
    config_path = Path(compose)
    env_path = Path(envfile)
    if not config_path.is_absolute():
        config_path = root / config_path
    if not env_path.is_absolute():
        env_path = root / env_path
    generated = (
        config_path.name == 'compose.work.json'
        and env_path.name == 'compose.env'
        and config_path.parent == env_path.parent
        and (config_path.parent / 'state.env').is_file()
    )
    if generated:
        def present(path):
            try:
                path.stat()
                return True
            except FileNotFoundError:
                # A broken symlink is configuration damage, not a fresh stream.
                return path.is_symlink()
        config_exists, env_exists = present(config_path), present(env_path)
        if not config_exists and not env_exists:
            return False
        if config_exists != env_exists:
            raise RuntimeError('The saved Docker configuration is incomplete. '
                               'Its Compose file and environment file must both be present.')
    return True

def inspect(stream=None, status_only=False, service=None, metrics=False):
    try:
        root = Path(run(['git', 'rev-parse', '--show-toplevel'], '.').strip())
        branch = run(['git', 'symbolic-ref', '--quiet', '--short', 'HEAD'], root).strip()
    except RuntimeError:
        raise RuntimeError('Run inside a Git stream checkout to inspect its Docker stack.')
    stream = stream or (branch[6:] if branch.startswith('codex/') else '')
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', stream) or branch != 'codex/' + stream:
        raise RuntimeError('Select the matching stream checkout before opening Docker.')
    values = json.loads(run([str(BIN/'work'), '_herdr-env', stream], root))
    if not prepared_environment(values, root):
        if service:
            raise RuntimeError('This stream has not prepared any Docker services yet.')
        return {'stream':stream, 'project':values['COMPOSE_PROJECT_NAME'],
                'state':'unprepared', 'services':[], 'logs':'', 'warnings':[],
                'observed_at':datetime.now(timezone.utc).isoformat()}
    env = {k:v for k,v in os.environ.items() if not k.startswith('COMPOSE_')}
    env.update({k:v for k,v in values.items() if k.startswith('COMPOSE_') and isinstance(v,str)})
    raw = run(['docker','compose','ps','--all','--format','json'], root, env).strip()
    services = rows(raw)
    if service and service not in {s.get('Service') for s in services}:raise RuntimeError('Unknown service in this stream')
    logs = '' if status_only or not services else run(['docker','compose','logs','--no-color','--timestamps','--tail','100',*([service] if service else [])], root, env)
    warnings=enrich(services,root,env) if metrics else []
    state = 'active' if any(s.get('State') in ('running','restarting','paused') for s in services) else 'stopped' if services else 'empty'
    return {'stream':stream, 'project':values['COMPOSE_PROJECT_NAME'], 'state':state, 'services':services, 'logs':logs[-120000:], 'warnings':warnings, 'observed_at':datetime.now(timezone.utc).isoformat()}

def main():
    p=argparse.ArgumentParser(description='Read the current stream’s existing Docker status and recent logs.')
    p.add_argument('stream',nargs='?');p.add_argument('--json',action='store_true')
    p.add_argument('--status-only',action='store_true');p.add_argument('--service')
    p.add_argument('--metrics',action='store_true',help='Read bounded uptime and resource snapshots for this stack only')
    a=p.parse_args()
    try:
        result=inspect(a.stream,a.status_only,a.service,a.metrics)
        print(json.dumps(result) if a.json else result['logs'] or ('No Docker stack prepared for this stream yet.' if result['state'] == 'unprepared' else 'No container logs.'))
    except (RuntimeError,OSError,ValueError,sp.SubprocessError) as e:
        sys.exit('work observe: '+str(e))

if __name__=='__main__':main()
