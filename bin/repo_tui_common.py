"""Shared, machine-local presentation state; agents remain owned by herdr-core."""
from repo_state import write_json as save
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess as sp
import time

import repo_stream_backend as Streams
SESSION = os.environ.get('REPO_TUI_SESSION', 'studio-work-v2')
BASE = Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state')))/'repo-tools'/'tui'

def read(path, default=None):
    try: return json.loads(path.read_text())
    except FileNotFoundError: return default

def runtime():
    if not re.fullmatch(r'[a-zA-Z0-9-]+', SESSION): raise RuntimeError('Invalid dashboard session')
    p = BASE/SESSION
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    return p


def update(name, fn):
    with (runtime()/(name+'.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        p = runtime()/(name+'.json')
        value = fn(read(p, {}))
        save(p, value)
        return value

def layout(): return read(runtime()/'layout.json', {})
def lane_state(lane): return read(runtime()/(lane+'.json'), {})
def control(lane, **fields): return update(lane+'-control', lambda d: dict(d, **fields))
def state(lane): return read(runtime()/(lane+'-control.json'), {})

def viewer_started():
    """Only acknowledge a visible TUI, not its detached background server."""
    now=time.time();starts=[]
    for path in runtime().glob('viewer-*.json'):
        try:
            data=read(path,{})
            if 0<=now-data['heartbeat']<8:
                os.kill(int(data['pid']),0)
                starts.append(float(data['started_ms']))
        except (OSError,ValueError,KeyError,TypeError):continue
    return min(starts) if starts else None

def managed():
    # Herdr shell keybindings carry the session, but do not inherit pane variables.
    return os.environ.get('HERDR_ENV') == '1' or os.environ.get('HERDR_SESSION') == SESSION

def native(*args):
    if not managed():
        raise RuntimeError('Open this control inside the Studio/Work TUI')
    r = sp.run([shutil.which('herdr') or str(Path.home()/'.local/bin/herdr'), '--session', SESSION, *args],
               capture_output=True, text=True, timeout=10)
    if r.returncode: raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    if not r.stdout.strip(): return {}
    value = json.loads(r.stdout)
    if value.get('error'): raise RuntimeError(str(value['error']))
    return value.get('result', value)

def pane_id(result):
    p = result['pane']
    return p['pane_id'] if isinstance(p, dict) else p

def focus_conversation(lane):
    d = layout().get(lane, {})
    if d.get('conversation'):
        native('pane', 'zoom', d['panel'], '--off')
        native('pane', 'focus', '--pane', d['panel'], '--direction', 'down')

def status(row):
    s = row.get('status')
    return s if isinstance(s, str) else (s or {}).get('state', 'unknown')

class Backend(Streams.Backend):
    def call(self, row, name, args=(), timeout=40, raw=False):
        return self.script(
            Streams.machine(row['address']), name, args,
            cwd=Streams.label(row, 'checkout') or row['cwd'],
            timeout=timeout, raw=raw,
        )

    def data(self, row, *args): return self.call(row, 'repo-tui-data.py', args)
    def work(self, row, *args): return self.call(row, 'work', args)

def bar(value, width=12):
    if value is None: return '['+'?'*width+']'
    n = max(0, min(width, round(float(value)*width/100)))
    return '['+'█'*n+'░'*(width-n)+']'

def level(value): return 4 if value is not None and value >= 90 else 3 if value is not None and value >= 70 else 2

def reset_note(epoch):
    import time
    if not epoch: return 'Reset not reported'
    seconds = max(0, int(float(epoch)-time.time()))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    return 'Reset due' if not seconds else 'Resets in '+(f'{days}d {hours}h' if days else f'{hours}h {rest//60}m')

def memory(service):
    reading = service.get('Metrics') or {}
    def size(text):
        m = re.fullmatch(r'([\d.]+)\s*([KMGT]?i?B)', text.strip(), re.I)
        if not m: return None
        unit = m[2].upper()
        power = 'KMGT'.find(unit[0])+1
        return float(m[1]) * (1024 if 'I' in unit else 1000)**max(0, power)
    used_text, _, limit_text = reading.get('MemUsage', '').partition('/')
    used, limit = size(used_text), size(limit_text)
    cap = service.get('MemoryLimitBytes') or 0
    if cap > 0: limit, limit_text = cap, f'{cap/1024**2:.0f} MiB'
    return used_text.strip(), limit_text.strip(), (100*used/limit if used is not None and limit else None), bool(cap)
