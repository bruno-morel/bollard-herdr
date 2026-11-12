import {viewerExec} from './terminal-display.js';
import { View, div } from 'gpui-kit';
import { v_flex, h_flex, Input, InputState } from 'gpui-base';
import { spaces, panes, terminals, focused, props, theme, exec, run, notify, openOverlay, closeOverlay, shared, setShared, nextCommand } from 'herdr';
import { selectLocation, selectWorkflowContext } from './routing.js';
import { openExisting, watchOpen, followOpens } from './navigation.js';
const here=()=>selectLocation(terminals(),spaces(),panes(),focused());
const dialog=(action,extra={})=>openOverlay({mod:action==='open'?'repo-stream-picker':'repo-workflow',kind:'dialog',width:action==='open'?720:610,...(action==='open'?{}:{height:590}),props:{dialog:true,action,...extra}});
const TITLES={open:'Open or create a stream',prepare:'Prepare implementation',implement:'Implement through review',helper:'Add a scoped helper',pause:'Pause workflow'};
export default class Workflow extends View {
 init(_p,cx){
  this.dialog=!!props()?.dialog;this.busy=false;this.message='';this.lastKey=null;
  if(!this.dialog){this.refresh(cx);cx.timer.every(15000,cx=>this.refresh(cx));cx.timer.every(5000,cx=>{cx.spawn(async cx=>{await followOpens();cx.notify();});});cx.spawn(async cx=>{for(;;){const command=await nextCommand();if(['open','prepare','implement','helper','pause'].includes(command))dialog(command);cx.notify();}});return;}
  if((props().action||'open')==='open'){this.redirect=true;const old=props().overlay;dialog('open',{...props(),overlay:undefined});if(old)closeOverlay(old);return;}
  const p=props()||{},loc=p.context||selectWorkflowContext(terminals(),spaces(),panes(),focused(),p);
  this.action=p.action||'open';this.role=p.role||'studio';this.kind=p.kind||'research';this.agent='codex';this.reviewer='claude';
  this.on=loc.on;
  const cwd=loc.cwd;
  this.folder=InputState.new({value:cwd,placeholder:'Repository or existing worktree path on this machine'});
  this.stream=InputState.new({value:p.fresh?'':loc.stream,placeholder:'Stream name, e.g. waiting-list'});
  this.scope=InputState.new({value:p.scope||'',placeholder:'Focused task (required for helper; optional for implementation)'});
  for(const input of [this.folder,this.stream,this.scope])input.on('change',(_e,cx)=>{this.message='';cx.notify();});
  this.stream.focus();
 }
 button(id,label,fn,selected=false){const t=theme();return div().id(id).px(9).py(6).rounded(5).text_size(12).bg(selected?t.selected:t.surface).text_color(selected?t.foreground:t.accent).cursor_pointer().hover(s=>s.bg(t.hover)).on_click(fn).child(label);}
 refresh(cx){if(this.busy)return;const loc=here();if(!loc)return;this.busy=true;const key=loc.key;
  cx.spawn(async cx=>{try{const r=await exec('work',['flow','status'],{cwd:loc.cwd,on:loc.on});
    if(!r.code){const value=JSON.parse(r.stdout),old=shared('repo.flow-status')?.[key];
     setShared('repo.flow-status',{...(shared('repo.flow-status')||{}),[key]:value});
     if(old&&old.updated!==value.updated&&['verified','needs-you','ready'].includes(value.state)&&old.state!==value.state)
      notify({title:`${value.stream}: ${value.state==='needs-you'?'Needs you':value.state==='verified'?'Review verified':'Ready'}`,body:value.message,level:value.state==='needs-you'?'warning':'success'});
    }
   }catch{}finally{this.busy=false;cx.notify();}});
 }
 submit(cx){
  if(this.busy)return;const cwd=this.folder.value().trim(),stream=this.stream.value().trim(),task=this.scope.value().trim();
  if(!cwd||!stream){this.message='Choose a repository path and stream.';cx.notify();return;}
  if(!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(stream)){this.message='Use lowercase words separated by hyphens for the stream.';cx.notify();return;}
  if(this.action==='helper'&&!task){this.message='Give the helper a focused task.';cx.notify();return;}
  const role=['prepare','implement'].includes(this.action)?'work':this.role;
  const args=['flow',this.action,stream,'--role',role,'--agent',this.agent];
  if(this.action==='implement')args.push('--reviewer',this.reviewer);
  if(this.action==='helper')args.push('--kind',this.kind,'--scope',task);
  else if(task)args.push('--task',task);
  this.busy=true;this.message='Preparing…';
  cx.spawn(async cx=>{try{
   if(this.action==='open'&&await openExisting(cwd,stream,role,this.on,props().lane,props().newWindow)){closeOverlay(props().overlay);return;}
   const r=await viewerExec(role,args,{cwd,on:this.on});
   if(r.code)throw new Error(r.stderr.trim()||r.stdout.trim()||'The workflow could not start.');
   if(['open','prepare','implement'].includes(this.action)){const result=JSON.parse(r.stdout.trim().split('\n').pop());watchOpen({terminal:result.terminal,stream,cwd,on:this.on,lane:props().lane,newWindow:!!props().newWindow});}
   notify({title:'Workflow requested',body:this.action==='helper'?'The helper appears beside its lead.':props().newWindow?'Preparing your stream. Its window will open when the conversation is ready.':'Follow the Workflow tab for setup and any questions.',level:'success'});
   closeOverlay(props().overlay);
  }catch(e){this.message=String(e);}finally{this.busy=false;cx.notify();}});
 }
 field(label,input){const t=theme();return v_flex().gap(4).child(div().text_size(11).text_color(t.muted).child(label)).child(Input.new(input).h(34).px(8).items_center().rounded(5).border(1).border_color(t.border).bg(t.background).text_color(t.foreground));}
 render(cx){const t=theme();if(this.redirect)return div();
  if(!this.dialog){
   const loc=here(),state=loc?(shared('repo.flow-status')||{})[loc.key]:null;
   for(const space of spaces())for(const tab of space.tabs){if(tab.named)continue;
    const term=terminals().find(x=>panes().some(p=>p.tab===tab.id&&p.terminal===x.address));
    const role=term?.labels?.['repo-tools.role'];if(['workflow','studio','work','helper'].includes(role))run('tab.rename',{id:tab.id,name:role==='helper'?'Helper':role[0].toUpperCase()+role.slice(1)});
   }
   return v_flex().w_full().px(10).py(5).gap(4).bg(t.chrome)
    .child(h_flex().gap(5).items_center()
     .child(this.button('flow-new','+ Stream',()=>dialog('open',{fresh:true})))
     .child(this.button('flow-studio','Studio',()=>dialog('open',{role:'studio'})))
     .child(this.button('flow-work','Work',()=>dialog('open',{role:'work'})))
     .child(this.button('flow-prepare','Prepare implementation',()=>dialog('prepare')))
     .child(this.button('flow-implement','Implement → Review',()=>dialog('implement',{role:'work'})))
     .child(this.button('flow-helper','+ Helper',()=>dialog('helper',{role:'work'})))
     .child(this.button('flow-shell','Shell',()=>run('tab.new'))))
    .child(h_flex().items_center().gap(8)
     .child(div().text_size(11).text_color(state?.state==='needs-you'?t.blocked:t.muted).truncate().flex_1().child(state?.message||'Select a repository or stream. Your scripts handle setup, handoffs and review.'))
     .when(!!state&&['queued','preparing','implementing','fixing','reviewing'].includes(state.state),el=>el.child(this.button('flow-pause','Pause',()=>dialog('pause')))));
  }
  const limited=['helper','implement'].includes(this.action);
  return v_flex().size_full().p(20).gap(12).bg(t.surface).text_color(t.foreground)
   .child(div().text_size(19).font_semibold().child(props().newWindow?'Open or create a stream in a new window':TITLES[this.action]||'Workflow'))
   .child(div().text_size(12).text_color(t.muted).child(`Machine: ${this.on||'This computer'}`))
   .child(this.field('Repository / checkout',this.folder))
   .child(this.field('Stream',this.stream))
   .when(['open','helper'].includes(this.action),el=>el.child(h_flex().gap(5)
    .child(this.button('role-studio','Studio · planning',(_e,cx)=>{this.role='studio';cx.notify();},this.role==='studio'))
    .child(this.button('role-work','Work · implementation',(_e,cx)=>{this.role='work';cx.notify();},this.role==='work'))))
   .when(this.action==='helper',el=>el.child(h_flex().gap(5)
    .child(this.button('kind-research','Read-only research',(_e,cx)=>{this.kind='research';cx.notify();},this.kind==='research'))
    .child(this.button('kind-code','Isolated coding',(_e,cx)=>{this.kind='code';cx.notify();},this.kind==='code'))))
   .when(this.action!=='pause',el=>el.child(h_flex().gap(5).children(['codex','claude','cursor'].map(agent=>this.button('agent-'+agent,agent,(_e,cx)=>{this.agent=agent;cx.notify();},agent===this.agent)))))
   .when(this.action==='implement',el=>el.child(h_flex().gap(5).child(div().child('Reviewer')).children(['claude','codex','cursor'].map(a=>this.button('reviewer-'+a,a,(_e,cx)=>{this.reviewer=a;cx.notify();},a===this.reviewer)))))
   .when(['helper','implement'].includes(this.action),el=>el.child(this.field('Task / scope',this.scope)))
   .child(div().text_size(11).text_color(t.muted).child(this.action==='implement'?'Authorizes implementation, tests, fixes and the existing review allowance: at most two review attempts, 20 minutes each (Claude: Sonnet, 24 turns). Choose a different provider from the implementation agent. Stops for questions; no merge or push.':this.action==='helper'?'One helper at a time. Coding requires a clean committed checkpoint; the lead integrates and validates its work.':this.action==='prepare'?'Builds the handoff, opens Work and its Docker stack, then prepares the plan. Coding waits for your approval.':this.action==='pause'?'Stops further workflow steps. An agent or check already running is left intact.':'Creates or resumes the shared Git stream and repository guidance. Work also starts its existing Docker setup.'))
   .when(!!this.message,el=>el.child(div().text_size(11).text_color(t.blocked).child(this.message)))
   .child(h_flex().gap(8).justify_end()
    .child(this.button('flow-cancel','Cancel',()=>closeOverlay(props().overlay)))
    .when(!this.busy,el=>el.child(this.button('flow-submit',this.action==='implement'?'Implement through review':this.action==='pause'?'Pause':'Continue',(_e,cx)=>this.submit(cx)))));
 }
}
