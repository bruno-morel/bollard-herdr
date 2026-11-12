#!/usr/bin/env python3
"""Open an independent Herdr window on the same core; never launch an agent."""
import argparse,copy,ctypes,fcntl,hashlib,json,os,re,shutil,subprocess as sp,sys,time
from pathlib import Path
from urllib.parse import quote

def load(path,default=None):
 try:return json.loads(path.read_text())
 except FileNotFoundError:return default

def save(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(data,indent=2)+'\n');path.chmod(0o600)

def find(node,key):
 if node.get('id')==key:return node
 for child in node.get('children',[]):
  found=find(child,key)
  if found:return found
 return None

def sync_interface(origin,destination):
 # Herdr's asset loader requires real files beneath each app home.
 # Refresh only our managed interface files; preserve this window's layout,
 # state, settings, focus and position.
 for folder in ['helpers']+['mods/'+p.name for p in (origin/'mods').iterdir() if p.name.startswith('repo-') and p.is_dir()]:
  src=origin/folder;target=destination/folder
  if not src.is_dir():continue
  if target.is_symlink():
   if target.resolve()!=src.resolve():raise RuntimeError('Unexpected window interface link: '+str(target))
   target.unlink()
  for item in src.rglob('*'):
   if not item.is_file() or '__pycache__' in item.parts:continue
   out=target/item.relative_to(src)
   if out.is_file() and out.read_bytes()==item.read_bytes():continue
   out.parent.mkdir(parents=True,exist_ok=True)
   shutil.copy2(item,out)

def prepare(source,lane,context=None):
 shared=load(source/'shared.json',{})
 context=context or shared.get('repo.portrait.lanes',{}).get(lane)
 if not isinstance(context,dict) or not context.get('cwd') or not context.get('stream'):
  raise RuntimeError('Choose a stream before opening another window.')
 if not context['cwd'].startswith('/') or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',context['stream']) or context.get('role') not in ('studio','work'):
  raise RuntimeError('Invalid stream context for the new window.')
 origin=Path((load(source/'repo-window.json',{}) or {}).get('origin',str(source))).resolve()
 key=hashlib.sha256(json.dumps([context.get('on'),context['cwd'],context.get('role')]).encode()).hexdigest()[:12]
 slug=re.sub('[^a-z0-9-]+','-',(context.get('repo','stream')+'-'+context['stream']).lower()).strip('-')[:48]
 legacy=origin/'screens'/(slug+'-'+key)
 # macOS Unix sockets cannot use long profile paths. Keep existing short profiles.
 destination=legacy if legacy.exists() and len(os.fsencode(str(legacy/'herdr-app.sock')))<104 else origin/'screens'/('w-'+key)
 if len(os.fsencode(str(destination/'herdr-app.sock')))>=104:
  raise RuntimeError('Herdr profile path is too long for its control socket; move the app home to a shorter path. No window was launched.')
 if destination==source:raise RuntimeError('This stream already has its own window. Switch to the other Herdr window to open a different stream.')
 destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 with (destination.parent/(key+'.lock')).open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  if destination.exists():
   record=load(destination/'repo-window.json',{})
   if record.get('key')!=key or record.get('origin')!=str(origin):raise RuntimeError('Existing window profile is not managed by Studio / Work.')
   sync_interface(origin,destination)
   return destination,context
  layout_name=shared.get('layout','studio-work-portrait')
  if Path(layout_name).name!=layout_name:raise RuntimeError('Invalid source layout name.')
  tree=load(source/'layouts'/(layout_name+'.json'))
  if not isinstance(tree,dict):raise RuntimeError('Source window layout is unavailable.')
  selected=find(tree,lane+'-lane');streams=find(tree,'portrait-streams');manager=find(tree,'portrait-bar')
  if not selected or not streams or not manager:raise RuntimeError('Choose a stream from the Studio / Work layout.')
  selected=copy.deepcopy(selected);selected['size']={'weight':1};selected['min']=300
  find(selected,lane+'-conversation')['content']=({'terminal':context['terminal']} if context.get('terminal') else {'mod':'repo-portrait','props':{'kind':'empty','lane':lane}})
  find(selected,lane+'-views')['hidden']=True;find(selected,lane+'-info')['hidden']=True
  streams['children']=[selected];streams['type']='column'
  manager['content']['props']['defaults']={lane:context}
  manager['content']['props']['windowTitle']=context.get('repo','Repository')+' / '+context['stream']
  tree.pop('preview',None)
  sidebar=find(tree,'sidebar')
  if sidebar:sidebar['hidden']=True
  destination.mkdir(mode=0o700)
  sync_interface(origin,destination)
  for name in ('settings.json','keys.json','update-notes.json'):
   if (origin/name).is_file():shutil.copy2(origin/name,destination/name)
  save(destination/'layouts/studio-work-window.json',tree)
  save(destination/'shared.json',{'layout':'studio-work-window','frame.welcomed':'finished',
      'repo.portrait.lanes':{lane:context},'repo.portrait.views':{lane:None},
      'repo.portrait.info':{lane:None},'space.colors':shared.get('space.colors',{})})
  save(destination/'window.json',{'state':'windowed','bounds':[80,80,1280,900]})
  save(destination/'repo-window.json',{'version':1,'key':key,'origin':str(origin),'stream':context['stream']})
 return destination,context

