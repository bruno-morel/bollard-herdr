import {View,div} from 'gpui-kit';
import {v_flex,h_flex,Input,InputState,Editor,EditorState} from 'gpui-base';
import {props,theme,settings,exec,closeOverlay,notify,nextCommand} from 'herdr';
import {button} from './ui.js';
export const PRESETS={
 'investigate-failure':{title:'Investigate failure',icon:'test',question:'Explain the failure, distinguish evidence from hypotheses, and propose the smallest next check or fix.',detail:'Inspect evidence and relevant code. Propose checks and fixes; do not run tests or change files.'},
 'campaign-follow-up':{title:'Campaign follow-up',icon:'gauge',question:'Review campaign performance for the specified dates and suggest one measurable next experiment.',detail:'Read connected Metricool analytics for these dates. Report gaps honestly. No scheduling, posting, paid actions or monitors.'},
 'pre-publication':{title:'Pre-publication check',icon:'shield',question:'Check claims, links, tracking, consistency and missing assets. Separate blockers from suggestions.',detail:'Review the draft and referenced material. Report blockers and proposed corrections. No publication or edits.'},
};
export function buildArgs(context,snapshot,preset,agent,question,period,comparison){
 if(!context?.cwd||!context?.stream||!snapshot?.text||!snapshot?.parent)throw new Error('Reopen Ask a helper from a pane with selected evidence.');
 if(!PRESETS[preset]||!['codex','claude','cursor'].includes(agent))throw new Error('Choose a preset and Codex, Claude or Cursor.');
 if(!question.trim()||question.length>4000)throw new Error('Give a focused question under 4,000 characters.');
 if(preset==='campaign-follow-up'&&(!/^\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}$/.test(period)||!/^\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}$/.test(comparison)))throw new Error('Enter both reporting windows as YYYY-MM-DD..YYYY-MM-DD.');
 const args=['flow','helper',context.stream,'--role',context.role,'--kind','research','--agent',agent,'--preset',preset,'--scope',question,'--context-json',JSON.stringify(snapshot)];
 if(preset==='campaign-follow-up')args.push('--period',period,'--compare-period',comparison);
 return args;
}
export default class Helper extends View{
 init(_p,cx){const p=props()||{};this.context=p.context;this.snapshot=p.snapshot;this.preset=PRESETS[p.preset]?p.preset:'investigate-failure';this.agent=p.agent==='cursor'?'cursor':'codex';this.busy=false;this.attempted=false;this.message='';
  this.question=InputState.new({value:PRESETS[this.preset].question});this.period=InputState.new({placeholder:'2026-11-01..2026-11-07'});this.comparison=InputState.new({placeholder:'2026-10-25..2026-10-31'});
  this.preview=EditorState.new({readonly:true,value:this.snapshot?.text||'Open this dialog from a pane to select its evidence.',soft_wrap:true,line_numbers:false,folding:false,font_size:12,font_family:settings().font_family});
  cx.spawn(async cx=>{for(;;){const cmd=await nextCommand();if(cmd.startsWith('preset:'))this.choose(cmd.slice(7),cx);}});
 }
 choose(id,cx){if(!PRESETS[id]||this.busy||this.attempted)return;const old=PRESETS[this.preset].question;if(this.question.value()===old)this.question.set_value(PRESETS[id].question);this.preset=id;this.message='';cx.notify();}
 submit(cx){if(this.busy||this.attempted)return;let args;try{args=buildArgs(this.context,this.snapshot,this.preset,this.agent,this.question.value().trim(),this.period.value().trim(),this.comparison.value().trim());}catch(e){this.message=String(e);cx.notify();return;}
  this.busy=true;this.message='Validating the selected context…';cx.notify();
  cx.spawn(async cx=>{try{
   // Validation cannot launch a terminal or consume a model call.
   const opts={cwd:this.context.cwd,on:this.context.on};const check=await exec(this.context.role,[...args,'--preview'],opts);
   if(check.code)throw new Error(check.stderr||check.stdout||'Context validation failed.');
   this.attempted=true;this.message='Opening the helper…';cx.notify();
   const r=await exec(this.context.role,args,opts);
   if(r.code)throw new Error(r.stderr||r.stdout||'The launch did not report success.');
   notify({title:'Helper opened · '+PRESETS[this.preset].title,body:'Read its report in the stream’s separate Helper tab. Your lead conversation stays in place.',level:'success'});
   closeOverlay(props().overlay);
  }catch(e){this.message=String(e)+(this.attempted?'\nInspect this stream’s Helper tabs before trying again; a timed-out launch may have succeeded.':'');}finally{this.busy=false;cx.notify();}});
 }
 field(label,state){const t=theme();return v_flex().gap(4).flex_1().max_h(56).child(div().text_size(11).text_color(t.muted).child(label)).child(Input.new(state).h(34).px(8).items_center().border(1).border_color(t.border).rounded(5).bg(t.background).text_color(t.foreground));}
 render(cx){const t=theme(),c=this.context,s=this.snapshot,p=PRESETS[this.preset];
  return v_flex().size_full().min_h(0).p(18).gap(10).bg(t.surface).text_color(t.foreground)
   .child(h_flex().items_center().gap(8).flex_none().child(div().flex_1().font_semibold().text_size(19).child('Ask a helper about this')).child(div().text_size(11).text_color(t.ansi2).child('Read-only')))
   .child(div().text_size(12).text_color(t.muted).child(c?`${c.repo||c.stream} / ${c.stream} · ${c.role} · ${c.on||'This computer'}`:'No pane selected'))
   .child(h_flex().gap(6).flex_wrap().flex_none().children(Object.entries(PRESETS).map(([id,p])=>button('preset-'+id,p.title,(_e,cx)=>this.choose(id,cx),{icon:p.icon,selected:id===this.preset}))))
   .child(h_flex().gap(6).items_center().flex_none().children(['codex','claude','cursor'].map(a=>button('helper-'+a,a[0].toUpperCase()+a.slice(1),(_e,cx)=>{if(!this.busy&&!this.attempted){this.agent=a;cx.notify();}},{selected:a===this.agent}))).child(div().text_size(11).text_color(t.muted).child('Selected account usage; review budget unchanged')))
   .child(div().text_size(12).text_color(t.muted).child(p.detail))
   .child(this.field('Question for the helper',this.question))
   .when(this.preset==='campaign-follow-up',el=>el.child(h_flex().gap(10).flex_none().child(this.field('Reporting dates (inclusive)',this.period)).child(this.field('Comparison dates (same length)',this.comparison))))
   .child(div().font_semibold().text_size(12).child('Context preview · '+(s?.pane||'pane')+' · '+(s?.source||'')))
   .child(div().text_size(11).text_color(s?.draft||s?.truncated?t.blocked:t.muted).child([s?.captured_at,s?.head?'Commit '+s.head.slice(0,9):'',s?.observed_at?'Observed '+s.observed_at:'',s?.draft?'UNSAVED DRAFT · shared as shown; not saved':'',s?.truncated?'Excerpt only · '+(s?.pane==='docker'?'last':'first')+' 18,000 characters':''].filter(Boolean).join(' · ')))
   .child(Editor.new(this.preview).flex_1().min_h(110).rounded(6).border(1).border_color(t.border))
   .child(div().text_size(11).text_color(t.muted).child('Shares this snapshot and permits relevant read-only investigation. No full conversation is sent. Findings stay in the helper tab; your lead decides what to adopt. One helper at a time.'))
   .when(!!this.message,el=>el.child(div().text_size(11).text_color(t.blocked).child(this.message)))
   .child(h_flex().gap(8).justify_end().flex_none().child(button('helper-cancel',this.busy?'Close preview':'Cancel',()=>closeOverlay(props().overlay)))
    .when(!this.busy&&!this.attempted,el=>el.child(button('helper-start','Start read-only helper',(_e,cx)=>this.submit(cx),{icon:'agents',strong:true}))))
  ;
 }
 close(){this.question.release();this.period.release();this.comparison.release();this.preview.release();}
}
