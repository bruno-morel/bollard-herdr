// Pure layout operations. These never start, stop or delete an agent/worktree.
export const clone=x=>JSON.parse(JSON.stringify(x));
export function findNode(n,id){if(n?.id===id)return n;for(const c of n?.children||[]){const found=findNode(c,id);if(found)return found;}return null;}
export function laneIds(tree){const out=[];function walk(n){if(!n)return;const p=n.content?.props;if(n.content?.mod==='repo-portrait'&&p?.kind==='header'&&p.lane)out.push(p.lane);for(const c of n.children||[])walk(c);}walk(tree);return [...new Set(out)];}
export function makeLane(template,id){
 const n=clone(template),old=n.id.slice(0,-5);
 function walk(x){if(!x)return;if(x.id?.startsWith(old+'-'))x.id=id+x.id.slice(old.length);if(x.active?.startsWith(old+'-'))x.active=id+x.active.slice(old.length);if(x.content?.props?.lane===old){x.content.props.lane=id;delete x.content.props.context;}for(const c of x.children||[])walk(c);}
 walk(n);n.size={weight:1};n.min=200;
 const tools=findNode(n,id+'-views');if(tools){tools.hidden=true;tools.active=id+'-read';tools.size={weight:.48};}
 const body=findNode(n,id+'-conversation');if(body)body.content={mod:'repo-portrait',props:{kind:'empty',lane:id}};
 const info=findNode(n,id+'-info');if(info)info.hidden=true;return n;
}
export function addLane(tree,id,{axis='column',target=null}={}){
 if(!['row','column'].includes(axis))throw Error('Choose below or beside.');
 const copy=clone(tree),ids=laneIds(copy);if(ids.includes(id))throw Error('Stream slot already exists.');
 const root=findNode(copy,'portrait-streams'),template=findNode(copy,ids[0]+'-lane');if(!root||!template)throw Error('Stream layout unavailable.');
 const fresh=makeLane(template,id);
 if(target){
  function split(n){for(let i=0;i<(n.children||[]).length;i++){const c=n.children[i];if(c.id===target+'-lane'){const size=c.size;c.size={weight:1};n.children[i]={id:'split-'+id,type:axis,size,gap:8,divider:{width:1,color:'border'},children:[c,fresh]};return true;}if(split(c))return true;}return false;}
  if(!split(root))throw Error('That stream is no longer displayed.');
 }else if(root.type===axis)root.children.push(fresh);
 else{const children=root.children;root.children=[{id:'group-'+id,type:root.type,children,size:{weight:Math.max(1,ids.length)},gap:8,divider:{width:1,color:'border'}},fresh];root.type=axis;}
 return copy;
}
export function removeLane(tree,id){
 if(!tree || typeof tree!=='object')throw Error('Layout is unavailable. Reopen the stream menu and try again.');
 const copy=clone(tree),ids=laneIds(copy);if(!ids.includes(id))return copy;
 if(ids.length===1){const root=findNode(copy,'portrait-streams');root.children=[makeLane(findNode(copy,id+'-lane'),id)];return copy;}
 function prune(n){if(!n)return null;if(n.id===id+'-lane')return null;if(n.children)n.children=n.children.map(prune).filter(Boolean);
  if((n.id?.startsWith('split-')||n.id?.startsWith('group-'))&&n.children?.length===1){const child=n.children[0];child.size=n.size||{weight:1};return child;}return n;}
 return prune(copy);
}

// Clear only per-view state. Do not stop terminals, remove worktrees, or touch
// operation checkpoints; closing a view must not cancel work in the background.
export function withoutLaneState(value, id, prefixed=false) {
 return Object.fromEntries(Object.entries(value || {}).filter(([key]) =>
   prefixed ? !key.startsWith(id+':') : key !== id));
}
