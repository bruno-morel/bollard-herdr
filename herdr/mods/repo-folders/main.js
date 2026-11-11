import { View, div } from 'gpui-kit';
import { v_flex,h_flex,InputState,Input } from 'gpui-base';
import { props,shared,setShared,closeOverlay,theme } from 'herdr';
export default class Folders extends View {
 init(_p,cx){this.input=InputState.new({value:(shared('repo.space-folders')||{})[props()?.space]||'',placeholder:'Folder name, e.g. Marketing'});this.input.on('submit',()=>this.save());this.input.focus();}
 save(){const p=props();if(!p?.space)return;const all={...(shared('repo.space-folders')||{})},name=this.input.value().trim().slice(0,60);if(name)all[p.space]=name;else delete all[p.space];setShared('repo.space-folders',all);closeOverlay(p.overlay);}
 render(){const t=theme(),folders=[...new Set(Object.values(shared('repo.space-folders')||{}))];
  const b=(id,name,fn)=>div().id(id).px(10).py(7).rounded(5).text_size(12).hover(s=>s.bg(t.hover)).cursor_pointer().on_click(fn).child(name);
  return v_flex().p(18).gap(12).bg(t.popover).text_color(t.foreground)
   .child(div().text_size(16).font_semibold().child('Organize '+(props()?.name||'space')))
   .child(Input.new(this.input).h(34).px(8).rounded(6).border_1().border_color(t.input).bg(t.background))
   .child(div().text_size(12).text_color(t.muted).child('Blank uses the automatic repository folder. This organizes the sidebar; files and worktrees stay in place.'))
   .child(h_flex().flex_wrap().gap(4).children(folders.map((f,i)=>b('folder-'+i,f,()=>{this.input.set_value(f);}))))
   .child(h_flex().justify_end().gap(8).child(b('cancel','Cancel',()=>closeOverlay(props().overlay))).child(b('save','Save',()=>this.save())));
 }
 async close(){this.input.release();}
}