def focus_context(executable,env,context):
 terminal=context.get('terminal')
 if not terminal:return
 # The layout binds the terminal directly; labels are not native tab IDs.
 sp.run([executable,'do','pane.focus',json.dumps({'terminal':terminal})],env=env,capture_output=True,text=True,timeout=3)

def open_window(source,lane,context=None):
 destination,context=prepare(source,lane,context)
 with (destination/'open.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  return launch_window(destination,context)

def launch_window(destination,context):
 executable=shutil.which('herdr-app')
 if not executable:raise RuntimeError('The Herdr desktop launcher is unavailable on this computer.')
 env=dict(os.environ,HERDR_APP_HOME=str(destination))
 # Reuse an existing display. An unacknowledged live launch must not be replayed.
 try:
  current=sp.run([executable,'status'],env=env,capture_output=True,text=True,timeout=2)
  if current.returncode==0:
   focus_context(executable,env,context)
   return {'opened':True,'home':str(destination),'stream':context['stream'],'message':'Reused the existing stream window.'}
 except sp.TimeoutExpired:pass
 previous=load(destination/'launch-process.json',{})
 if previous.get('pid'):
  try:os.kill(previous['pid'],0)
  except ProcessLookupError:pass
  else:raise RuntimeError('This window is already opening or is unresponsive. Inspect it before retrying; no duplicate was launched.')
 with (destination/'launch.log').open('w') as log:
  os.chmod(log.name,0o600)
  proc=sp.Popen([executable],env=env,stdin=sp.DEVNULL,stdout=log,stderr=log,start_new_session=True)
 save(destination/'launch-process.json',{'pid':proc.pid})
 deadline=time.monotonic()+18
 while time.monotonic()<deadline:
  try:
   r=sp.run([executable,'status'],env=env,capture_output=True,text=True,timeout=2)
   if r.returncode==0:
    status=json.loads(r.stdout)
    if status.get('errors'):raise RuntimeError('The new window reported a layout error. See '+str(destination/'launch.log'))
    focus_context(executable,env,context)
    return {'opened':True,'home':str(destination),'stream':context['stream'],
            'message':'Opened '+context.get('repo','Repository')+' / '+context['stream']+'. Move it to any screen; Herdr remembers its position.'}
  except (sp.TimeoutExpired,json.JSONDecodeError):pass
  if proc.poll() not in (None,0):raise RuntimeError('Herdr could not open the window. See '+str(destination/'launch.log'))
  time.sleep(.3)
 raise RuntimeError('Herdr is still opening. Click the window again shortly; its profile is preserved.')

def agent_windows(source, context):
 origin=Path((load(source/'repo-window.json',{}) or {}).get('origin',str(source))).resolve()
 profiles=[origin]+sorted((origin/'screens').glob('*'))
 matches=[]
 for home in profiles:
  if not home.is_dir():continue
  if home!=origin:
   owner=(load(home/'repo-window.json',{}) or {}).get('origin')
   if not owner or Path(owner).resolve()!=origin:continue
  if not (home/'herdr-app.sock').is_socket():continue
  state=load(home/'shared.json',{}) or {}
  for lane,c in state.get('repo.portrait.displayed',state.get('repo.portrait.lanes',{})).items():
   exact=c.get('terminal')==context.get('terminal')
   parent=c.get('terminal')==context.get('parent') and bool(context.get('parent'))
   same=(bool(context.get('cwd')) and c.get('cwd')==context['cwd'] and c.get('on')==context.get('on')
         and c.get('stream')==context.get('stream') and (c.get('role')==context.get('role') or context.get('role')=='helper'))
   if exact or parent or same:matches.append((0 if exact else 1 if parent else 2,home,lane,exact))
 return sorted(matches,key=lambda x:(x[0],str(x[1])))


def activate_window(home):
 if sys.platform!='darwin':raise RuntimeError('Automatic window activation currently requires macOS.')
 # Find the process serving this exact profile, not every Herdr application.
 result=sp.run(['/usr/sbin/lsof','-t','-a','-U',str(home/'herdr-app.sock')],capture_output=True,text=True,timeout=3)
 pids=list(dict.fromkeys(x for x in result.stdout.split() if x.isdigit()))
 if len(pids)!=1:raise RuntimeError('Could not identify the window process; no other window was activated.')
 raise_process(int(pids[0]))


def raise_process(pid):
 # NSRunningApplication.activate can return true without bringing independently
 # launched Herdr instances forward. Target the process serial number instead.
 class ProcessSerialNumber(ctypes.Structure):
  _fields_=[('high',ctypes.c_uint32),('low',ctypes.c_uint32)]
 services=ctypes.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
 services.GetProcessForPID.argtypes=[ctypes.c_int32,ctypes.POINTER(ProcessSerialNumber)]
 services.GetProcessForPID.restype=ctypes.c_int32
 services.SetFrontProcessWithOptions.argtypes=[ctypes.POINTER(ProcessSerialNumber),ctypes.c_uint32]
 services.SetFrontProcessWithOptions.restype=ctypes.c_int32
 serial=ProcessSerialNumber()
 if services.GetProcessForPID(pid,ctypes.byref(serial))!=0:
  raise RuntimeError('The Herdr window process is no longer available.')
 if services.SetFrontProcessWithOptions(ctypes.byref(serial),1)!=0:
  raise RuntimeError('macOS could not bring this Herdr instance forward.')
 # Verify the visible result, not just the activation API's return value.
 script='ObjC.import("AppKit"); function run(args) { for (var i=0;i<10;i++) { if (Number($.NSWorkspace.sharedWorkspace.frontmostApplication.processIdentifier)===Number(args[0])) return "focused"; delay(0.1); } throw Error("The requested Herdr window did not come to the front. Please select it from the Dock."); }'
 result=sp.run(['/usr/bin/osascript','-l','JavaScript','-e',script,str(pid)],capture_output=True,text=True,timeout=4)
 if result.returncode or result.stdout.strip()!='focused':
  raise RuntimeError(result.stderr.strip() or 'Could not verify the Herdr window came to the front.')



def focus_agent(source,context):
 terminal=context.get('terminal')
 if not isinstance(terminal,str) or not terminal:raise RuntimeError('Choose an agent to show.')
 executable=shutil.which('herdr-app')
 if not executable:raise RuntimeError('Herdr desktop launcher is unavailable.')
 for _,home,lane,exact in agent_windows(source,context):
  env=dict(os.environ,HERDR_APP_HOME=str(home))
  try:
   status=sp.run([executable,'status'],env=env,capture_output=True,text=True,timeout=2)
   if status.returncode:continue
  except sp.TimeoutExpired:continue
  # Let the destination's own manager update its shared tool selection too.
  payload=quote(json.dumps({'lane':lane,'terminal':terminal,'exact':exact}),safe='')
  result=sp.run([executable,'do','repo-portrait.attention-focus:'+payload],env=env,capture_output=True,text=True,timeout=3)
  if result.returncode:raise RuntimeError(result.stderr or result.stdout or 'Could not focus the agent.')
  activate_window(home)
  return {'found':True,'home':str(home),'terminal':terminal}
 return {'found':False,'terminal':terminal}


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['open','focus-agent']);p.add_argument('--source',type=Path,required=True);p.add_argument('--lane');p.add_argument('--context',type=json.loads);a=p.parse_args()
 if a.action=='open' and not a.lane:p.error('--lane is required for open')
 print(json.dumps(focus_agent(a.source.resolve(),a.context or {}) if a.action=='focus-agent' else open_window(a.source.resolve(),a.lane,a.context)))
if __name__=='__main__':
 os.umask(0o077)
 try:main()
 except (OSError,ValueError,RuntimeError,sp.SubprocessError) as e:sys.exit('Herdr window: '+str(e))
