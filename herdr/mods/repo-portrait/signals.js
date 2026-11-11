import {shared,setShared,props} from 'herdr';
export const SIGNALS='repo.portrait.signals';
export const COMPLETE='repo.portrait.completed';
export function reportPanel(panel,context,error){const lane=props()?.lane;if(!lane||!context)return;const all=shared(SIGNALS)||{},key=lane+':'+panel,value={context:context.key||JSON.stringify([context.on,context.cwd]),error:!!error};if(JSON.stringify(all[key])!==JSON.stringify(value))setShared(SIGNALS,{...all,[key]:value});}
export function panelFailed(lane,context,panels){const all=shared(SIGNALS)||{},key=JSON.stringify([context?.on,context?.cwd]);return panels.some(p=>all[lane+':'+p]?.context===key&&all[lane+':'+p]?.error);}
export const agentState=r=>typeof r?.status==='string'?r.status:r?.status?.state;
export function interactionTone(rows,lead,complete){if(rows.some(r=>['error','failed'].includes(agentState(r))))return 'error';if(rows.some(r=>agentState(r)==='blocked'))return 'attention';if(['idle','done'].includes(agentState(lead))||complete?.[lead?.address])return 'ready';return null;}
