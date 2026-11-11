import {terminals,openOverlay,notify} from 'herdr';
// Account creation returns before the desktop receives the core's terminal event.
// Wait for that event, then show a dedicated overlay (never the lead terminal).
export function showAccount(address,cx,done,attempt=0){
 if(terminals().some(t=>t.address===address&&t.state==='live')){
  const isClaude=terminals().find(t=>t.address===address)?.labels?.['repo-tools.account']==='claude';
  openOverlay({kind:'dialog',width:1000,height:650,layout:{type:'column',children:[
   {type:'block',size:{px:isClaude?110:36},content:{mod:isClaude?'repo-portrait':'peek',props:{kind:'account-header',terminal:address}}},
   {type:'block',content:{terminal:address}}
  ]}});done?.('Sign-in pane opened. Complete the browser step, then refresh your account.',cx);return;
 }
 if(attempt>=24){const message='The account terminal is starting. Click Open sign-in to try showing it again, or run hc attach '+address.split('/').pop()+' on JumpBox.';done?.(message,cx);notify({title:'Sign-in is waiting',body:message,level:'warning'});return;}
 cx.timer.after(500,next=>showAccount(address,next,done,attempt+1));
}
