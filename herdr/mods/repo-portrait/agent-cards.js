export const agentState=r=>typeof r?.status==='string'?r.status:r?.status?.state;
const machine=a=>a.includes('/')?a.slice(0,a.lastIndexOf('/')):null;
export function parentAddress(row){const p=row.parent;if(!p)return null;return p.includes('/')?p:(machine(row.address)?machine(row.address)+'/':'')+p;}
export function scopedAgents(all,c){
 if(!c)return [];
 const live=all.filter(r=>r.state==='live'&&machine(r.address)===c.on),selected=new Set(live.filter(r=>r.labels?.['repo-tools.stream']===c.stream&&((r.labels?.['repo-tools.checkout']||r.cwd)===c.cwd||r.labels?.['repo-tools.parent-checkout']===c.cwd)).map(r=>r.address));
 let changed=true;while(changed){changed=false;for(const r of live)if(!selected.has(r.address)&&selected.has(parentAddress(r))){selected.add(r.address);changed=true;}}
 return live.filter(r=>selected.has(r.address));
}
export function agentTree(rows,lead){
 const out=[],seen=new Set(),ids=new Set(rows.map(r=>r.address));
 const visit=(r,depth)=>{if(seen.has(r.address))return;seen.add(r.address);out.push({row:r,depth});for(const child of rows)if(parentAddress(child)===r.address)visit(child,depth+1);};
 const roots=rows.filter(r=>!ids.has(parentAddress(r))).sort((a,b)=>(b.address===lead?1:0)-(a.address===lead?1:0));
 roots.forEach(r=>visit(r,0));rows.forEach(r=>visit(r,0));return out;
}
export function statusKind(row){const s=agentState(row)||'unknown';return ['error','failed'].includes(s)?'error':s==='blocked'?'attention':s==='working'?'working':s==='done'?'done':'idle';}
export function memoryReading(service){
 const m=service.Metrics;if(!m)return null;
 const parse=text=>{const a=/^([\d.]+)\s*([KMGT]?i?B)$/i.exec((text||'').trim());if(!a)return null;const unit=a[2].toUpperCase(),exp='KMGT'.indexOf(unit[0])+1;return Number(a[1])*Math.pow(unit.includes('I')?1024:1000,Math.max(0,exp));};
 const [usedText,limitText]=(m.MemUsage||'').split('/').map(x=>x.trim()),used=parse(usedText),reportedLimit=parse(limitText),configured=Number(service.MemoryLimitBytes),capped=Number.isFinite(configured)&&configured>0;
 const limit=capped?configured:reportedLimit,pct=used!==null&&limit>0?100*used/limit:null;
 const size=n=>n>=1024**3?(n/1024**3).toFixed(1)+' GiB':Math.round(n/1024**2)+' MiB';
 return {used:usedText||'—',limit:capped?size(configured):limitText||'—',pct,capped,kind:capped?'container cap':service.MemoryLimitBytes===0?'shared host limit':'reported limit'};
}
