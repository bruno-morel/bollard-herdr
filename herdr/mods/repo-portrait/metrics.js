import {div,PathBuilder} from 'gpui-kit';
import {h_flex,v_flex,Progress,ProgressTrack,ProgressIndicator} from 'gpui-base';
import {theme,settings} from 'herdr';

export const count = n => Math.round(Number(n)).toString().replace(/\B(?=(\d{3})+(?!\d))/g,',');
export const clamp = n => Math.min(100,Math.max(0,n));
export const number = n => n !== null && n !== undefined && n !== '' && Number.isFinite(Number(n)) ? Number(n) : null;
export const percent = n => number(n) === null ? null : number(n);
export function duration(seconds){
 if(number(seconds)===null)return 'Unavailable';
 const n=Math.max(0,Math.floor(seconds)),d=Math.floor(n/86400),h=Math.floor(n%86400/3600),m=Math.floor(n%3600/60);
 return d?`${d}d ${h}h`:h?`${h}h ${m}m`:m?`${m}m`:`${n}s`;
}
export function palette(){const dark=settings().dark;return {green:dark?'#5cdbb0':'#168366',amber:dark?'#f5c267':'#a36713',red:dark?'#ff928f':'#be4148',blue:dark?'#7bbcff':'#307cba',violet:dark?'#b9a0ff':'#7854b5'};}
export function level(n){const p=palette();return n>=90?p.red:n>=75?p.amber:p.green;}
export function badge(text,color){return div().px(7).py(3).rounded(5).text_size(10).font_semibold().bg(color+'18').text_color(color).child(text);}
export function meter(id,value,label,color=null,height=9){
 const t=theme(),n=percent(value),ink=color||(n===null?t.muted:level(n));
 if(n===null)return div().h(height).w_full().rounded(5).bg(t.border).tooltip(label+' unavailable');
 return Progress.new(id).value(clamp(n)).accessibility_label(label).w_full()
 .child(ProgressTrack.new().relative().h(height).w_full().rounded(5).overflow_hidden().bg(ink+'20')
 .child(ProgressIndicator.new().h_full().w(clamp(n)+'%').rounded(5).bg(ink).transition('width',250)));
}
export function stat(label,value,color){return v_flex().flex_1().min_w(0).gap(3).child(div().text_size(10).text_color(theme().muted).child(label)).child(div().text_size(17).font_semibold().text_color(color||theme().foreground).child(String(value)));}
export function meterCard(id,title,amount,note,color=null){
 const t=theme(),n=percent(amount),ink=color||(n===null?t.muted:level(n));
 return v_flex().gap(10).p(12).rounded(9).bg(t.background).border_1().border_color(t.border)
 .child(h_flex().gap(8).items_center().child(div().flex_1().text_size(11).font_semibold().child(title)).child(badge(n===null?'NO DATA':n>=90?'NEAR LIMIT':n>=75?'WATCH':'AVAILABLE',ink)))
 .child(h_flex().gap(8).items_end().child(div().text_size(32).font_semibold().text_color(ink).child(n===null?'—':Math.round(n)+'%')).child(div().pb(4).text_size(11).text_color(t.muted).child('used')))
 .child(meter(id,n,title,ink))
 .when(n!==null,e=>e.child(div().text_size(11).text_color(t.muted).child(Math.max(0,Math.round(100-n))+'% remaining')))
 .when(!!note,e=>e.child(div().text_size(10).text_color(t.muted).child(note)));
}

// Small, three-zone dial. Numbers and labels also carry the meaning of colour.
export function quotaGeometry(value){
 const n=percent(value),point=(v,r)=>[31+Math.cos(Math.PI*(1+v))*r,32+Math.sin(Math.PI*(1+v))*r];
 const zones=[[0,.75],[.75,.9],[.9,1]].map(([a,b])=>{
  const points=[],start=a+.007,end=b-.007;
  for(let i=0;i<=24;i++)points.push(point(start+(end-start)*i/24,27));
  for(let i=24;i>=0;i--)points.push(point(start+(end-start)*i/24,21));
  return points;
 });
 const angle=Math.PI*(1+clamp(n??0)/100),tip=point(clamp(n??0)/100,19),dx=Math.cos(angle+Math.PI/2)*2,dy=Math.sin(angle+Math.PI/2)*2;
 return {zones,needle:n===null?null:[[31+dx,32+dy],tip,[31-dx,32-dy]],value:n===null?null:clamp(n)};
}
export function quotaCard(id,title,amount,note){
 const t=theme(),p=palette(),g=quotaGeometry(amount),ink=g.value===null?t.muted:level(g.value);
 const draw=(points,color)=>window.paint_path(PathBuilder.fill().add_polygon(points,true).build(),color).absolute().inset_0();
 let dial=div().id(id+'-dial').relative().w(62).h(37).flex_none().accessibility_label(title+': '+(g.value===null?'unavailable':g.value+' percent used'))
  .tooltip('Used allowance: green below 75%, yellow 75–89%, red 90–100%.')
  .children(g.zones.map((points,i)=>draw(points,[p.green,'#e2b33e',p.red][i])));
 if(g.needle)dial=dial.child(draw(g.needle,t.foreground)).child(div().absolute().left(28).top(29).size(6).rounded(3).bg(t.foreground));
 return h_flex().gap(9).p(8).items_center().rounded(8).bg(t.background).border_1().border_color(t.border)
  .child(dial).child(v_flex().flex_1().min_w(0).gap(3)
   .child(div().text_size(10).font_semibold().child(title))
   .child(h_flex().gap(6).items_center()
    .child(div().text_size(19).font_semibold().text_color(ink).child(g.value===null?'—':Math.round(g.value)+'%'))
    .child(div().text_size(10).text_color(t.muted).child(g.value===null?'No reading':'used · '+Math.round(100-g.value)+'% left')))
   .when(!!note,e=>e.child(div().text_size(10).text_color(t.muted).child(note))));
}
