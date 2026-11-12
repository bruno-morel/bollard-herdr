import {reportPanel} from './signals.js';
import {resultsView} from './test-results.js';
import {askHelper} from './helper.js';
import {View,div,svg} from 'gpui-kit';
import {v_flex,h_flex,Editor,EditorState} from 'gpui-base';
import {exec,theme,props,terminals,shared,settings,notify,run} from 'herdr';
import {scopedLocation,leadFor,VIEWS} from './scope.js';
import {toolColors,button,caption,view} from './ui.js';

// Setup, running and rerunning are different states, not one misleading button.
export function primaryAction(s,busy=false,pending=false){
 if(busy)return {label:'Working…',disabled:true};
 if(!s)return {label:'Loading tests…',disabled:true};
 if(s.state==='preparing')return {label:'Preparing first run…',disabled:true};
 if(['queued','running'].includes(s.state))return {label:'Tests running…',disabled:true};
 if(!s.configured)return {label:'First tests run',action:'first',icon:'play'};
 return {label:s.results?.length?'Rerun tests':'First tests run',action:'run',icon:'play'};
}

export default class Tests extends View {
 init(_p,cx){
  this.setupAgent='codex';this.key=null;this.generation=0;this.data=null;this.busy=false;this.error='';this.actionError='';this.pendingSetup=false;this.chosen=null;this.showCommands=false;this.logOpen=false;
  this.editor=EditorState.new({readonly:true,value:'',font_size:12,font_family:settings().font_family});
  cx.timer.every(15000,cx=>this.refresh(cx));
 }
 refresh(cx,force=false){
  const c=scopedLocation();
  if(!c||this.busy||(!force&&(shared(VIEWS)||{})[props().lane]!=='tests'))return;
  this.busy=true;const g=this.generation,current=()=>this.key===c.key&&scopedLocation()?.key===c.key&&g===this.generation;
  cx.spawn(async cx=>{try{
   const r=await exec('work',['tests','status',c.stream,'--json'],{cwd:c.cwd,on:c.on});
   if(!current())return;if(r.code)throw new Error(r.stderr||r.stdout);
   this.data=JSON.parse(r.stdout);this.error='';
   this.pendingSetup=this.data.state==='preparing';
   this.showLog();
  }catch(e){if(current())this.error=String(e);}finally{if(current()){this.busy=false;cx.notify();}}});
 }
 showLog(){
  const results=this.data?.results||[];
  const requested=(this.data?.checks||[]).find(x=>x.id===this.chosen);
  if(requested&&!results.some(x=>x.id===requested.id)){this.editor.set_value(JSON.stringify(requested.argv)+'\n'+(this.data?.current===requested.id?'Running…':'No completed result for this check yet.'));return;}
  const selected=results.find(x=>x.id===this.chosen)||results.find(x=>x.exit_code!==0)||results[0];
  this.chosen=selected?.id||null;
  this.editor.set_value(selected?JSON.stringify(selected.argv)+'\nExit '+selected.exit_code+' · '+selected.log+'\n\n'+selected.tail:
   this.data?.current?'Running '+this.data.current+'… Output appears as each check finishes.':
   'Check output will appear here. Commands are time-limited; no Claude review is started.');
 }
 conversation(){const c=scopedLocation(),lead=leadFor(terminals(),c);if(lead){view(props().lane,null);run('pane.focus',{terminal:lead.address});}}
 action(action,cx){
  const c=scopedLocation();if(!c||this.key!==c.key||this.busy)return;
  if(action==='run'&&(!this.data?.configured||['queued','running'].includes(this.data.state)))return;
  if(action==='first'&&this.pendingSetup)return;
  const lead=leadFor(terminals(),c),args=['tests',action,c.stream,'--json'];
  this.actionError='';
  if(['first','send'].includes(action)){
   if(!lead){this.actionError='Open this stream’s lead conversation first, then try again.';cx.notify();return;}
   if(action==='first')args.push('--agent',this.setupAgent);
   args.push('--target',lead.address.split('/').pop());
  }
  this.busy=true;const g=this.generation,current=()=>this.key===c.key&&scopedLocation()?.key===c.key&&g===this.generation;
  cx.spawn(async cx=>{try{
   const r=await exec('work',args,{cwd:c.cwd,on:c.on});if(r.code)throw new Error(r.stderr||r.stdout);
   if(current()){
    if(action==='first')this.pendingSetup=true;
    if(['run','first'].includes(action)){this.data=JSON.parse(r.stdout);this.showLog();}
   }
   notify({title:c.stream+' · Tests',body:action==='run'?'Configured checks queued. No Claude usage.':action==='first'?'A read-only child is selecting project checks; the first test run follows automatically.':'Failures sent to this conversation.',level:'success'});
  }catch(e){
   notify({title:'Tests need attention',body:String(e),level:'warning'});
   if(current())this.actionError=String(e);
  }finally{if(current()){this.busy=false;this.refresh(cx,true);cx.notify();}}});
 }
 render(cx){
  const c=scopedLocation(),t=theme();
  if(this.key!==c?.key){this.key=c?.key;this.generation++;this.busy=false;this.data=null;this.error='';this.actionError='';this.pendingSetup=false;this.chosen=null;this.showCommands=false;this.logOpen=false;this.editor.set_value('');this.refresh(cx,true);}
  const s=this.data,action=primaryAction(s,this.busy,this.pendingSetup),missing=!!s&&!s.configured,lead=leadFor(terminals(),c);
  reportPanel('tests',c,this.error||this.actionError||['failed','incomplete'].includes(s?.state));
  const label=missing?(this.pendingSetup?'Preparing checks':'Setup needed'):(s?.state||'Loading…');
  return v_flex().size_full().min_h(0).p(4).bg(toolColors().background).text_color(t.foreground).gap(6)
   .child(h_flex().px(12).py(6).gap(8).items_center().flex_wrap().justify_end().flex_none()
    .child(div().flex_1().font_semibold().text_size(13).child('Tests · '+label))
    .when(missing&&!this.pendingSetup,e=>e.child(h_flex().gap(4).children(['codex','claude','cursor'].map(a=>button('tests-agent-'+a,a,(_e,cx)=>{if(!this.busy){this.setupAgent=a;cx.notify();}},{selected:this.setupAgent===a})))))
    .child(button('tests-primary',action.label,(_e,cx)=>{if(!action.disabled)this.action(action.action,cx);},{icon:action.icon||'test',strong:true}).opacity(action.disabled ? 0.55 : 1))
    .when(!!s?.configured,e=>e.child(button('tests-commands',this.showCommands?'Hide commands':'Show commands',(_e,cx)=>{this.showCommands=!this.showCommands;cx.notify();},{icon:'list',selected:this.showCommands})))
    .when(!!s?.setup_terminal,e=>e.child(button('tests-child','Open test helper',()=>run('terminal.peek',{terminal:(c.on?c.on+'/':'')+s.setup_terminal}),{icon:'agents'})))
    .when(!!s?.failure_prompt,e=>e.child(button('tests-send',s.state==='stale'?'Discuss old failures':'Investigate failures',(_e,cx)=>this.action('send',cx),{icon:'message'})))
    .when(this.logOpen&&!!this.chosen,e=>e.child(button('tests-helper','Ask a helper',()=>askHelper(c,{pane:'tests',source:this.chosen,text:'Run: '+(s.token||'unknown')+' · evidence '+s.state+'\n\n'+this.editor.value(),head:s.head,observed_at:s.finished||s.started}),{icon:'agents'})))
    .child(button('tests-refresh','Refresh',(_e,cx)=>this.refresh(cx,true),{icon:'refresh',compact:true})))
   .when(!!this.error||!!this.actionError,e=>e.child(div().px(12).text_size(12).text_color(t.blocked).child(this.actionError||this.error)))
   .when(missing,e=>e.child(v_flex().flex_1().min_h(0).id('tests-setup-scroll').overflow_y_scrollbar().p(20).gap(10)
    .child(svg('mods/repo-portrait/icons/test.svg').size(34).text_color(t.accent))
    .child(div().text_size(17).font_semibold().child(this.pendingSetup?'A child agent is preparing the first run':'First tests run'))
    .child(div().max_w(640).text_size(13).child(this.pendingSetup?
     'Your main conversation stays available. The child inspects the project’s existing scripts and CI, then the runner saves and executes those checks once.':
     'A read-only child using your selected CLI selects finite checks from the project’s existing scripts and CI. The first run starts automatically when the check list is valid. Later reruns need no model.'))
    .child(caption('No feature changes, automatic fixes or Claude review. After setup, reruns execute the saved commands directly.'))
    .when(!!s.message,e=>e.child(div().text_size(12).text_color(t.muted).child(s.message)))
    .when(!!s.config_error,e=>e.child(div().mt(4).text_size(11).text_color(t.muted).child(s.config_error)))))
   .when(!missing,e=>e
    .child(div().px(12).child(caption(s?.message||'Runs the saved checks. No model usage for reruns.')))
    .when(s?.state==='stale',e=>e.child(div().px(12).text_size(12).text_color(t.muted).child('Historical results — not the current checkout. Tests run directly by an agent are not automatically imported here.')))
    .when(!!s?.failure_prompt,e=>e.child(div().px(12).text_size(12).text_color(t.muted).child('This runner reports failures; it does not edit code. Investigate failures sends evidence to your lead when idle; Ask a helper provides read-only analysis. Implement → Review is the separate bounded fix/review workflow.')))
    .when(!!s?.checks,e=>e.child(div().px(12).text_size(11).text_color(t.muted).child(s.checks.length+' configured checks · Up to '+Math.ceil(s.checks.reduce((n,x)=>n+(x.timeout||120),0)/60)+' minutes'+(s.current?' · Running '+s.current:''))))
    .when(!!s?.setup_summary,e=>e.child(div().px(12).text_size(12).text_color(t.muted).child(s.setup_summary+' · '+s.setup_limitations)))
    .when(this.showCommands,e=>e.child(v_flex().id('tests-commands-list').max_h(140).flex_none().overflow_y_scrollbar().px(12).py(5).gap(5)
     .children((s?.checks||[]).map(x=>div().text_size(11).text_color(t.muted).child(x.id+' · '+x.argv.join(' '))))))
    .child(resultsView(s,this.logOpen?this.chosen:null,(id,cx)=>{this.logOpen=!(this.logOpen&&this.chosen===id);this.chosen=id;this.showLog();cx.notify();}))
    .when(this.logOpen,e=>e.child(v_flex().flex_1().min_h(90).gap(4)
     .child(h_flex().px(12).gap(6).items_center().flex_none()
      .child(div().flex_1().text_size(11).font_semibold().child((this.chosen||'Check')+' · captured output'))
      .child(button('tests-copy-log','Copy output',(_e,cx)=>cx.write_to_clipboard(this.editor.value()),{icon:'copy',compact:true}))
      .child(button('tests-close-log','Hide logs',(_e,cx)=>{this.logOpen=false;cx.notify();},{icon:'close',compact:true})))
     .child(Editor.new(this.editor).flex_1().min_h(0)))))
   .child(div().px(12).py(4).child(caption((s?.head?'Commit '+s.head.slice(0,9)+' · ':'')+(s?.finished||s?.started||'No run yet')+' · Passing checks ≠ review approval')));
 }
 close(){this.editor.release();}
}
