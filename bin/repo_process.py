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
