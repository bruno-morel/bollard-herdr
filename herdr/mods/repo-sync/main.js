import {View,div} from 'gpui-kit';
import {h_flex,v_flex,Input,InputState,TextView} from 'gpui-base';
import {props,exec,theme,closeOverlay,notify,nextCommand} from 'herdr';
import {button,caption,toolColors} from './ui.js';
export default class Sync extends View{
 init(_p,cx){this.context=props()?.context;this.source=props()?.source||null;this.autoPreview=this.source==='default';this.rows=[];this.snapshot=null;this.message='';this.busy=false;this.attempted=false;this.filter='';this.input=InputState.new({placeholder:'Find a branch or worktree…'});this.input.on('change',(_e,cx)=>{this.filter=this.input.value().toLowerCase();cx.notify();});this.request('sources',cx);cx.spawn(async cx=>{for(;;){const cmd=await nextCommand();if(cmd==='preview')this.request('preview',cx);cx.notify();}});}
 request(action,cx,fetch=false){if(this.busy)return;const c=this.context;if(!c?.cwd)return;this.busy=true;this.message='';const args=['sync',action,'--json'];
  if(action==='preview'){this.snapshot=null;this.attempted=false;args.push('--source',this.source||'default');if(fetch)args.push('--fetch');}
  if(action==='apply'){if(!this.snapshot||this.attempted){this.busy=false;return;}args.push('--token',this.snapshot.token);this.attempted=true;}
  cx.spawn(async cx=>{try{const r=await exec(c.role||'work',args,{cwd:c.cwd,on:c.on});let data;try{data=JSON.parse(r.stdout);}catch{}
   if(r.code&&!data)throw new Error(r.stderr||r.stdout||'Git operation failed');
   if(action==='sources'){this.rows=data.sources;this.branch=data.branch;this.default=data.default;if(this.source==='default')this.source=data.default;}
   else if(action==='preview')this.snapshot=data;
   else {this.message=data.message+'\n\n'+data.note;if(data.conflicts)this.message+='\nConflicts:\n'+data.conflicts;notify({title:data.ok?'Stream updated':'Merge needs attention',body:c.stream+' · '+data.note,level:data.ok?'success':'warning'});}
  }catch(e){this.message=String(e)+(action==='apply'?'\nInspect Git status before retrying. A timed-out merge may have completed.':'');}finally{this.busy=false;cx.notify();if(action==='sources'&&this.autoPreview&&this.source&&!this.message){this.autoPreview=false;this.request('preview',cx);}}});
 }
 render(){const t=theme(),p=this.snapshot,c=this.context,selected=this.rows.find(r=>r.ref===this.source),rows=this.rows.filter(r=>(r.label+' '+(r.worktree||'')).toLowerCase().includes(this.filter));
 const text=p?`**${p.branch.replace('refs/heads/','')} ← ${p.source.label}**\n\n${p.kind} · ${p.incoming} incoming / ${p.ahead} stream-only commits\n\nCurrent: \`${p.head.slice(0,12)}\` · source: \`${p.source.oid.slice(0,12)}\`\n\n${[...p.blocked,...p.warnings].join('\n\n')}\n\n${p.commits?'Incoming commits:\n\n    '+p.commits.replace(/\n/g,'\n    '):'No incoming commits.'}\n\n${p.diffstat?'    '+p.diffstat.replace(/\n/g,'\n    '):''}\n\n${p.dirty?'Current changes:\n\n    '+p.dirty.replace(/\n/g,'\n    '):''}`:'Choose a source branch, then preview. A source worktree contributes committed changes only.';
 return v_flex().size_full().min_h(0).p(16).gap(10).bg(toolColors().background).text_color(t.foreground)
 .child(h_flex().items_center().gap(8).flex_none().child(div().flex_1().text_size(18).font_semibold().child('Update this stream')).child(button('sync-close','Close',()=>closeOverlay(props().overlay),{icon:'close',compact:true})))
 .child(caption((c?.repo||'')+' / '+c?.stream+' · '+(c?.on||'This computer')))
 .child(h_flex().gap(6).items_center().justify_end().flex_none()
  .child(button('sync-back',p?'Choose source':'Use main',(_e,cx)=>{if(this.busy)return;if(p){this.snapshot=null;this.attempted=false;}else this.source=this.default;cx.notify();},{icon:'changes'}))
  .child(button('sync-preview',this.busy?'Working…':'Preview',(_e,cx)=>this.request('preview',cx),{icon:'book'}))
  .when(!!selected?.ref.startsWith('refs/remotes/'),e=>e.child(button('sync-fetch','Fetch & preview',(_e,cx)=>this.request('preview',cx,true),{icon:'refresh'})))
  .when(!!p&&!p.blocked.length&&p.incoming>0&&!this.attempted,e=>e.child(button('sync-apply','Merge into '+c.stream,(_e,cx)=>this.request('apply',cx),{icon:'changes',strong:true}))))
 .child(caption('Merges the previewed commit into this stream. No rebase, automatic stash, push, or copying unfinished source edits. Active work blocks the merge.'))
 .when(!p,e=>e.child(Input.new(this.input).h(32).px(8).bg(t.background).border_1().border_color(t.border).rounded(5))
  .child(v_flex().id('sync-sources').flex_1().min_h(0).overflow_y_scrollbar().gap(4).children(rows.map(r=>div().id('source-'+r.ref).p(9).rounded(6).bg(this.source===r.ref?t.selected:t.background).cursor_pointer().on_click((_e,cx)=>{if(!this.busy){this.source=r.ref;cx.notify();}}).child(v_flex().gap(3).child(div().text_size(12).font_semibold().child(r.label)).child(caption(r.worktree||'Remote / local branch without an open worktree')))))))
 .when(!!p,e=>e.child(TextView.markdown('sync-preview-'+p.token,text).selectable(true).scrollable(true).flex_1().min_h(0).p(10).bg(t.background).rounded(6)))
 .when(!!this.message,e=>e.child(div().max_h(160).id('sync-result').overflow_y_scrollbar().p(10).bg(t.background).text_size(12).child(this.message)));
 }
 close(){this.input.release();}
}
