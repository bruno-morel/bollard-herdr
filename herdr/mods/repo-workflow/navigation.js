import {addLane,laneIds} from './stream-tree.js';
import { shared,setShared,terminals,exec,hc,run,notify,appHome,layout } from 'herdr';
const PENDING='repo.open-requests';
const qualify=(on,id)=>on&&id&&!id.startsWith(on+'/')?on+'/'+id:id;
const machine=address=>address.includes('/')?address.slice(0,address.lastIndexOf('/')):null;
export function showConversation(t,on,lane=null,options={}){
 if(options.placement){
  const id='lane-'+Date.now().toString(36),tree=addLane(layout(),id,options.placement);
  run('layout.set',{layout:tree});lane=id;
 }
 const space=qualify(on,t.labels?.['herdr.space']),tab=qualify(on,t.labels?.['herdr.tab']);
 if(lane){const old=shared('repo.portrait.lanes')||{};setShared('repo.portrait.lanes',{...old,[lane]:{...old[lane],on,repo:options.repo||(t.labels?.['repo-tools.checkout']||t.cwd).split('-worktrees/')[0].split('/').pop(),cwd:t.labels?.['repo-tools.checkout']||t.cwd,stream:t.labels?.['repo-tools.stream'],role:t.labels?.['repo-tools.role'],terminal:qualify(on,t.address)}});}
 if(space)run('space.select',{id:space});if(tab)run('tab.select',{id:tab});
 run('pane.focus',{terminal:qualify(on,t.address)});
}
export async function showInWindow(t,on,lane,options={}){
 lane=laneIds(layout()).includes(lane)?lane:laneIds(layout())[0];
 if(!lane)throw Error('Open the Studio / Work layout before opening a stream window.');
 const cwd=t.labels?.['repo-tools.checkout']||t.cwd;
 const context={on,cwd,stream:t.labels?.['repo-tools.stream'],role:t.labels?.['repo-tools.role'],terminal:qualify(on,t.address),repo:options.repo||cwd.split('-worktrees/')[0].split('/').pop()};
 const r=await exec('python3',[appHome()+'/helpers/window.py','open','--source',appHome(),'--lane',lane,'--context',JSON.stringify(context)]);
 if(r.code)throw Error(r.stderr||r.stdout||'Could not open the stream window.');
 notify({title:'Separate Herdr window',body:JSON.parse(r.stdout).message,level:'success'});
}
export async function openExisting(cwd,stream,role,on,lane,newWindow=false,options={}){
 const path=await exec('work',['path',stream],{cwd,on});if(path.code)return false;
 const root=path.stdout.trim();
 const candidates=terminals().filter(t=>t.state==='live'&&machine(t.address)===on&&t.labels?.['repo-tools.role']===role&&t.labels?.['repo-tools.stream']===stream);
 const matches=[];
 for(const row of candidates){
  const checkout=row.labels?.['repo-tools.checkout']||row.cwd;if(!checkout)continue;
  // Git/runtime records can preserve different case or symlink spellings on macOS.
  // Ask the remote filesystem; never lowercase paths on case-sensitive machines.
  const same=checkout===root?true:(await exec('python3',['-c','import os,sys; sys.exit(0 if os.path.samefile(sys.argv[1],sys.argv[2]) else 1)',root,checkout],{cwd,on})).code===0;
  if(same)matches.push(row);
 }
 if(matches.length>1)throw new Error('Multiple live '+role+' conversations match this checkout. Select the intended conversation.');
 if(!matches.length)return false;if(newWindow)await showInWindow(matches[0],on,lane,options);else showConversation(matches[0],on,lane,options);return true;
}
export function watchOpen(request){setShared(PENDING,{...(shared(PENDING)||{}),[qualify(request.on,request.terminal)]:{...request,time:Date.now()}});}
export async function followOpens(){
 for(const [id,p] of Object.entries(shared(PENDING)||{})){
  if(p.claimedAt&&Date.now()-p.claimedAt<60000)continue;
  const pending=shared(PENDING)||{};if(!pending[id]||pending[id].claimedAt&&Date.now()-pending[id].claimedAt<60000)continue;
  setShared(PENDING,{...pending,[id]:{...p,claimedAt:Date.now()}});
  let remove=false;
  try{
   const r=await exec('work',['flow','status',p.stream],{cwd:p.cwd,on:p.on});
   if(r.code)continue;
   const state=JSON.parse(r.stdout);
   if(state.terminal!==id.split('/').pop())continue;
   if(['ready','preparing','implementing','fixing','reviewing','verified'].includes(state.state)&&state.lead){
    const result=await hc(['get',qualify(p.on,state.lead),'--json']);if(result.code)continue;const row=JSON.parse(result.stdout);if(p.newWindow)await showInWindow(row,p.on,p.lane,p);else showConversation(row,p.on,p.lane,p);remove=true;
   }else if(state.state==='needs-you'){
    notify({title:p.stream+' needs attention',body:state.message,level:'warning',action:{name:'pane.focus',args:{terminal:qualify(p.on,id)}}});remove=true;
   }
  }catch(e){if(p.newWindow){notify({title:'Stream window needs attention',body:String(e)+' The stream is preserved; select it from Add stream to retry.',level:'warning'});remove=true;}}finally{const pending=shared(PENDING)||{};if(pending[id]){const updated={...pending[id]};delete updated.claimedAt;setShared(PENDING,{...pending,[id]:updated});}}
  if(Date.now()-p.time>900000)remove=true;
  if(remove){const next={...(shared(PENDING)||{})};delete next[id];setShared(PENDING,next);}
 }
}
