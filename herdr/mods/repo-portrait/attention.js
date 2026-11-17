import {exec,appHome,notify,run,closeOverlay,openOverlay} from 'herdr';
export function attentionRows(rows){
 const seen=new Set();
 return rows.filter(r=>{
  if(r.state!=='live'||!r.address||seen.has(r.address))return false;
  const status=typeof r.status==='string'?r.status:r.status?.state;
  const done=status==='done' && !(r.turn!=null && Number(r.labels?.['herdr.seen']??-1)>=r.turn);
  if(status!=='blocked'&&!done)return false;
  seen.add(r.address);return true;
 }).map(r=>{
  const l=r.labels||{},status=typeof r.status==='string'?r.status:r.status?.state;
  const cwd=l['repo-tools.checkout']||r.cwd||'';
  return {...r,reason:status==='blocked'?'Waiting for input':'Unread response',
   display:(l['repo-tools.stream']||r.title||r.name||r.address),
   context:{terminal:r.address,parent:r.parent,on:r.address.includes('/')?r.address.slice(0,r.address.lastIndexOf('/')):null,
    cwd,stream:l['repo-tools.stream'],role:l['repo-tools.role']}};
 }).sort((a,b)=>(a.reason==='Waiting for input'?0:1)-(b.reason==='Waiting for input'?0:1)||a.display.localeCompare(b.display));
}
export async function focusAttention(row){
 try{
  const r=await exec('python3',[appHome()+'/helpers/window.py','focus-agent','--source',appHome(),'--context',JSON.stringify(row.context)]);
  if(r.code)throw Error(r.stderr||r.stdout);
  const result=JSON.parse(r.stdout);
  if(!result.found)openOverlay({mod:'repo-portrait',kind:'popup',width:370,props:{kind:'layout-menu',operation:'add',attention:row}});
 }catch(e){notify({title:'Cannot show waiting agent',body:String(e),level:'warning'});}
}

// Queue navigation on the persistent manager before disposing of a popup.
export function requestAttention(row,overlay){
 run('repo-portrait.attention-open:'+encodeURIComponent(JSON.stringify({address:row.address,context:row.context})));
 if(overlay)closeOverlay(overlay);
}
