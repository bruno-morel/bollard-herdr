import {publishedPorts} from './docker-ports.js';
import {scopedAgents,agentTree,statusKind,memoryReading} from './agent-cards.js';
import {showAccount} from './account-pane.js';
import {View,div} from 'gpui-kit';
import {v_flex,h_flex} from 'gpui-base';
import {exec,theme,props,terminals,shared,run,settings,notify} from 'herdr';
import {scopedLocation,leadFor,machineOf} from './scope.js';
import {button,caption,INFO,info,toolColors} from './ui.js';
import {quotaCard,meterCard,meter,stat,badge,level,palette,number,duration,count} from './metrics.js';
export function resetNote(epoch,now=Date.now()){
 if(!Number.isFinite(Number(epoch))||Number(epoch)<=0)return 'Reset not reported';
 const seconds=Number(epoch)-now/1000;if(seconds<=0)return 'Reset due · refresh for the new allowance';
 const days=Math.floor(seconds/86400),hours=Math.floor(seconds%86400/3600),minutes=Math.ceil(seconds%3600/60);
 return 'Resets in '+(days?days+' day'+(days===1?'':'s')+' '+hours+'h':hours?hours+'h '+minutes+'m':minutes+'m')+' · '+new Date(epoch*1000).toLocaleString();
}
const state=r=>typeof r.status==='string'?r.status:r.status?.state;
export function relatives(c){return scopedAgents(terminals(),c);}
export default class Info extends View {
 init(_p,cx){this.agentDetails={};this.key=null;this.data=null;this.services=null;this.git='';this.providers=null;this.codexData=null;this.accountBusy=false;this.accountMessage='';this.accountAddress=null;this.busy=false;this.error='';cx.timer.every(30000,cx=>this.refresh(cx));}
 refresh(cx,force=false){const c=scopedLocation(),tab=(shared(INFO)||{})[props()?.lane];if(!c||this.busy||(!force&&!tab))return;this.busy=true;const lead=leadFor(terminals(),c),key=c.key,requestKey=this.key;const current=()=>this.key===requestKey&&scopedLocation()?.key===key;
 cx.spawn(async cx=>{try{
  if(tab==='agents'){
   const rows=relatives(c);const results=await Promise.allSettled(rows.map(async row=>{const r=await exec('repo-panel.py',['metadata',row.address.split('/').pop()],{cwd:row.labels?.['repo-tools.checkout']||row.cwd,on:c.on});return [row.address,r.code?{note:'Metadata unavailable'}:JSON.parse(r.stdout)];}));
   if(!current())return;this.agentDetails=Object.fromEntries(results.map((result,i)=>result.status==='fulfilled'?result.value:[rows[i].address,{note:'Metadata unavailable'}]));
  }
  if(['context','usage'].includes(tab)&&lead){const r=await exec('repo-panel.py',['metadata',lead.address.split('/').pop()],{cwd:c.cwd,on:c.on});if(!current())return;if(r.code)throw new Error(r.stderr||r.stdout);this.data=JSON.parse(r.stdout);}
  if(tab==='usage'){
   const result=await exec('repo-provider.py',['status',...(force?['--force']:[])],{cwd:c.cwd,on:c.on});if(!current())return;if(result.code)throw new Error(result.stderr||result.stdout);this.providers=JSON.parse(result.stdout);
   const codex=terminals().find(r=>r.state==='live'&&machineOf(r.address)===c.on&&r.labels?.['repo-tools.agent']==='codex');
   if(this.data?.provider==='codex')this.codexData=this.data;
   else if(codex){const r=await exec('repo-panel.py',['metadata',codex.address.split('/').pop()],{cwd:codex.cwd,on:c.on});if(!current())return;if(!r.code)this.codexData=JSON.parse(r.stdout);}
  }
  if(tab==='services'){const r=await exec('work',['observe',c.stream,'--json','--status-only','--metrics'],{cwd:c.cwd,on:c.on});if(!current())return;if(r.code)throw new Error(r.stderr||r.stdout);this.services=JSON.parse(r.stdout);}
  if(tab==='git'){const r=await exec('git',['--no-optional-locks','status','--short','--branch'],{cwd:c.cwd,on:c.on});if(!current())return;if(r.code)throw new Error(r.stderr||r.stdout);this.git=r.stdout;}
  this.error='';this.updated=new Date().toLocaleTimeString();
 }catch(e){if(current())this.error=String(e);}finally{if(current()){this.busy=false;cx.notify();}}});}
 account(action,provider,cx){if(this.accountBusy)return;const c=scopedLocation();if(!c)return;this.accountBusy=true;this.accountMessage='Opening '+provider+' sign-in…';cx.notify();
  const args=[action];if(action==='login'){args.push(provider);const lead=leadFor(terminals(),c);if(lead)args.push('--lead',lead.address.split('/').pop());}
  cx.spawn(async cx=>{try{const r=await exec('repo-provider.py',args,{cwd:c.cwd,on:c.on});if(r.code)throw new Error(r.stderr||r.stdout);const out=JSON.parse(r.stdout);
   if(out.terminal){const address=c.on?c.on+'/'+out.terminal:out.terminal;this.accountAddress=address;showAccount(address,cx,(message,next)=>{this.accountMessage=message;next.notify();});}
   else {this.accountAddress=null;this.accountMessage=out.message||'Account settings updated.';notify({title:out.connected?'Account connected':'Provider settings',body:this.accountMessage,level:'success'});}
  }catch(e){this.accountMessage=String(e)+' · On JumpBox: '+(provider==='claude'?'claude auth login':provider==='cursor'?'cursor-agent login':provider==='codex'?'codex login':'gemini');notify({title:'Account setup needs attention',body:String(e),level:'warning'});}finally{this.accountBusy=false;this.refresh(cx,true);cx.notify();}});
 }
 render(cx){const c=scopedLocation(),t=theme(),lane=props()?.lane,tab=(shared(INFO)||{})[lane]||'agents';const lead=leadFor(terminals(),c),key=c?.key+':'+lead?.address+':'+tab;if(key!==this.key){this.key=key;this.busy=false;this.updated=null;this.data=null;this.error='';this.services=null;this.git='';this.providers=null;this.codexData=null;this.refresh(cx,true);}
 const colors=palette();
 const card=(title,body)=>v_flex().gap(5).p(10).rounded(9).bg(t.background).border_1().border_color(t.border).child(div().text_size(11).font_semibold().child(title)).child(body);
 let content=v_flex().id('info-scroll').flex_1().min_h(0).overflow_y_scrollbar().p(9).gap(9);
 if(tab==='agents'){
  const rows=relatives(c);content=content.child(h_flex().gap(5).flex_wrap().child(badge(rows.filter(r=>state(r)==='working').length+' WORKING',colors.blue)).child(badge(rows.filter(r=>state(r)==='blocked').length+' NEED INPUT',colors.amber))).child(caption('Lead conversation and scoped helpers'));
  for(const {row:r,depth} of agentTree(rows,lead?.address)){
   const status=state(r)||'unknown',role=r.labels?.['repo-tools.role']||(depth?'helper':'agent'),d=this.agentDetails[r.address],ink={error:colors.red,attention:colors.amber,working:colors.blue,done:colors.green,idle:t.muted}[statusKind(r)];
   content=content.child(v_flex().id('info-agent-'+r.address).ml(Math.min(depth,3)*10).gap(4).p(8).rounded(8).bg(t.background).border_1().border_color(depth?t.accent+'40':t.border)
    .cursor_pointer().tooltip(r.address===lead?.address?'Focus the main conversation':'Open this helper’s conversation').on_click(()=>run(r.address===lead?.address?'pane.focus':'terminal.peek',{terminal:r.address}))
    .child(h_flex().gap(4).items_center()
     .child(div().flex_1().truncate().text_size(10).font_semibold().child((depth?'↳ ':'')+role+' · '+(r.labels?.['repo-tools.agent']||r.status?.app||'agent'))))
    .child(h_flex().gap(5).items_center()
     .child(badge(status,ink).px(5).py(2).text_size(9).flex_none())
     .child(div().flex_1().min_w(0).truncate().text_size(11).child(d?.model||'Model not reported').tooltip(d?.model||'Model not reported'))
     .child(div().flex_none().text_size(10).text_color(colors.violet).child(d?.reasoning||'—').tooltip('Reasoning level · '+(d?.reasoning||'not reported'))))
    .child(div().text_size(10).truncate().text_color(t.muted).tooltip(r.title||c.stream).child(r.title||c.stream)));
  }
  if(!rows.length)content=content.child(caption('No managed agents in this stream.'));
  const flow=(shared('repo.flow-status')||{})[c?.key];if(flow)content=content.child(card('Workflow · '+flow.state,caption(flow.message)));
 }
 if(tab==='context'){
  const d=this.data,x=d?.context,used=number(x?.input),limit=number(x?.window),pct=used!==null&&limit>0?100*used/limit:null;
  content=content.child(meterCard('context-meter','Conversation capacity',pct,limit?`${used===null?'?':count(used)} / ${count(limit)} tokens`:'No exact context reading reported.'));
  if(used!==null&&used>0&&number(x?.cached)!==null){const cached=Math.min(used,Math.max(0,x.cached));
   content=content.child(card('Latest input',v_flex().gap(9)
    .child(meter('context-cache',100*cached/used,'Cached share of latest input',colors.blue))
    .child(h_flex().gap(12).child(stat('CACHED',count(cached),colors.blue)).child(stat('NEW',count(used-cached),colors.violet)))
    .child(caption(count(x.output??0)+' output tokens · last reported turn'))));
  }
  if(d?.compactions!==null&&d?.compactions!==undefined)content=content.child(card('Compaction',h_flex().items_center().gap(10)
   .child(div().size(42).rounded(12).bg(colors.violet+'18').text_color(colors.violet).flex().items_center().justify_center().text_size(24).font_semibold().child(String(d.compactions)))
   .child(div().flex_1().child(caption(d.compactions_partial?'Recorded in the inspected log tail':'Recorded in this conversation')))));
  content=content.child(caption(d?.note||'Select a reporting conversation.'));
 }
 if(tab==='usage'){
  if(this.accountMessage)content=content.child(div().text_size(12).child(this.accountMessage));
  if(this.accountAddress)content=content.child(button('account-open','Open sign-in',(_e,cx)=>showAccount(this.accountAddress,cx,(message,next)=>{this.accountMessage=message;next.notify();}),{icon:'agents',strong:true}));
  const configs=[['codex','Codex',colors.green,'https://chatgpt.com/codex/settings/usage','https://developers.openai.com/codex/cli/'],['claude','Claude',colors.violet,'https://claude.ai/settings/usage','https://code.claude.com/docs/en/quickstart'],['cursor','Cursor',colors.blue,'https://cursor.com/dashboard?tab=usage','https://cursor.com/docs/cli/installation'],['gemini','Gemini',colors.amber,'https://geminicli.com/docs/quota-and-pricing/','https://geminicli.com/docs/get-started/installation/']];
  for(const [id,label,color,url,guide] of configs){
   const account=this.providers?.providers?.find(p=>p.provider===id),connected=account?.connected;
   let section=v_flex().gap(8).p(10).rounded(10).bg(color+'0c').border_1().border_color(color+'35')
    .child(h_flex().gap(5).items_center().child(badge(label.toUpperCase(),color)).child(div().flex_1()).child(caption(!account?'Checking…':!account.installed?'Not installed':connected===true?('Connected'+(account.plan?' · '+account.plan.toUpperCase():'')):connected===false?'Sign in':'Check account')));
   if(id==='codex'){
    const q={...(this.codexData?.quota||{}),...(account?.quota||{})};
    if(!q?.primary&&!q?.secondary)section=section.child(caption('No Codex account limits reported yet.'));
    for(const [name,w] of [['Primary',q?.primary],['Secondary',q?.secondary]])if(w){const h=number(w.window_minutes)===null?null:w.window_minutes/60;section=section.child(quotaCard('codex-'+name,(h===168?'Weekly':h===null?name:h>=24?Math.round(h/24)+' day':h+' hour')+' allowance',w.used_percent,resetNote(w.resets_at),color));}
    const reported=account?.reported_at?account.reported_at*1000:this.codexData?.reported_at;if(reported)section=section.child(caption('Snapshot '+new Date(reported).toLocaleString()));
   }
   if(id==='claude'){
    const windows=account?.quota,labels={five_hour:'5 hour allowance',seven_day:'Weekly allowance',seven_day_sonnet:'Weekly · Sonnet',seven_day_opus:'Weekly · Opus'};
    for(const [name,w] of Object.entries(windows||{}))section=section.child(quotaCard('claude-'+name,labels[name]||name,w.used_percent,w.resets_at?resetNote(w.resets_at):(w.reset_text||'Reset not reported'),color));
    if(!windows||!Object.keys(windows).length)section=section.child(caption(connected===true?(account?.quota_check?.refreshing?'Reading Claude usage…':'Connected. No usage reading is available yet.'):connected===false?'Sign in to connect your Claude subscription.':'Checking Claude connection…'));
    if(connected===true)section=section.child(caption('Automatic check every 5 min while Usage is open · no model tokens.'));
    if(account?.quota_check?.note)section=section.child(caption(account.quota_check.note+' Retrying automatically.'));
    if(account?.reported_at)section=section.child(caption('Snapshot '+new Date(account.reported_at*1000).toLocaleString()));
    const r=(shared('repo.review-cache')||{})[c?.key],left=number(r?.remaining);
    section=section.child(v_flex().gap(6).p(8).rounded(6).bg(t.background)
     .child(caption('LOCAL REVIEW BUDGET · this stream'))
     .child(h_flex().gap(6).children([0,1].map(i=>div().h(8).flex_1().rounded(4).bg(left===null?t.border:i<left?color:color+'25'))))
     .child(caption(left===null?'1 initial review + 1 follow-up per cycle.':left+' of 2 review calls remaining.'))
     .child(caption('12 turns / 10 min each. Separate from subscription quota. Tests use no Claude.')));
   }
   if(id==='cursor')section=section.child(caption('Account quota is not exposed by this CLI integration. View exact usage in the Cursor dashboard.'));
   if(id==='gemini')section=section.child(caption(account?.installed?'Verify sign-in in Gemini. Account limits are not exposed here.':'Optional. Install and sign in to Gemini to use its own CLI; Studio/Work launchers currently offer Codex, Claude and Cursor.'));
   if(account?.note)section=section.child(caption(account.note));
   section=section.child(h_flex().justify_end().gap(5).flex_wrap()
    .when(account?.installed&&connected!==true,e=>e.child(button('login-'+id,this.accountBusy?'Opening…':'Sign in / setup',(_e,cx)=>this.account('login',id,cx),{icon:'play'})))
    .when(account&&!account.installed,e=>e.child(button('install-'+id,'Install guide',(_e,cx)=>cx.open_url(guide),{icon:'book'})))
    .child(button('usage-'+id,id==='gemini'?'Plans & limits':'Usage ↗',(_e,cx)=>cx.open_url(url),{icon:'gauge'})));
   content=content.child(section);
  }
 }
 if(tab==='services'){
  const services=this.services?.services||[],running=services.filter(s=>s.State==='running').length;
  if(services.length)content=content.child(h_flex().gap(8).items_center().child(badge(running+'/'+services.length+' RUNNING',running===services.length?colors.green:colors.amber)));
  for(const s of services){const ram=memoryReading(s),mem=ram?.pct,ok=s.State==='running',healthy=s.Health==='healthy',warn=s.Health==='unhealthy',ink=warn?colors.red:ok?colors.green:colors.amber;
   const tag=(text,color)=>badge(text,color).px(4).py(1).text_size(9).flex_none();
   content=content.child(v_flex().gap(5).p(8).rounded(8).bg(t.background).border_1().border_color(t.border)
    .child(h_flex().gap(4).items_center().justify_end().flex_wrap()
     .child(h_flex().flex_1().min_w(160).gap(4).items_center()
     .child(div().flex_1().min_w(0).truncate().text_size(12).font_semibold().tooltip(s.Name||s.Service).child(s.Service||s.Name))
     .child(tag(s.State||'unknown',ink))
     .when(!!s.Health,e=>e.child(tag(s.Health,healthy?colors.green:warn?colors.red:colors.amber))))
    .children(publishedPorts([s],c?.on).map(p=>h_flex().gap(4).items_center().flex_none()
     .child(div().px(6).py(2).rounded(5).bg(t.selected).text_color(t.foreground).text_size(12).font_semibold().tooltip(p.target+'/'+p.protocol+' · '+p.note).child(':'+p.port))
     .when(!!p.address,r=>r.child(button('address-'+p.key,'Copy address',(_e,cx)=>{cx.write_to_clipboard(p.address);notify({title:'Address copied',body:p.address});},{icon:'copy',compact:true}).tooltip(p.address+' · '+p.note)))
     .when(!!p.url,r=>r.child(button('url-'+p.key,'Open in browser',(_e,cx)=>cx.open_url(p.url),{icon:'external',compact:true}).tooltip(p.url+' · '+(p.suggested?'HTTP/HTTPS inferred from container port; not probed. ':'')+p.note))))))
    .child(h_flex().gap(6).items_center().flex_wrap()
     .child(div().flex_1().text_size(10).text_color(t.muted).child(ok?'Up '+duration(s.UptimeSeconds):'Stopped'))
     .when(!!ram,e=>e.child(h_flex().gap(5).items_center().flex_none()
      .tooltip('RAM used / '+ram.kind+' · '+(mem===null?'Percentage unavailable':Math.round(mem)+'%')+'. Docker excludes reclaimable cache on Linux.')
      .child(div().text_size(10).text_color(t.muted).child('RAM '+ram.used+' / '+ram.limit))
      .child(div().w(44).flex_none().child(meter('memory-'+s.ID,mem,'RAM against '+ram.kind,null,4)))))
     .when(!ram&&ok,e=>e.child(div().text_size(10).text_color(t.dim).tooltip('Memory reading unavailable').child('RAM —')))
     .child(div().text_size(10).text_color(s.Restarts?colors.amber:t.dim).tooltip('Container restart count').child('↻ '+(s.Restarts??'—')))));
  }
  if(!services.length)content=content.child(caption(this.services?.state==='unprepared'?'This stream hasn’t prepared a Docker stack yet.':this.services?'No containers in this Compose project.':'Loading containers…'));
  for(const warning of this.services?.warnings||[])content=content.child(caption(warning));
 }
 if(tab==='git')content=content.child(div().font_family(settings().font_family||'Menlo').text_size(11).child(this.git||'Loading repository status…'));
 if(this.error)content=content.child(div().text_size(11).text_color(t.blocked).child(this.error));
 if(tab==='context'&&this.data?.reported_at)content=content.child(caption('Reported '+new Date(this.data.reported_at).toLocaleString()+' · snapshot, not live usage'));
 return v_flex().size_full().min_h(0).bg(t.chrome).text_color(t.foreground)
 .child(h_flex().px(7).py(5).gap(2).items_center().flex_wrap().children([['agents','agents','Agents & progress'],['context','context','Conversation context'],['usage','gauge','Usage & limits'],['services','docker','Docker containers'],['git','changes','Git status']].map(([id,icon,label])=>button('info-'+id,label,(_e,cx)=>{info(lane,id);cx.notify();},{icon,compact:true,selected:tab===id}))).child(div().flex_1()).child(button('info-refresh','Refresh',(_e,cx)=>this.refresh(cx,true),{icon:'refresh',compact:true})).child(button('info-close','Hide information',()=>info(lane,null),{icon:'close',compact:true})))
 .child(content).child(div().px(12).py(5).child(caption(this.busy?'Refreshing…':this.updated?'Checked '+this.updated:'Reported status only')));
 }
}
export class Questions extends View {
 render(){const c=scopedLocation(),t=theme(),rows=relatives(c).filter(r=>state(r)==='blocked'),flow=(shared('repo.flow-status')||{})[c?.key];return v_flex().size_full().min_h(0).bg(toolColors().background).text_color(t.foreground).p(14).gap(10)
 .child(div().text_size(14).font_semibold().child('Questions · '+rows.length+' agent'+(rows.length===1?'':'s')+' awaiting input'))
 .child(caption('Open the originating conversation to read and answer the exact question or approval. No questions are inferred from terminal prose.'))
 .child(v_flex().id('questions-list').flex_1().min_h(0).overflow_y_scrollbar().gap(8).children(rows.map(r=>h_flex().p(10).bg(t.background).rounded(6).gap(10).items_center().child(v_flex().flex_1().child(div().text_size(12).child(r.labels?.['repo-tools.role']||'Agent')).child(caption(r.title||'Needs your input'))).child(button('question-'+r.address,'Open question',()=>run('terminal.peek',{terminal:r.address}),{icon:'question'}))))
 .when(!rows.length,e=>e.child(caption('No agent is currently reporting a blocked state.')))
 .when(flow?.state==='needs-you',e=>e.child(v_flex().p(10).bg(t.background).child(div().text_size(12).font_semibold().child('Workflow needs you')).child(caption(flow.message)))));
 }
}
