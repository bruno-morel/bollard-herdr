import {div} from 'gpui-kit';
import {h_flex,v_flex,Select,Popup,v_virtual_list} from 'gpui-base';
import {theme} from 'herdr';

// A native combobox: keyboard and pointer use exactly the same selection path.
export function dropdown(owner,cx,id,title,value,options,choose){
 const t=theme();owner.dropdowns??={};
 const s=owner.dropdowns[id];
 const setOpen=(open,cx)=>{if(owner.busy||owner.loading)return;for(const d of Object.values(owner.dropdowns))d.open=false;s.open=open;s.at=Math.max(0,options.findIndex(o=>o.value===value));if(options.length)s.scroll.scroll_to_item(s.at,'center');if(open)s.list.focus();else s.focus.focus();cx.notify();};
 const pick=(i,cx)=>{if(!options[i]||owner.busy||owner.loading)return;s.open=false;choose(options[i].value,cx);s.focus.focus();cx.notify();};
 const trigger=h_flex().id(id+'-trigger').track_focus(s.focus).w_full().gap(8).items_center().px(10).py(8).rounded(6).border_1().border_color(t.border).bg(t.background).cursor_pointer()
  .on_mouse_down('left',(_e,cx)=>{cx.stop_propagation();setOpen(!s.open,cx);})
  .child(div().flex_1().min_w(0).truncate().child(options.find(o=>o.value===value)?.label||'Choose…'))
  .child(div().text_color(t.muted).child('▾'));
 const list=v_flex().id(id+'-options').w(440).p(4).rounded(7).border_1().border_color(t.border).bg(t.popover)
  .track_focus(s.list).on_key_down((e,cx)=>{
   if(e.key==='down')s.at=Math.min(s.at+1,options.length-1);
   else if(e.key==='up')s.at=Math.max(0,s.at-1);
   else if(e.key==='home')s.at=0;
   else if(e.key==='end')s.at=options.length-1;
   else if(e.key==='enter'){pick(s.at,cx);cx.stop_propagation();return;}
   else if(e.key==='escape'){s.open=false;s.focus.focus();}
   else return;
   s.scroll.scroll_to_item(s.at,'center');cx.stop_propagation();cx.notify();
  }).child(v_virtual_list(id+'-rows',options.length,46,i=>JSON.stringify(options[i].value),(range,cx)=>options.slice(range.start,range.end).map((o,n)=>{const i=range.start+n;return v_flex().id(id+'-'+i).role('list_box_option').when(i===s.at,e=>e.aria_active_descendant()).px(9).py(5).h(46).rounded(5)
   .bg(i===s.at?t.selected:t.popover).cursor_pointer().hover(e=>e.bg(t.hover))
   .child(div().text_size(12).truncate().child(o.label)).when(!!o.detail,e=>e.child(div().text_size(10).text_color(t.muted).truncate().child(o.detail)));})).h(Math.min(230,options.length*46)).w_full().track_scroll(s.scroll)
   .on_item_click((key,cx)=>{cx.stop_propagation();pick(options.findIndex(o=>JSON.stringify(o.value)===key),cx);}));
 return v_flex().flex_1().min_w(0).gap(4)
  .child(div().text_size(11).text_color(t.muted).child(title))
  .child(Select.new(id).w_full().accessibility_label(title).open(s.open).track_focus(s.focus).content_focus_handle(s.list)
   .on_open_change(setOpen).on_confirm((_e,cx)=>pick(s.at,cx))
   .child(Popup.new(id+'-popup',trigger).anchor('bottom_left').when(s.open,e=>e.content(list))));
}
