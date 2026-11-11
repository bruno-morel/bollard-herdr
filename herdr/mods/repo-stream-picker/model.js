export const machineOf=a=>a.includes('/')?a.slice(0,a.lastIndexOf('/')):null;
export const slug=s=>String(s||'').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');
export const running=all=>all.filter(t=>t.state==='live'&&['studio','work'].includes(t.labels?.['repo-tools.role'])&&t.labels?.['repo-tools.stream']);
export function sourceForTree(t){return t.stream&&!t.primary?{source:'tree',stream:t.stream,folder:t.folder,checkout:t.path,ref:null}:{source:'new',stream:'',folder:'',ref:t.branch?'refs/heads/'+t.branch:null,checkout:null};}
export function sourceForRef(r){return {source:r.stream?'recover':'new',stream:r.stream||slug(r.branch.split('/').pop()),folder:r.stream||slug(r.branch.split('/').pop()),ref:r.ref,checkout:null};}
export function pairedNames(state,field,value){
 const next={...state,[field]:value,[field+'Edited']:true};
 const other=field==='stream'?'folder':'stream';if(!state[other+'Edited'])next[other]=value;
 return next;
}
export function defaultNames(){return {stream:'',folder:'',streamEdited:false,folderEdited:false};}
