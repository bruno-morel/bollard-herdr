import {div} from 'gpui-kit';
import {v_flex,v_virtual_list,Scrollbar} from 'gpui-base';
import {settings} from 'herdr';
export function logText(value){return String(value||'').replace(/\r\n/g,'\n').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'').replace(/[\n\r]+$/,'');}
export function escapeLog(value){return logText(value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
export function logRows(text,columns=120){
 const rows=[];for(const line of logText(text).split('\n')){if(!line.length)rows.push('');else for(let i=0;i<line.length;i+=columns)rows.push(line.slice(i,i+columns));}return rows;
}
export function logView(id,text,owner){
 const rows=logRows(text,Math.max(25,Math.floor(((owner.logWidth||900)-28)/7.4)));
 return v_flex().relative().flex_1().min_h(0).min_w(0)
 .on_size_change((size,cx)=>{if(Math.abs(size.width-(owner.logWidth||0))>8){owner.logWidth=size.width;cx.notify();}})
 .on_scroll_wheel((_e,cx)=>{if(owner.follow){owner.follow=false;cx.notify();}})
 .child(v_virtual_list(id,rows.length,20,i=>String(i),range=>rows.slice(range.start,range.end).map((line,j)=>div().id(id+'-'+(range.start+j)).h(20).px(10).font_family(settings().font_family||'Menlo').text_size(12).child(line||' '))).track_scroll(owner.logScroll).flex_1().min_h(0))
 .child(Scrollbar.vertical(id).absolute().inset_0());
}
