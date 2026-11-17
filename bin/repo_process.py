"""Verify an agent under a managed wrapper; an idle recovery shell is not an agent."""
from pathlib import Path
import subprocess as sp

def agent_running(row):
    fg=row.get('foreground') or {}
    words=[Path(str(x)).name for x in fg.get('argv',[])[:4]]
    if fg.get('name') in ('codex','cursor-agent','agent','claude') or any(x in ('codex','cursor-agent','agent','claude','index.js') for x in words):return True
    pid=row.get('pid')
    if not isinstance(pid,int):return False
    try:
        raw=sp.check_output(['ps','-axo','pid=,ppid=,comm='],text=True,timeout=5)
        records=[line.split(None,2) for line in raw.splitlines() if len(line.split(None,2))==3]
        ids={pid}
        for _ in range(12):
            new={int(x[0]) for x in records if int(x[1]) in ids}
            if not new-ids:break
            ids|=new
        return any(int(p) in ids and Path(name).name in ('codex','claude','cursor-agent','agent') for p,_,name in records)
    except (OSError,ValueError,sp.SubprocessError):return False


def run_foreground(args, *, cwd, env):
    """Give a Herdr agent its own foreground job, then return to the menu.

    Called only by the single-threaded CLI launcher. Unlike setsid, a new
    process group retains this terminal, its input, and native status reports.
    """
    import os
    import signal
    import sys

    fd = sys.stdin.fileno()
    if not env.get('HC_TERMINAL_ID') or not os.isatty(fd):
        return sp.run(args, cwd=cwd, env=env)
    owner = os.tcgetpgrp(fd)
    if owner != os.getpgrp():
        raise RuntimeError('agent launcher does not own the terminal; return to its foreground pane')

    def take_terminal():
        os.setpgid(0, 0)
        signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        os.tcsetpgrp(fd, os.getpgrp())
        signal.signal(signal.SIGTTOU, signal.SIG_DFL)

    try:
        # The child takes control before exec/read, avoiding a SIGTTIN race.
        with sp.Popen(args, cwd=cwd, env=env, preexec_fn=take_terminal) as child:
            try:
                code = child.wait()
            except KeyboardInterrupt:
                child.send_signal(signal.SIGINT)
                code = child.wait()
        return sp.CompletedProcess(args, code)
    finally:
        previous = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        try:
            os.tcsetpgrp(fd, owner)
        finally:
            signal.signal(signal.SIGTTOU, previous)
