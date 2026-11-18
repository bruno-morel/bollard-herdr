import {div} from 'gpui-kit';
import {v_flex} from 'gpui-base';
import {shared,setShared,layout,run,exec,appHome,theme,props,closeOverlay,terminals} from 'herdr';
import {button} from './ui.js';
import {laneIds,findNode,moveLane,placeLane,renameLane,removeLane,withoutLaneState} from './stream-tree.js';
import {leadFor} from './scope.js';
const KEYS=['repo.portrait.lanes','repo.portrait.views','repo.portrait.info','repo.portrait.browser','repo.portrait.questions'];
const name=c=>(c?.repo||'Repository')+' / '+(c?.stream||'Empty');
export function receiveMove(packet){
 const ack='repo.portrait.move-result';
 if(shared(ack)?.id===packet.id && !shared(ack)?.error)return;
 try{
  const lane=packet.replace||'moved-'+packet.id;
  const existing=findNode(layout(),lane+'-conversation');
  if(!packet.replace && existing){
   if(existing.content?.terminal!==packet.terminal)throw Error('Destination view identity changed.');
   setShared(ack,{id:packet.id,lane,terminal:packet.terminal});return;
  }
  const node=renameLane(packet.node,packet.lane,lane);
  let tree;
  if(packet.replace){
   if(Object.entries(shared('repo.portrait.unsaved')||{}).some(([k,v])=>k.startsWith(lane+':')&&v))throw Error('Save the destination editor draft first.');
   tree=JSON.parse(JSON.stringify(layout()));
   const current=findNode(tree,lane+'-lane');
   if(!current || shared(KEYS[0])?.[lane]?.terminal!==packet.terminal)throw Error('Destination changed; original view preserved.');
   Object.assign(current,node);
  }else tree=placeLane(layout(),node,packet.placement);
  // Bind state before layout so the manager never initializes this lane empty.
  for(const key of KEYS)setShared(key,{...(shared(key)||{}),[lane]:packet.state[key]});
  run('layout.set',{layout:tree});
  setShared(ack,{id:packet.id,lane,terminal:packet.terminal});
 }catch(e){setShared(ack,{id:packet.id,error:String(e)});}
}
export default class Move {
 init(_p,cx){this.source=null;this.destination=null;this.target=null;this.windows=null;this.busy=false;this.error='';this.done=false;
  const ids=laneIds(layout()).filter(id=>shared(KEYS[0])?.[id]);if(ids.length===1)this.source=ids[0];
 }
 render(cx){
  const t=theme(),configs=shared(KEYS[0])||{},ids=laneIds(layout()).filter(id=>configs[id]);
  let el=v_flex().p(14).gap(6).bg(t.surface).text_color(t.foreground).child(div().font_semibold().child('Move stream'));
  if(this.error)el=el.child(div().text_size(12).text_color(t.blocked).child(this.error));
  if(this.done)return el.child(div().child('Stream moved. Close this empty Herdr window?'))
   .child(button('move-close','Close this window',()=>run('app.quit'),{icon:'external'}))
   .child(button('move-keep','Keep empty window',()=>closeOverlay(props()?.overlay)));
  if(this.busy)return el.child(div().child('Opening destination… keeping the original view until it is ready.'));
  if(!this.source)return el.children(ids.map(id=>button('move-source-'+id,name(configs[id]),(_e,cx)=>{this.source=id;cx.notify();},{icon:'message'})));
  el=el.child(div().text_size(12).child(name(configs[this.source])));
  if(!this.destination)return el
   .child(button('move-here','Within this window',(_e,cx)=>{this.destination='here';cx.notify();},{icon:'columns'}))
   .child(button('move-other','To another window',(_e,cx)=>this.loadWindows(cx),{icon:'rows'}))
   .child(button('move-new','To a new window',(_e,cx)=>this.perform(cx,null,null,'new'),{icon:'external'}))
   .child(button('move-cancel','Cancel',()=>closeOverlay(props()?.overlay)));
  if(this.destination==='choose')return el.children((this.windows||[]).map(w=>button('move-window-'+w.home,w.title,(_e,cx)=>{this.destination=w;cx.notify();},{icon:'external'})))
   .when(!this.windows?.length,e=>e.child(div().child('No other open Bollard windows.')))
   .child(button('move-back','Back',(_e,cx)=>{this.destination=null;cx.notify();}));
  const targets=this.destination==='here'?ids.filter(id=>id!==this.source).map(id=>({id,label:name(configs[id])})):this.destination.lanes;
  if(!this.target)return el.children(targets.map(row=>button('move-target-'+row.id,row.label,(_e,cx)=>{this.target=row.id;cx.notify();},{icon:'message'})))
   .when(!targets.length,e=>e.child(div().child('There is no other stream in this window.')))
   .child(button('move-back','Back',(_e,cx)=>{this.destination=null;cx.notify();}));
  return el.child(div().text_size(12).child('Place relative to '+(targets.find(r=>r.id===this.target)?.label||this.target)))
   .children(['above','below','left','right'].map(position=>button('move-'+position,position[0].toUpperCase()+position.slice(1),(_e,cx)=>this.perform(cx,this.target,position),{icon:['left','right'].includes(position)?'columns':'rows'})))
   .child(button('move-back','Back',(_e,cx)=>{this.target=null;cx.notify();}));
 }
 loadWindows(cx){this.busy=true;cx.spawn(async cx=>{try{
  const r=await exec('python3',[appHome()+'/helpers/window.py','list-windows','--source',appHome()]);if(r.code)throw Error(r.stderr||r.stdout);
  this.windows=JSON.parse(r.stdout);this.destination='choose';
 }catch(e){this.error=String(e);}finally{this.busy=false;cx.notify();}});}
 perform(cx,target,position,mode=null){
  this.busy=true;this.error='';cx.spawn(async cx=>{try{
   const source=this.source;
   if(Object.entries(shared('repo.portrait.unsaved')||{}).some(([k,v])=>k.startsWith(source+':')&&v))throw Error('Save or discard the open editor draft before moving this stream.');
   if(this.destination==='here'){
    run('layout.set',{layout:moveLane(layout(),source,{target,position})});closeOverlay(props()?.overlay);return;
   }
   const original=findNode(layout(),source+'-lane');if(!original)throw Error('The original view is no longer open.');
   const node=JSON.parse(JSON.stringify(original));
   const sourceIdentity=JSON.stringify(shared(KEYS[0])?.[source]);
   const state=Object.fromEntries(KEYS.map(k=>[k,shared(k)?.[source]??null]));
   const lead=leadFor(terminals(),state[KEYS[0]]);
   state[KEYS[0]]={...state[KEYS[0]],terminal:lead?.address||state[KEYS[0]]?.terminal};
   const id=this.moveId||(this.moveId=Date.now().toString(36));
   const packet={id,lane:source,node,state,terminal:state[KEYS[0]].terminal,placement:{target,position},destination:mode==='new'?'new':this.destination.home};
   if(lead)findNode(node,source+'-conversation').content={terminal:lead.address};
   const r=await exec('python3',[appHome()+'/helpers/window.py','move-view','--source',appHome(),'--lane',source,'--context',JSON.stringify(packet)]);
   if(r.code)throw Error(r.stderr||r.stdout||'Destination did not confirm the view. Original preserved.');
   if(JSON.stringify(shared(KEYS[0])?.[source])!==sourceIdentity)throw Error('The source view changed while moving. Both views were preserved.');
   // Remove only after the destination verified its terminal binding.
   const last=laneIds(layout()).length===1;
   run('layout.set',{layout:removeLane(layout(),source)});
   for(const key of KEYS)setShared(key,withoutLaneState(shared(key),source));
   setShared('repo.open-requests',Object.fromEntries(Object.entries(shared('repo.open-requests')||{}).filter(([,r])=>r?.lane!==source)));
   if(last)this.done=true;else closeOverlay(props()?.overlay);
  }catch(e){this.error=String(e);}finally{this.busy=false;cx.notify();}});
 }
}
