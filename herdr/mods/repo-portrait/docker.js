import {reportPanel} from './signals.js';
import {askHelper} from './helper.js';
import {dockerState,emptyCopy} from './docker-state.js';
import { View,div,image } from 'gpui-kit';
import { v_flex,h_flex,VirtualListScrollHandle } from 'gpui-base';
import {logView,logText} from './log-view.js';
import { theme,settings,shared,props,notify } from 'herdr';
import {exec,location as scopedLocation,panelVisible,workflowAvailable,liveLogDescription} from './panel-host.js';
import {toolColors,button} from './ui.js';
// Shorten only Compose's line prefix; leave the actual log message intact.
export function displayLogs(data){
 const project=data.project||'',names=new Set((data.services||[]).map(s=>s.Name||s.Names));
 return (data.logs||'').split('\n').map(line=>{
  const pipe=line.indexOf('|');if(pipe<0)return line;
  const prefix=line.slice(0,pipe).trim();
  if(project&&names.has(prefix)&&prefix.startsWith(project+'-'))return prefix.slice(project.length+1)+' |'+line.slice(pipe+1);
  return line;
 }).join('\n');
}
export default class Docker extends View {
 init(_p,cx){this.busy=false;this.generation=0;this.startRequests=new Set();this.job=null;this.showStartup=false;this.startError='';this.error='';this.data=null;this.key=null;this.frozen=false;this.showOldLogs=false;this.showDetails=false;this.log='';this.follow=true;this.feedBusy=false;this.feedError='';this.logScroll=VirtualListScrollHandle.new();cx.timer.every(2000,cx=>this.pollLogs(cx));cx.timer.every(10000,cx=>this.refresh(cx));}
 setLog(value){const next=logText(value);if(next===this.log)return;this.log=next;if(this.follow)this.logScroll.scroll_to_bottom();}
 pollLogs(cx){const c=scopedLocation();if(!c||this.feedBusy||this.frozen||this.showStartup||this.job?.state==='running'||!panelVisible('docker')||dockerState(this.data)!=='active')return;
  this.feedBusy=true;const generation=this.generation;cx.spawn(async cx=>{try{const r=await exec('repo-logfeed.py',['poll',c.stream],{cwd:c.cwd,on:c.on});if(generation!==this.generation)return;if(r.code)throw new Error(r.stderr||r.stdout);const d=JSON.parse(r.stdout);this.feedError=d.state==='error'?d.message:'';if(d.logs){this.data={...this.data,logs:d.logs,observed_at:new Date(d.heartbeat*1000).toISOString()};this.setLog(displayLogs(this.data));}}catch(e){if(generation===this.generation)this.feedError=String(e);}finally{this.feedBusy=false;cx.notify();}});
 }
 askHelper(){const c=scopedLocation();if(this.key===c?.key&&this.data?.logs)askHelper(c,{pane:'docker',source:this.data.project||'Compose logs',text:displayLogs(this.data),observed_at:this.data.observed_at});}
 start(cx){
  const c=scopedLocation();if(!c||this.key!==c.key||this.startRequests.has(c.key)||this.job?.state==='running')return;
  this.startRequests.add(c.key);this.generation++;this.busy=false;this.startError='';this.error='';this.showStartup=true;this.showOldLogs=false;this.frozen=false;
  this.setLog('Preparing this stream’s Docker stack…');cx.notify();
  cx.spawn(async cx=>{try{
   const r=await exec('work',['docker','start',c.stream,'--json'],{cwd:c.cwd,on:c.on});
   if(scopedLocation()?.key!==c.key)return;
   if(r.code)throw new Error(r.stderr.trim()||r.stdout.trim()||'Docker startup could not be queued.');
   this.job=JSON.parse(r.stdout);this.setLog(this.job.output||'Docker startup queued…');
   if(this.job.state==='succeeded')this.showStartup=false;
  }catch(e){if(scopedLocation()?.key===c.key){this.startError=String(e);this.showStartup=false;}}
  finally{this.startRequests.delete(c.key);if(scopedLocation()?.key===c.key){this.refresh(cx,true);cx.notify();}}});
 }
 refresh(cx,force=false){const c=scopedLocation();if(!c||this.busy||this.startRequests.has(c.key)||(!force&&(this.frozen||!panelVisible('docker'))))return;
  this.busy=true;const key=c.key,g=this.generation;
  const current=()=>scopedLocation()?.key===key&&g===this.generation;
  cx.spawn(async cx=>{try{
   const startup=await exec('work',['docker','status',c.stream,'--json'],{cwd:c.cwd,on:c.on});if(!current())return;
   if(startup.code)throw new Error(startup.stderr.trim()||'Cannot inspect Docker startup.');
   const previous=this.job;this.job=JSON.parse(startup.stdout);
   const finished=previous?.state==='running'&&previous?.terminal===this.job.terminal&&this.job.state!=='running';
   if(finished){
    this.showStartup=this.job.state==='failed';
    notify({title:c.stream+' · Docker',body:this.job.state==='succeeded'?'Docker startup finished.':'Docker startup needs attention. Open Docker for the output.',level:this.job.state==='succeeded'?'success':'warning'});
   }
   if(this.showStartup)this.setLog(this.job.output||'Waiting for startup output…');
   if(this.job.state==='running'){
    this.error='';this.setLog(this.job.output||'Preparing containers…');return;
   }
   const r=await exec('work',['observe',c.stream,'--json','--status-only'],{cwd:c.cwd,on:c.on});if(!current())return;
   if(r.code)throw new Error(r.stderr.trim()||'Docker inspection failed');
   const latest=JSON.parse(r.stdout);this.data={...latest,logs:this.data?.logs||''};this.error='';this.showDetails=false;
   if(this.showStartup)this.setLog(this.job.output||'No startup output captured.');else if(dockerState(this.data)==='active')this.pollLogs(cx);
  }catch(e){if(current())this.error=String(e);}finally{if(current())this.busy=false;cx.notify();}});
 }
 empty(state,t){const copy=emptyCopy(state);
  return v_flex().id('docker-empty-scroll').flex_1().min_h(0).overflow_y_scrollbar()
   .child(v_flex().h_full().min_h(370).px(20).py(12).gap(10).items_center().justify_center()
    .child(image('mods/repo-portrait/icons/whale-waiting.svg').w(320).h(213).flex_none().accessibility_label('A little teal whale with tears, waiting for containers'))
    .child(div().text_size(18).font_semibold().text_center().child(copy.title))
    .child(div().max_w(410).text_size(12).text_center().text_color(t.muted).child(copy.detail))
    .child(button('docker-start','Start Docker',(_e,cx)=>this.start(cx),{icon:'play',strong:true}).px(24).py(13).text_size(15))
    .child(div().text_size(11).text_color(t.muted).child('Starts this stream’s Docker stack')));
 }
 render(cx){const c=scopedLocation(),t=theme();if(c?.key!==this.key){this.key=c?.key;this.follow=true;this.feedError='';this.generation++;this.busy=false;this.job=null;this.showStartup=false;this.startError='';this.data=null;this.error='';this.showOldLogs=false;this.showDetails=false;this.setLog('');this.refresh(cx);}
  const starting=this.startRequests.has(c?.key)||this.job?.state==='running';
  reportPanel('docker',c,this.error||this.feedError||this.startError||this.job?.state==='failed');
  const state=dockerState(this.data),empty=['unprepared','empty','stopped'].includes(state);
  return v_flex().size_full().min_h(0).p(4).bg(toolColors().background).text_color(t.foreground)
   .child(h_flex().flex_none().px(10).py(4).gap(6).items_center().border_b(1).border_color(t.border)
    .child(div().flex_1().text_size(12).font_semibold().child(this.data?.project||'Docker logs'))
    .when(!starting&&!!this.job?.terminal,e=>e.child(button('docker-start-output',this.showStartup?'Back to containers':'Startup output',(_e,cx)=>{this.showStartup=!this.showStartup;this.setLog(this.showStartup?this.job.output||'No startup output captured.':displayLogs(this.data||{}));cx.notify();},{icon:'list'})))
    .when(!starting&&empty&&!!this.data?.logs,e=>e.child(button('docker-history',this.showOldLogs?'Back to overview':'View last logs',(_e,cx)=>{this.showOldLogs=!this.showOldLogs;this.showStartup=false;this.setLog(displayLogs(this.data));cx.notify();},{icon:this.showOldLogs?'docker':'list'})))
    .when(workflowAvailable()&&!!this.data?.logs,e=>e.child(button('docker-helper','Ask a helper',()=>this.askHelper(),{icon:'agents'})))
    .child(button('docker-latest',this.follow?'Following':'Latest',(_e,cx)=>{this.follow=true;this.logScroll.scroll_to_bottom();cx.notify();},{icon:'play',selected:this.follow}))
    .child(button('docker-copy','Copy logs',(_e,cx)=>cx.write_to_clipboard(this.log),{icon:'copy'}))
    .child(button('docker-freeze',this.frozen?'Resume refresh':'Freeze',(_e,cx)=>{this.frozen=!this.frozen;if(!this.frozen)this.refresh(cx,true);cx.notify();},{icon:this.frozen?'play':'pause'}))
    .child(button('docker-refresh','Refresh',(_e,cx)=>this.refresh(cx,true),{icon:'refresh',compact:true})))
   .when(starting,e=>e.child(div().px(14).py(8).text_size(13).font_semibold().child('Starting Docker… this can take a few minutes.')))
   .when(!starting&&(this.job?.state==='failed'||!!this.startError),e=>e.child(h_flex().px(14).py(7).gap(8).items_center()
    .child(div().flex_1().text_size(12).text_color(t.muted).child(this.startError||'The last startup did not finish successfully. Its output is available above.'))
    .child(button('docker-start-retry','Retry startup',(_e,cx)=>this.start(cx),{icon:'play'}))))
   .when(!!this.error&&!starting&&!this.showStartup,el=>el.child(v_flex().flex_1().min_h(0).id('docker-error').overflow_y_scrollbar().p(20).gap(12)
    .child(div().font_semibold().child('Docker needs a little attention'))
    .child(div().text_size(12).text_color(t.muted).child('We couldn’t read this stream’s stack. Check the connection or configuration, then refresh.'))
    .child(h_flex().justify_end().gap(6)
     .child(button('docker-details',this.showDetails?'Hide details':'Show details',(_e,cx)=>{this.showDetails=!this.showDetails;cx.notify();},{icon:'context'}))
     .child(button('docker-retry','Try again',(_e,cx)=>this.refresh(cx,true),{icon:'refresh'})))
    .when(this.showDetails,e=>e.child(div().text_size(11).text_color(t.muted).child(this.error)))))
   .when(!this.error&&!starting&&!this.showStartup&&empty&&!this.showOldLogs,el=>el.child(this.empty(state,t)))
   .when(!this.error&&!starting&&!this.showStartup&&(state==='loading'||state==='unknown'),el=>el.child(div().flex_1().p(20).text_size(12).text_color(t.muted).child(state==='unknown'?'Docker status is unavailable. Refresh to try again.':c?'Checking this stream’s containers…':'Choose a stream to see its containers.')))
   .when((starting||this.showStartup)||(!this.error&&(state==='active'||(empty&&this.showOldLogs))),el=>el.child(logView('docker-logs-'+this.key,this.log||'Waiting for container output…',this)))
   .child(div().flex_none().px(10).py(3).text_size(10).text_color(t.dim).child(starting?'Docker startup continues in the background · refresh 10s':this.busy?'Refreshing…':this.frozen?'Display frozen · agent and containers continue':empty?'Checks every 10s':this.error?'Inspection unavailable · retry every 10s':this.feedError?'Log stream needs attention: '+this.feedError:liveLogDescription+(this.follow?' · following latest':' · scroll paused')));
 }
 close(){this.logScroll.release();}
}
