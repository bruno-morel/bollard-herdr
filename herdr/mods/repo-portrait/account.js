import {View,div} from 'gpui-kit';
import {v_flex,h_flex} from 'gpui-base';
import {exec,props,terminals,theme,closeOverlay,notify} from 'herdr';
import {button} from './ui.js';
import {showAccount} from './account-pane.js';
export default class Account extends View {
 init(_p,cx){this.provider=props()?.provider||terminals().find(t=>t.address===props()?.terminal)?.labels?.['repo-tools.account']||'claude';this.url=null;this.error='';this.busy=false;this.checking=false;this.connected=false;this.load(cx);this.check(cx);cx.timer.every(5000,cx=>this.check(cx));}
 location(){const address=props()?.terminal||'',cut=address.lastIndexOf('/');return {on:cut<0?null:address.slice(0,cut),id:address.slice(cut+1)};}
 check(cx){if(this.checking||this.connected)return;this.checking=true;const {on}=this.location();cx.spawn(async cx=>{try{const r=await exec('repo-provider.py',['connection',this.provider],{on});if(!r.code){const result=JSON.parse(r.stdout);if(result.connected){this.connected=true;this.url=null;this.error='';notify({title:this.provider==='cursor'?'Cursor connected':'Claude connected',body:'Sign-in succeeded on '+(on||'this computer')+'. You can close this pane.',level:'success'});}}}catch{}finally{this.checking=false;cx.notify();}});}
 load(cx,attempt=0){if(this.busy||this.connected)return;this.busy=true;this.url=null;const {on,id}=this.location();
  cx.spawn(async cx=>{try{const r=await exec('repo-provider.py',['login-link',this.provider,'--terminal',id],{on});if(r.code)throw Error('The login link is not ready. Refresh the link, or use Fresh login if the attempt expired.');const out=JSON.parse(r.stdout);this.url=out.url;this.error='';}catch(e){this.error=attempt<8?'Preparing the browser login link…':String(e);if(attempt<8)cx.timer.after(1000,next=>this.load(next,attempt+1));}finally{this.busy=false;cx.notify();}});
 }
 fresh(cx){if(this.busy)return;this.busy=true;this.url=null;const {on}=this.location(),id=props()?.overlay;
  cx.spawn(async cx=>{try{const r=await exec('repo-provider.py',['login',this.provider,'--fresh'],{on});if(r.code)throw Error(r.stderr||r.stdout);const out=JSON.parse(r.stdout);closeOverlay(id);showAccount((on?on+'/':'')+out.terminal,cx);}catch(e){this.error=String(e);}finally{this.busy=false;cx.notify();}});
 }
 render(cx){const t=theme(),label=this.provider==='cursor'?'Cursor':'Claude';return v_flex().size_full().px(12).py(7).gap(6).bg(t.chrome).text_color(t.foreground)
  .child(h_flex().gap(5).items_center().child(div().flex_1().font_semibold().child(label+' · '+(this.connected?'Connected': 'Sign in on '+(this.location().on||'this computer'))))
   .when(!this.connected,e=>e.child(button('login-browser','Open login in browser',(_e,cx)=>{if(this.url)cx.open_url(this.url);},{icon:'external',strong:true}).opacity(this.url?1:.5))
    .child(button('login-copy','Copy login link',(_e,cx)=>{if(this.url)cx.write_to_clipboard(this.url);},{icon:'copy'}).opacity(this.url?1:.5))
    .child(button('login-fresh','Fresh login',(_e,cx)=>this.fresh(cx),{icon:'refresh'}))
    .child(button('login-refresh','Refresh link',(_e,cx)=>this.load(cx),{icon:'refresh',compact:true})))
   .child(button('login-close','Close sign-in',()=>closeOverlay(props()?.overlay),{icon:'close',compact:true})))
  .child(div().text_size(11).text_color(this.connected?'#168366':t.muted).child(this.connected?'Signed in successfully. Your account panel will refresh automatically.':this.error||'Open the login link in your laptop browser. '+(this.provider==='cursor'?'Finish signing in there; this pane will detect completion automatically.':'Use the intact link above, then paste the returned code below.')));
 }
}
