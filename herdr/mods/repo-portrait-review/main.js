import {reportPanel} from './signals.js';
import {showAccount} from './account-pane.js';
import {askHelper} from './helper.js';
import {button as control,toolColors} from './ui.js';
import { scopedLocation, scopedRequest, leadFor } from './scope.js';
import { View, div } from 'gpui-kit';
import { v_flex, h_flex, TextView } from 'gpui-base';
import { spaces, panes, terminals, focused, props, shared, setShared, exec, theme, run, notify, openOverlay, nextCommand } from 'herdr';
import { selectLocation, selectRequest } from './routing.js';
const location=()=>scopedLocation();
const CACHE='repo.review-cache';
const labelState=s=>['preflight','reviewing'].includes(s);
export default class Review extends View {
 init(_props,cx){
  if(props()?.header)return;
  cx.timer.every(15000,cx=>this.refresh(cx));
  this.reviewers={};
  this.compact=!!props()?.compact;this.busy=new Set();this.context=null;this.message='';this.actionError=false;this.actionBusy=false;this.accountAddress=null;this.readSeen=new Set();this.namedTabs=new Set();
  this.seen=JSON.parse(localStorage.getItem('review.seen')||'{}');
  if(this.compact){cx.timer.every(15000,cx=>this.refresh(cx));this.refresh(cx);}
  else cx.spawn(async cx=>{for(;;){const c=await nextCommand();
   if(c.startsWith('new-cycle:')){const context=JSON.parse(decodeURIComponent(c.slice(10)));if(context.key===location()?.key)this.act('--new-cycle',cx,context);}
   if(c==='refresh')this.refresh(cx,true);
   if(c==='login:'+props()?.lane)this.login(cx);cx.notify();}});
 }
 reviewer(c){return this.reviewers[c?.key]||(shared(CACHE)||{})[c?.key]?.reviewer||'claude';}
 targets(){const here=location();return here?[here]:[];}
 refresh(cx,force=false){for(const target of this.targets()){if(force){const old=(shared(CACHE)||{})[target.key];if(old)setShared(CACHE,{...(shared(CACHE)||{}),[target.key]:{...old,readiness:null}});}this.fetch(target,cx);}}
 fetch(context,cx){
  if(this.busy.has(context.key))return;this.busy.add(context.key);
  cx.spawn(async cx=>{try{
   const r=await exec('work',['review','--status','--json'],{cwd:context.cwd,on:context.on});
   if(r.code)throw new Error(r.stderr.trim()||r.stdout.trim()||'Review status unavailable');
   const s=JSON.parse(r.stdout);
   const completion=await exec('work',['complete',context.stream,'--status','--json'],{cwd:context.cwd,on:context.on});
   s.completion=completion.code?{state:'unavailable',missing:[(completion.stderr||completion.stdout).trim()]}:JSON.parse(completion.stdout);
   const reviewer=this.reviewer(context),oldReady=(shared(CACHE)||{})[context.key]?.readiness;
   if(!oldReady||oldReady.reviewer!==reviewer||Date.now()-oldReady.checked>60000){
    const d=await exec('work',['review','--doctor','--json','--reviewer',reviewer],{cwd:context.cwd,on:context.on});
    s.readiness=d.code?{ready:false,message:(d.stderr||d.stdout).trim(),checked:Date.now()}:{...JSON.parse(d.stdout),checked:Date.now()};
   }else s.readiness=oldReady;
   const cache={...(shared(CACHE)||{}),[context.key]:{...s,checked:Date.now(),on:context.on}};setShared(CACHE,cache);
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
 checkCompletion(cx){
  const context=location();if(!context||this.actionBusy)return;this.actionBusy=true;
  cx.spawn(async cx=>{try{
   const r=await exec('work',['complete',context.stream,'--status','--record','--json'],{cwd:context.cwd,on:context.on});
   if(r.code)throw new Error(r.stderr||r.stdout);
   const completion=JSON.parse(r.stdout),old=(shared(CACHE)||{})[context.key]||{};
   setShared(CACHE,{...(shared(CACHE)||{}),[context.key]:{...old,completion}});
   if(location()?.key===context.key)this.message=completion.state+' · '+completion.message;
  }catch(e){if(location()?.key===context.key)this.message=String(e);}
  finally{this.actionBusy=false;cx.notify();}});
 }
 act(flag,cx,target=null){
  const context=target||location();if(!context||this.actionBusy)return;this.actionBusy=true;this.message='';this.actionError=false;
  cx.spawn(async cx=>{try{
   const args=['review','--reviewer',context.reviewer||this.reviewer(context)];if(flag)args.push(flag);
   const r=await exec('work',args,{cwd:context.cwd,on:context.on});
   if(location()?.key!==context.key)return;
   this.message=(r.code?(r.stderr||r.stdout):r.stdout).trim()|| (r.code?'Review could not start':'Review requested');
   this.actionError=!!r.code;
   if(r.code)notify({title:'Review needs attention',body:this.message,level:'warning'});
   const old=(shared(CACHE)||{})[context.key];if(old)setShared(CACHE,{...(shared(CACHE)||{}),[context.key]:{...old,readiness:null}});
   this.fetch(context,cx);
  }catch(e){if(location()?.key===context.key){this.message=String(e);this.actionError=true;}notify({title:'Review needs attention',body:String(e),level:'warning'});}finally{this.actionBusy=false;cx.notify();}});
 }
 login(cx){
  const c=location();if(!c||this.actionBusy)return;this.actionBusy=true;this.message='Opening reviewer sign-in…';cx.notify();
  cx.spawn(async cx=>{try{
   const lead=leadFor(terminals(),c),args=['login',this.reviewer(c)];if(lead)args.push('--lead',lead.address.split('/').pop());
   const r=await exec('repo-provider.py',args,{cwd:c.cwd,on:c.on});if(r.code)throw new Error(r.stderr||r.stdout);
   const row=JSON.parse(r.stdout);
   if(row.connected){if(location()?.key===c.key)this.message=row.message;this.accountAddress=null;this.refresh(cx,true);notify({title:'Reviewer connected',body:row.message,level:'success'});return;}
   if(!row.terminal)throw new Error('Reviewer sign-in did not return an account terminal.');
   this.accountAddress=(c.on?c.on+'/':'')+row.terminal;showAccount(this.accountAddress,cx,(message,next)=>{if(location()?.key===c.key)this.message=message;next.notify();});
   if(location()?.key===c.key)this.message='Complete sign-in in the account pane, then click Check again here.';
  }catch(e){if(location()?.key===c.key)this.message=String(e);notify({title:'Reviewer sign-in needs attention',body:String(e),level:'warning'});}
  finally{this.actionBusy=false;cx.notify();}});
 }
 openInputs(cx){
  const c=location();if(!c)return;
  cx.spawn(async cx=>{try{const r=await exec('repo-read',['--show','docs/handoffs/'+c.stream+'/review-input.json'],{cwd:c.cwd,on:c.on});if(r.code)throw new Error(r.stderr||r.stdout);}
   catch(e){if(location()?.key===c.key)this.message=String(e);cx.notify();}});
 }
 button(id,title,fn,style={}){return control(id,title,fn,style);}
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
  if(this.context?.key!==context?.key){this.context=context;this.message='';this.actionError=false;if(context)this.fetch(context,cx);}
  reportPanel('review',context,this.actionError||s?.error||['incomplete','changes-required'].includes(s?.state));
  const completion=s?.completion;
  const ready=s?.readiness;const account=ready?.account||ready?.claude;const inputs=ready?.inputs;
  const title=s?.title||'Review';const running=labelState(s?.state);const color=s?.state==='verified'?t.ansi2:['incomplete','changes-required','stale'].includes(s?.state)?t.blocked:running?t.working:t.muted;
  if(this.compact)return v_flex().w_full().p(12).gap(5).border_t(1).border_color(t.border).bg(t.chrome)
   .child(h_flex().items_center().justify_between().child(div().text_size(11).text_color(t.dim).child('FEATURE REVIEW'))
     .child(this.button('review-open','Open',()=>run('layout.select',{stack:'read-review',child:'review-panel'}))))
   .child(div().text_size(12).text_color(color).truncate().child(title))
   .child(div().text_size(10).text_color(t.dim).truncate().child(s?.stream?`${s.stream} · ${s.remaining}/2 review attempts left`:'Select a stream to review'))
   .when(running,el=>el.child(div().h(3).rounded(2).bg(t.border).child(div().w(60).h(3).bg(t.working).loop('opacity',{from:.3,to:1,period:1500}))));
  let el=v_flex().id('review-panel').size_full().p(4).min_h(0).min_w(0).rounded(10).border_1().border_color(t.border).bg(toolColors().background).text_color(t.foreground)
   .child(h_flex().flex_none().px(14).py(8).gap(8).flex_wrap().items_center().border_b(1).border_color(t.border)
    .child(div().flex_1().font_semibold().child('Review'))
    .when(!!context&&!running&&!this.actionBusy,e=>e.child(h_flex().gap(3).children(['claude','codex','cursor'].map(a=>this.button('reviewer-'+a,a,(_e,cx)=>{this.reviewers[context.key]=a;this.refresh(cx,true);cx.notify();},{selected:this.reviewer(context)===a})))))
    .when(!!s?.stream&&!running&&!this.actionBusy,el=>el.child(h_flex().gap(4).flex_wrap().justify_end()
     .child(this.button('review-prepare',inputs?.exists?'Open inputs':'Prepare inputs',(_e,cx)=>inputs?.exists?this.openInputs(cx):this.act('--prepare',cx),{icon:'book',strong:true}))
     .when(!!ready?.ready&&ready.reviewer===this.reviewer(context)&&!s.calls,el=>el.child(this.button('review-start','Start review',(_e,cx)=>this.act('',cx),{icon:'shield',strong:true})))
     .when(!!ready?.ready&&ready.reviewer===this.reviewer(context)&&s.calls===1,el=>el.child(this.button('review-follow','Review fixes',(_e,cx)=>this.act('--follow-up',cx),{icon:'shield',strong:true})))
     .when(!!ready?.ready&&ready.reviewer===this.reviewer(context)&&s.calls>=2,el=>el.child(this.button('review-new','New review cycle',()=>openOverlay({mod:'confirm',kind:'dialog',width:430,height:230,props:{title:'Authorize another review cycle?',detail:'This allows up to two more review attempts, each capped at 20 minutes. Claude uses Sonnet with 24 turns. Your prior reports stay in the repository.',command:{name:'repo-portrait-review.new-cycle:'+encodeURIComponent(JSON.stringify({...context,reviewer:this.reviewer(context)}))}}}),{icon:'shield',strong:true})))))
    .when(!!s?.report_markdown,e=>e.child(this.button('review-helper','Ask a helper',()=>askHelper(context,{pane:'review',source:s.report||'Review report · '+(s.cycle||s.state),text:'Recorded verdict: '+s.state+' · cycle '+(s.cycle||'unknown')+'\n\n'+s.report_markdown,observed_at:s.updated}),{icon:'agents'})))
    .when(!!context&&!this.actionBusy,e=>e.child(this.button('completion-check','Check completion',(_e,cx)=>this.checkCompletion(cx),{icon:'shield',strong:true})))
    .child(this.button('review-refresh','Refresh',(_e,cx)=>this.refresh(cx,true),{icon:'refresh',compact:true})))
   .child(v_flex().px(14).py(10).gap(5).max_h(220).overflow_y_scrollbar().border_b(1).border_color(t.border)
    .child(h_flex().gap(8).items_center().flex_wrap()
     .child(div().font_semibold().child('Completion'))
     .child(div().px(7).py(3).rounded(5).bg(t.chrome).text_color(completion?.risk==='high'?t.blocked:completion?.risk==='medium'?t.working:t.muted).child((completion?.risk||'unassessed').toUpperCase()))
     .child(div().text_size(12).text_color(completion?.state==='completed'?t.ansi2:t.muted).child(completion?.state||'Checking existing evidence…')))
    .when(!!completion?.scope,e=>e.child(div().text_size(12).child(completion.scope)))
    .children((completion?.checks||[]).map(x=>div().text_size(12).text_color(x.status==='passed'?t.ansi2:t.muted).child((x.status==='passed'?'✓ ':'○ ')+x.id+' · '+x.detail)))
    .children((completion?.missing||[]).map(x=>div().text_size(12).text_color(t.blocked).child('Missing: '+x)))
    .children((completion?.limitations||[]).map(x=>div().text_size(12).text_color(t.muted).child('Limitation: '+x)))
    .child(div().text_size(11).text_color(t.dim).child('Existing evidence only · no test rerun or Claude call')))
   .child(v_flex().p(14).gap(8).flex_none()
    .child(div().text_size(17).font_semibold().text_color(color).child(title))
    .child(div().text_size(12).text_color(t.muted).child(s?.stream?`${this.reviewer(context)} · ${s.remaining}/2 attempts left`:'Select an existing Studio/Work stream.'))
    .child(div().text_size(12).text_color(t.dim).child(s?.phase||'One initial review + one follow-up. 20 minutes each; Claude: Sonnet, 24 turns.'))
    .when(!!ready&&!ready.ready&&!running,e=>e.child(v_flex().p(10).gap(7).rounded(8).bg(t.chrome)
     .child(div().font_semibold().text_size(13).child('Review needs setup'))
     .when(!!account&&!account.ready,e=>e
      .child(div().text_size(12).child(account.message))
      .child(h_flex().gap(6).items_center().justify_end().flex_wrap()
       .when(account.code==='sign-in'||account.code==='subscription',e=>e.child(this.button('review-login','Sign in to '+this.reviewer(context),(_e,cx)=>this.login(cx),{icon:'agents',strong:true})))
       .when(account.code==='not-installed',e=>e.child(this.button('review-install','Install guide',(_e,cx)=>cx.open_url(account.guide),{icon:'book'})))
       .when(!!this.accountAddress,e=>e.child(this.button('review-account-open','Open sign-in',(_e,cx)=>showAccount(this.accountAddress,cx,(message,next)=>{this.message=message;next.notify();}),{icon:'message'})))
       .child(this.button('review-copy','Copy command',(_e,cx)=>cx.write_to_clipboard(account.command),{icon:'copy'}))
       .child(this.button('review-check','Check again',(_e,cx)=>this.refresh(cx,true),{icon:'refresh'})))
      .child(div().text_size(12).text_color(t.muted).child('On '+(context?.on||'this computer')+': '+account.command)))
     .when(!!inputs&&!inputs.ready,e=>e.child(div().text_size(12).child(inputs.message+' '+(inputs.exists?'Open inputs to complete them.':'Click Prepare inputs above.'))))
     .when(!account,e=>e.child(div().text_size(12).child(ready.message)))
     .child(div().text_size(11).text_color(t.dim).child('No Claude call is used for setup or sign-in checks.'))))
    .when(!!s?.reason,el=>el.child(div().text_size(12).text_color(t.blocked).child(s.reason)))
    .when(!!s?.error,el=>el.child(div().text_size(12).text_color(t.dim).child(s.error)))
    .when(this.actionBusy,el=>el.child(div().text_size(12).text_color(t.muted).child('Working on your request…')))
    .when(!!this.message,el=>el.child(div().text_size(12).text_color(t.muted).child(this.message))));
  if(s?.report_markdown)el=el.child(TextView.markdown('review-report-'+s.updated,s.report_markdown).selectable(true).scrollable(true).p(16).flex_1().min_h(0));
  else el=el.child(TextView.markdown('review-guide',`### Before starting\n\n1. The implementation agent completes the feature and its normal checks.\n2. Prepare inputs, then fill every acceptance criterion and the actual check commands in \`review-input.json\` beside the handoff.\n3. Start review and pause overlapping edits. The selected independent provider checks implementation and test quality. Claude also supports up to three declared check reruns.\n4. The implementation agent fixes findings. Review fixes uses the single follow-up.\n\n**Incomplete evidence stays incomplete.** Changed source or requirements invalidate approval. A finished agent turn is not a quality verdict.\n\nReports stay in Git; raw logs stay in ignored scratch/. Direct Git pushes are outside this local review gate.`).scrollable(true).p(16).flex_1().min_h(0));
  return el;
 }
}
