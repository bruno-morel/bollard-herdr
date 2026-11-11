#!/usr/bin/env python3
"""Resolve native Compose config without changing it; isolate runtime resources."""
import json, os, pathlib, subprocess, sys
source, checkout, state, repo_id, slug, slot = sys.argv[1:]
source, checkout, state = map(pathlib.Path, (source, checkout, state))
slot = int(slot)
project = f'work-{repo_id}-{slug}'
env = dict(os.environ)
for key in list(env):
    if key.startswith('COMPOSE_'):
        del env[key]
original = state/'compose.env' if (state/'compose.env').is_file() else next((p for p in (source/'.env', source/'.env.example') if p.is_file()), None)
lines = original.read_text().splitlines() if original else []
lines = [line for line in lines if not line.lstrip().startswith(('COMPOSE_', 'VITE_API_BASE_URL='))]
# Retain the existing application's API port convention.
lines += [f'VITE_API_BASE_URL=http://localhost:{5173 + slot * 100}/api']
env['VITE_API_BASE_URL'] = f'http://localhost:{5173 + slot * 100}/api'
envfile = state/'compose.env'
envfile.write_text('\n'.join(lines)+'\n'); envfile.chmod(0o600)
base = next((checkout/n for n in ('compose.yaml','compose.yml','docker-compose.yml','docker-compose.yaml') if (checkout/n).is_file()), None)
if base is None:
    sys.exit('work: repository has no Compose file')
args = ['docker','compose','--project-directory',str(checkout),'--env-file',str(envfile),'-p',project,'-f',str(base)]
override = next((checkout/n for n in ('compose.override.yaml','compose.override.yml','docker-compose.override.yml','docker-compose.override.yaml') if (checkout/n).is_file()), None)
if override: args += ['-f',str(override)]
config = json.loads(subprocess.check_output(args+['config','--format','json'],cwd=checkout,env=env,text=True))
config['name'] = project
for name, service in config.get('services',{}).items():
    if service.get('network_mode') == 'host':
        sys.exit('work: host networking cannot be isolated')
    if 'container_name' in service: service['container_name'] = f'{project}-{name}'
    for port in service.get('ports',[]):
        published = str(port.get('published',''))
        if published and published != '0':
            if not published.isdigit() or not 1 <= int(published)+slot*100 <= 65535:
                sys.exit('work: cannot offset published port: '+published)
            port['published'] = str(int(published)+slot*100)
    if name == 'tenhumans':
        service.setdefault('environment',{})['VITE_API_BASE_URL'] = f'http://localhost:{5173+slot*100}/api'
for kind in ('volumes','networks'):
    for name, value in config.get(kind,{}).items():
        if value.get('external'):
            sys.exit(f'work: external {kind} resource {name} cannot be isolated automatically')
        value['name'] = f'{project}-{name}'
# Escape resolved dollar signs so Compose doesn't interpolate them twice.
def literal(value):
    if isinstance(value,str): return value.replace('$','$$')
    if isinstance(value,list): return [literal(v) for v in value]
    if isinstance(value,dict): return {k:literal(v) for k,v in value.items()}
    return value
result = state/'compose.work.json'
result.write_text(json.dumps(literal(config),indent=2)+'\n'); result.chmod(0o600)
