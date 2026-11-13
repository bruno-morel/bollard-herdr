import { View, div } from 'gpui-kit';
import { v_flex, h_flex, TextView } from 'gpui-base';
import { spaces, panes, terminals, focused, props, shared, setShared, exec, theme, run, notify, openOverlay, nextCommand } from 'herdr';
import { selectLocation, selectRequest } from './routing.js';
const location=()=>selectLocation(terminals(),spaces(),panes(),focused());
const CACHE='repo.review-cache';
const labelState=s=>['preflight','reviewing'].includes(s);
export default class Review extends View {
 init(_props,cx){
  if(props()?.header)return;
  this.reviewers={};
  this.compact=!!props()?.compact;this.busy=new Set();this.context=null;this.message='';this.actionBusy=false;this.readSeen=new Set();this.namedTabs=new Set();
  this.seen=JSON.parse(localStorage.getItem('review.seen')||'{}');
  if(this.compact){cx.timer.every(15000,cx=>this.refresh(cx));this.refresh(cx);}
  else cx.spawn(async cx=>{for(;;){const c=await nextCommand();
   if(c.startsWith('new-cycle:')){const context=JSON.parse(decodeURIComponent(c.slice(10)));this.act('--new-cycle',cx,context);}
   if(c==='refresh')this.refresh(cx);cx.notify();}});
 }
 targets(){
  const list=new Map(),here=location();if(here)list.set(here.key,here);
  // Only connected, visible streams; no directory scanning or agent prompts.
  const ps=panes();
  for(const s of spaces())for(const p of ps.filter(p=>s.tabs.some(t=>t.id===p.tab))){
   const t=terminals().find(t=>t.address===p.terminal),cwd=t?.labels?.['repo-tools.checkout']||p.cwd;
   if(!cwd||!(p.branch?.startsWith('codex/')||s.branch?.startsWith('codex/')||t?.labels?.['repo-tools.stream']))continue;
   const on=s.machine??null,key=JSON.stringify([on,cwd]);list.set(key,{cwd,on,key});
  }return [...list.values()];
 }
 refresh(cx){for(const target of this.targets())this.fetch(target,cx);}
 fetch(context,cx){
  if(this.busy.has(context.key))return;this.busy.add(context.key);
  cx.spawn(async cx=>{try{
   const r=await exec('work',['review','--status','--json'],{cwd:context.cwd,on:context.on});
   if(r.code)throw new Error(r.stderr.trim()||r.stdout.trim()||'Review status unavailable');
   const s=JSON.parse(r.stdout);const cache={...(shared(CACHE)||{}),[context.key]:{...s,checked:Date.now(),on:context.on}};setShared(CACHE,cache);
   const seen=shared('repo.review-seen')||this.seen;
   const old=seen[context.key],stamp=JSON.stringify([s.cycle,s.attempt,s.state]);
   if(old&&old!==stamp&&['verified','changes-required','incomplete','stale'].includes(s.state)){
    const space=spaces().find(x=>x.machine===context.on&&(x.folder===context.cwd||panes().some(p=>x.tabs.some(t=>t.id===p.tab)&&p.cwd===context.cwd)));
    notify({title:`${s.stream}: ${s.title}`,body:s.reason||'The review report is ready.',level:s.state==='verified'?'success':'warning',timeout:9000,
     ...(space?{action:{name:'space.select',args:{id:space.id}}}:{})});
   }
   this.seen={...seen,[context.key]:stamp};setShared('repo.review-seen',this.seen);localStorage.setItem('review.seen',JSON.stringify(this.seen));
  }catch(e){setShared(CACHE,{...(shared(CACHE)||{}),[context.key]:{error:String(e),checked:Date.now()}});}
  finally{this.busy.delete(context.key);cx.notify();}});
 }
 act(flag,cx,target=null){
  const context=target||location();if(!context||this.actionBusy)return;this.actionBusy=true;this.message='';
  cx.spawn(async cx=>{try{
   const args=['review','--reviewer',context.reviewer||this.reviewers[context.key]||'claude'];if(flag)args.push(flag);
   const r=await exec('work',args,{cwd:context.cwd,on:context.on});
   this.message=(r.code?r.stderr:r.stdout).trim()|| (r.code?'Review could not start':'Review requested');
   if(r.code)notify({title:'Review needs attention',body:this.message,level:'warning'});
   this.fetch(context,cx);
  }catch(e){this.message=String(e);}finally{this.actionBusy=false;cx.notify();}});
 }
 button(id,title,fn){const t=theme();return div().id(id).px(9).py(6).rounded(5).text_size(12).text_color(t.accent).hover(s=>s.bg(t.hover)).cursor_pointer().on_click(fn).child(title);}
 render(cx){
  if(props()?.header){const t=theme();return h_flex().w_full().h(32).px(8).gap(4).items_center().bg(t.chrome)
    .child(this.button('tab-read','READ',()=>run('layout.select',{stack:'read-review',child:'read-panel'})))
    .child(this.button('tab-review','Review',()=>run('layout.select',{stack:'read-review',child:'review-panel'})));}

  if(this.compact){
   const all=terminals(),ss=spaces(),ps=panes(),request=selectRequest(all,ss,ps,focused());
   for(const space of ss)for(const tab of space.tabs){
    if(!tab.named&&!this.namedTabs.has(tab.id)&&ps.some(p=>p.tab===tab.id&&all.some(t=>t.address===p.terminal&&t.labels?.['repo-tools.role']==='review'))){
     this.namedTabs.add(tab.id);run('tab.rename',{id:tab.id,name:'Review'});
    }
   }
   if(request&&!this.readSeen.has(request.key)){
    this.readSeen.add(request.key);let acknowledged=false;
    try{acknowledged=JSON.parse(all.find(t=>t.address===request.address)?.labels?.['repo-read.result']||'{}').id===request.id;}catch{}
    if(!acknowledged)run('layout.select',{stack:'read-review',child:'read-panel'});
   }
  }
  const context=location(),t=theme(),s=context?(shared(CACHE)||{})[context.key]:null;
  if(this.context?.key!==context?.key){this.context=context;this.message='';if(context)this.fetch(context,cx);}
  const title=s?.title||'Review';const running=labelState(s?.state);const color=s?.state==='verified'?t.ansi2:['incomplete','changes-required','stale'].includes(s?.state)?t.blocked:running?t.working:t.muted;
  if(this.compact)return v_flex().w_full().p(12).gap(5).border_t(1).border_color(t.border).bg(t.chrome)
   .child(h_flex().items_center().justify_between().child(div().text_size(11).text_color(t.dim).child('FEATURE REVIEW'))
     .child(this.button('review-open','Open',()=>run('layout.select',{stack:'read-review',child:'review-panel'}))))
   .child(div().text_size(12).text_color(color).truncate().child(title))
   .child(div().text_size(10).text_color(t.dim).truncate().child(s?.stream?`${s.stream} · ${s.calls||0} review calls recorded`:'Select a stream to review'))
   .when(running,el=>el.child(div().h(3).rounded(2).bg(t.border).child(div().w(60).h(3).bg(t.working).loop('opacity',{from:.3,to:1,period:1500}))));
  let el=v_flex().id('review-panel').size_full().min_h(0).min_w(0).rounded(10).border_1().border_color(t.border).bg(t.background).text_color(t.foreground)
   .child(h_flex().h(42).flex_none().px(14).items_center().border_b(1).border_color(t.border)
    .child(div().flex_1().font_semibold().child('REVIEW'))
    .child(this.button('review-refresh','Refresh',(_e,cx)=>this.refresh(cx))))
   .child(v_flex().p(14).gap(8).flex_none()
    .child(div().text_size(17).font_semibold().text_color(color).child(title))
    .child(div().text_size(12).text_color(t.muted).child(s?.stream?`${s.stream} · Sonnet · subscription limits apply`:'Select an existing Studio/Work stream.'))
    .child(div().text_size(12).text_color(t.dim).child(s?.phase||'No fixed call cap. Claude: 24 turns / 20 minutes each.'))
    .when(!!s?.reason,el=>el.child(div().text_size(12).text_color(t.blocked).child(s.reason)))
    .when(!!s?.error,el=>el.child(div().text_size(12).text_color(t.dim).child(s.error)))
    .when(!!s?.stream&&!running&&!this.actionBusy,el=>el.child(h_flex().gap(4).flex_wrap()
     .child(this.button('review-prepare','Prepare inputs',(_e,cx)=>this.act('--prepare',cx)))
     .when(!s.calls,el=>el.child(this.button('review-start','Start review',(_e,cx)=>this.act('',cx))))
     .when(s.calls>0,el=>el.child(this.button('review-follow','Review fixes',(_e,cx)=>this.act('--follow-up',cx))))))
    .when(this.actionBusy,el=>el.child(div().text_size(12).text_color(t.muted).child('Preparing review…')))
    .when(!!this.message,el=>el.child(div().text_size(12).text_color(t.muted).child(this.message))));
  if(s?.report_markdown)el=el.child(TextView.markdown('review-report-'+s.updated,s.report_markdown).selectable(true).scrollable(true).p(16).flex_1().min_h(0));
  else el=el.child(TextView.markdown('review-guide',`### Before starting\n\n1. The implementation agent completes the feature and its normal checks.\n2. Prepare inputs, then fill every acceptance criterion and the actual check commands in \`review-input.json\` beside the handoff.\n3. Start review and pause overlapping edits. The selected independent provider checks implementation and test quality. Claude also supports up to three declared check reruns.\n4. The implementation agent fixes findings. Review fixes requests another focused review.\n\n**Incomplete evidence stays incomplete.** Changed source or requirements invalidate approval. A finished agent turn is not a quality verdict.\n\nReports stay in Git; raw logs stay in ignored scratch/. Direct Git pushes are outside this local review gate.`).scrollable(true).p(16).flex_1().min_h(0));
  return v_flex().size_full().child(h_flex().gap(5).children(['claude','codex','cursor'].map(a=>this.button('reviewer-'+a,(this.reviewers[context?.key]===a?'✓ ':'')+a,(_e,cx)=>{if(context&&!running){this.reviewers[context.key]=a;cx.notify();}})))).child(el.flex_1());
 }
}
