"""File requests shared with the desktop; no agent input or process control."""
import json
import math
from pathlib import PurePosixPath
import re
import unicodedata

DOCS = {'.md', '.markdown', '.mdown', '.mkd', '.txt'}

def request_for(terminal):
    try:
        value=json.loads((terminal.get('labels') or {}).get('repo-read.request','{}'))
    except (ValueError,TypeError):
        return None
    if not isinstance(value,dict):return None
    path=value.get('path');root=value.get('root');when=value.get('time')
    if (value.get('v')!=1 or not isinstance(value.get('id'),str)
        or not re.fullmatch(r'[a-f0-9]{24}',value['id'])
        or not isinstance(path,str) or not path or len(path)>4096 or '\0' in path
        or PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts
        or not isinstance(root,str) or not root.startswith('/') or '\0' in root
        or type(when) not in (int,float) or not math.isfinite(when)):
        return None
    return dict(value)

def result_for(terminal):
    try:
        value=json.loads((terminal.get('labels') or {}).get('repo-read.result','{}'))
        return value if isinstance(value,dict) else {}
    except (ValueError,TypeError):return {}

def pending_request(terminal, seen, viewer_started):
    if viewer_started is None or terminal.get('state')!='live':return None
    request=request_for(terminal)
    if not request or request['id']==seen:return None
    result=result_for(terminal)
    # A newly attached viewer must not replay historical, already handled requests.
    # New requests reach each attached view even if the desktop acknowledges first.
    if request['time']<viewer_started and result.get('id')==request['id']:return None
    return request

def ack_if_current(backend,address,request_id,status,message='',view='docs'):
    current=backend.hc('get',address);request=request_for(current)
    if not request or request['id']!=request_id:return False
    previous=result_for(current)
    if previous.get('id')==request_id and previous.get('status')=='shown':return True
    result=dict(id=request_id,status=status,message=str(message)[:300],viewer='tui',view=view)
    backend.hc('label',address,'repo-read.result='+json.dumps(result,separators=(',',':')))
    return True

def display_width(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)

def toolbar_start(width,labels):
    total=sum(display_width(label)+2 for label in labels)+max(0,len(labels)-1)
    return max(1,width-2-total)
