import {View,div} from 'gpui-kit';
import {v_flex,h_flex} from 'gpui-base';
import {theme,props} from 'herdr';
import Reader from './reader.js';
import Changes from './changes.js';
import {button} from './ui.js';
export default class Files extends View{
 init(p,cx){this.mode=['docs','files','git'].includes(props()?.mode)?props().mode:'docs';this.views={};this.get(p,cx);}
 get(p,cx){if(!this.views[this.mode]){const view=this.mode==='git'?new Changes():new Reader();view.init(p,cx);if(this.mode!=='git')view.mode=this.mode;this.views[this.mode]=view;}return this.views[this.mode];}
 render(cx){const t=theme();return v_flex().size_full().min_h(0).min_w(0).bg(t.background)
  .child(h_flex().flex_none().px(8).py(5).gap(4).justify_end().children(['docs','files','git'].map(mode=>button('mode-'+mode,{docs:'Docs',files:'Files',git:'Git'}[mode],(_e,cx)=>{this.mode=mode;cx.notify();},{selected:this.mode===mode,icon:{docs:'book',files:'folder',git:'changes'}[mode]}))))
  .child(this.get(props(),cx).render(cx));}
 close(){for(const view of Object.values(this.views))view.close?.();}
}
