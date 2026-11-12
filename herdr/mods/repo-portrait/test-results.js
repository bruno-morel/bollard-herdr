import {div} from 'gpui-kit';
import {h_flex,v_flex} from 'gpui-base';
import {theme} from 'herdr';
import {palette,badge} from './metrics.js';
import {button} from './ui.js';
export function checkRows(s){return (s?.checks||[]).map(check=>{
 const result=(s.results||[]).find(r=>r.id===check.id);
 const state=result?result.exit_code===0?'passed':result.exit_code===-1?'interrupted':'failed':s.current===check.id?'running':['failed','passed','incomplete','stale'].includes(s.state)?'not run':'pending';
 return {...check,result,state:s.state==='stale'?'stale':state,previousState:state};
});}
export function countLabel(n){
 if(!n)return 'Count unavailable';
 if(n.failed>0)return n.failed+' failed';
 return n.passed+' passed'+(n.skipped?' · '+n.skipped+' skipped':'')+(n.flaky?' · '+n.flaky+' flaky':'');
}
export function resultsView(s,chosen,choose){
 const t=theme(),p=palette(),rows=checkRows(s),ink={passed:p.green,failed:p.red,interrupted:p.amber,running:p.blue,pending:t.dim,'not run':t.dim,stale:p.amber};
 const counts=rows.reduce((a,r)=>(a[r.state]=(a[r.state]||0)+1,a),{});
 return v_flex().px(12).gap(6).flex_1().min_h(0)
 .child(h_flex().gap(6).items_center().flex_wrap().flex_none()
  .children(Object.entries(counts).map(([state,n])=>badge(n+' '+state.toUpperCase(),ink[state])))
  .child(div().flex_1()).child(div().text_size(10).text_color(t.muted).child(rows.length+' CHECKS')))
 .child(v_flex().id('check-rows').flex_1().min_h(0).overflow_y_scrollbar().gap(4).children(rows.map(r=>{
  const n=r.result?.native_summary,selected=chosen===r.id;
  return h_flex().id('result-'+r.id).flex_none().w_full().px(9).py(5).gap(8).items_center().rounded(6).bg(selected?ink[r.state]+'18':t.background).border_1().border_color(selected?ink[r.state]:t.border)
   .child(div().flex_1().min_w(0).truncate().font_semibold().text_size(12).tooltip(r.id+' · '+r.argv.join(' ')).child(r.id))
   .child(badge(r.state==='stale'?'stale · '+r.previousState:r.state,ink[r.state]).text_size(10).flex_none())
   .child(div().min_w(76).text_size(11).text_color(n?.failed&&r.state!=='stale'?p.red:t.muted).tooltip(n?`${n.passed} passed · ${n.failed} failed · ${n.skipped} skipped${n.flaky?' · '+n.flaky+' flaky':''}`:'Test-case count was not reported; status comes from the command exit code.').child(countLabel(n)))
   .child(button('logs-'+r.id,selected?'Hide logs':'Logs',(_e,cx)=>choose(r.id,cx),{icon:'list',selected}));
 })))
 .child(div().text_size(10).text_color(t.muted).flex_none().child('One row per project check. Counts come from native test reports; unavailable counts do not mean failure.'));
}
