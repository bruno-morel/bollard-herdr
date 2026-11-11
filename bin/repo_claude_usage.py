"""Read Claude's native /usage screen. No prompts, tokens, or private API calls."""
import errno
import fcntl
import json
import math
import os
import pty
import re
import select
import signal
import struct
import subprocess as sp
import termios
import time
import uuid
from datetime import datetime, timedelta, timezone

INTERVAL = 300
OSC = re.compile(r'\x1b\][\s\S]*?(?:\x07|\x1b\\)')
CSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
HEADINGS = {
    'Current session': 'five_hour',
    'Current session (5h)': 'five_hour',
    'Current week (all models)': 'seven_day',
    'Current week (Sonnet only)': 'seven_day_sonnet',
    'Current week (Opus only)': 'seven_day_opus',
}


def plain(raw):
    text = raw.decode('utf-8', errors='replace') if isinstance(raw, bytes) else raw
    return re.sub(r'\x1b[78=>]', '', CSI.sub('', OSC.sub('', text))).replace('\r', '')


def reset_epoch(label, window, now):
    # TZ=UTC fixes locale ambiguity. Keep the displayed text if syntax changes.
    m = re.fullmatch(r'Resets (?:(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2}) at )?(\d{1,2})(?::(\d{2}))?(am|pm) \(UTC\)', label)
    if not m:
        return None
    mon, day, hour, minute, ap = m.groups()
    hour, minute = int(hour), int(minute or 0)
    if not 1 <= hour <= 12 or not 0 <= minute < 60:
        return None
    hour = hour % 12 + (12 if ap == 'pm' else 0)
    dt = datetime.fromtimestamp(now, timezone.utc)
    if mon:
        month = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'].index(mon) + 1
        candidates = []
        for year in (dt.year, dt.year + 1):
            try:
                candidates.append(dt.replace(year=year, month=month, day=int(day), hour=hour, minute=minute, second=0, microsecond=0))
            except ValueError:
                pass
    else:
        candidate = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
        candidates = [candidate, candidate + timedelta(days=1)]
    limit = 6 * 3600 if window == 'five_hour' else 8 * 86400
    return next((d.timestamp() for d in candidates if 0 < d.timestamp()-now <= limit), None)


def parse_usage(text, now=None):
    now = time.time() if now is None else now
    windows, current = {}, None
    for raw in plain(text).splitlines():
        line = raw.strip()
        if line in HEADINGS:
            current = HEADINGS[line]
            windows.pop(current, None)
        elif line.startswith('Current ') or line.startswith("What's contributing"):
            current = None
        elif current:
            match = re.search(r'(?<![\d.\-])(\d+(?:\.\d+)?)% used\b', line)
            if match:
                value = float(match[1])
                if math.isfinite(value) and 0 <= value <= 100:
                    windows[current] = {'used_percent': value, 'resets_at': None}
                else:
                    windows.pop(current, None)
                    current = None
            elif current in windows and line.startswith('Resets '):
                windows[current]['reset_text'] = line[:160]
                windows[current]['resets_at'] = reset_epoch(line, current, now)
    return windows


def native_usage(executable, folder, timeout=18):
    """A bounded, isolated CLI process; the only submitted command is /usage."""
    if folder.is_symlink():
        raise RuntimeError('Quota-check folder must not be a symlink.')
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = dict(os.environ, TERM='xterm-256color', NO_COLOR='1', NO_OPEN_BROWSER='1',
               TZ='UTC', CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION='false',
               DISABLE_AUTOUPDATER='1', DISABLE_TELEMETRY='1', DISABLE_ERROR_REPORTING='1')
    # This switch also suppresses the native account-usage request.
    env.pop('CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC', None)
    for key in ('CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT'):
        env.pop(key, None)
    args = [executable, '--safe-mode', '--ax-screen-reader', '--tools', '',
            '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
            '--no-chrome', '--permission-mode', 'dontAsk']
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 48, 150, 0, 0))
    try:
        proc = sp.Popen(args, stdin=slave, stdout=slave, stderr=slave,
                        cwd=folder, env=env, start_new_session=True)
    except BaseException:
        os.close(master)
        raise
    finally:
        os.close(slave)
    buf, sent, last = b'', False, time.monotonic()
    deadline = last + timeout
    try:
        while time.monotonic() < deadline:
            if select.select([master], [], [], .1)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError as e:
                    if e.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                buf += chunk
                last = time.monotonic()
                if len(buf) > 1024 * 1024:
                    raise RuntimeError('Unexpectedly large Claude usage screen.')
                if b'\x1b[6n' in chunk:
                    os.write(master, b'\x1b[1;1R')
            text = plain(buf)
            if 'Permission Required: Accessing workspace' in text or 'Enter y/n:' in text:
                raise RuntimeError('Claude needs its one-time folder setup. On JumpBox run: cd '+str(folder)+' && claude')
            if not sent and 'Claude Code v' in text and re.search(r'(?:^|\n)\$\s*$', text):
                # Screen-reader mode gives an unambiguous input prompt. Never send
                # text through setup/auth dialogs or another running conversation.
                os.write(master, b'/usage\r')
                sent = True
                buf = b''
                continue
            if sent and ('Failed to load usage data' in text or 'Unknown command' in text):
                raise RuntimeError('Claude’s usage screen is temporarily unavailable; sign-in is unchanged.')
            if sent and time.monotonic() - last >= .6:
                windows = parse_usage(text)
                if {'five_hour', 'seven_day'} <= windows.keys():
                    return {'windows': windows, 'reported_at': time.time(), 'source': 'claude-native-usage'}
            if proc.poll() is not None:
                break
        raise RuntimeError('Claude did not report complete usage limits in time. The previous reading is preserved.')
    finally:
        # /usage is a dialog, so two interrupts exit this otherwise empty session.
        # Never signal another CLI or touch any existing Herdr terminal.
        if proc.poll() is None:
            try:
                os.write(master, b'\x03\x03')
                proc.wait(timeout=.4)
            except (OSError, sp.TimeoutExpired):
                if proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait(timeout=2)
        os.close(master)


def read(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def write(path, data):
    tmp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('x') as f:
            os.chmod(tmp, 0o600)
            json.dump(data, f)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def refresh(executable, folder):
    """One check per account/machine per five minutes, even across streams."""
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    sample = folder/'claude-quota.json'
    attempt = folder/'claude-usage-check.json'
    with (folder/'claude-usage.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return read(sample), {'refreshing': True}
        q, check, now = read(sample), read(attempt), time.time()
        if q.get('windows') and 0 <= now-q.get('reported_at', 0) < INTERVAL:
            return q, {'checked': check.get('checked'), 'interval_seconds': INTERVAL}
        if 0 <= now-check.get('checked', 0) < INTERVAL:
            return q, check
        check = {'checked': now, 'interval_seconds': INTERVAL}
        write(attempt, check)  # Also throttles failures/crashes; refresh can't hammer it.
        try:
            latest = native_usage(executable, folder/'quota-probe')
            # A real conversation's status-line hook may have reported meanwhile.
            other = read(sample)
            if other.get('reported_at', 0) > latest['reported_at']:
                q = other
            else:
                q = latest
                write(sample, q)
        except (RuntimeError, OSError, sp.SubprocessError) as e:
            check['note'] = str(e)
            q = read(sample)
        write(attempt, check)
        return q, check
