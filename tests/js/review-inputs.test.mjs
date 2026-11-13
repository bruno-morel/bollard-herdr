import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
function fixture(){
 const store={'repo.portrait.lanes':{top:{cwd:'/repo/stream',on:'remote',stream:'example'},bottom:{cwd:'/other',on:'remote'}}};
 let lane='top';
 const source=readFileSync(new URL('../../desktop/shared/scope.js',import.meta.url),'utf8').replace(/^import .*;\n/,'').replaceAll('export ','');
 const api=new Function('props','shared','setShared','terminals',source+';return {requestFile,scopedRequest};')(
  ()=>({lane}),key=>store[key],(key,value)=>store[key]=value,()=>[]);
 return {api,store,select:next=>lane=next};
}
test('review inputs open directly in Files without an agent terminal or shell',()=>{
 const f=fixture(),context=f.store['repo.portrait.lanes'].top;
 const source=readFileSync(new URL('../../herdr/mods/repo-portrait-review/main.js',import.meta.url),'utf8');
 const method=source.slice(source.indexOf(' openInputs(cx){'),source.indexOf('\n button('));
 const view=new Function('location','requestFile','return ({'+method+'});')(()=>context,f.api.requestFile);
 view.openInputs({notify(){}});
 assert.equal(view.actionError,false);
 assert.equal(f.store['repo.portrait.views'].top,'files');
 assert.equal(f.api.scopedRequest().path,'docs/handoffs/example/review-input.json');
 assert.equal(f.api.scopedRequest().local,true);
 assert.equal(f.store['repo.portrait.views'].bottom,undefined);
 f.select('bottom');assert.equal(f.api.scopedRequest(),null);
});
test('file requests stay with the original checkout and select Docs only for text documents',()=>{
 const f=fixture(),c=f.store['repo.portrait.lanes'].top;
 f.api.requestFile(c,'docs/brief.md');assert.equal(f.store['repo.portrait.views'].top,'read');
 f.store['repo.portrait.lanes'].top={...c,cwd:'/different'};
 assert.equal(f.api.scopedRequest(),null);
 for(const path of ['../secret','/secret','bad\0name'])assert.throws(()=>f.api.requestFile(c,path));
});
test('reader opens the requested JSON after resolving a differently cased Git root',()=>{
 const source=readFileSync(new URL('../../herdr/mods/repo-portrait-reader/main.js',import.meta.url),'utf8');
 const method=source.slice(source.indexOf('  openRequested(cx) {'),source.indexOf('  render(cx) {'));
 const request={local:true,on:'remote',root:'/repo/stream',path:'docs/review-input.json',key:'ui:one'};
 const view=new Function('requested','machineOf','return ({'+method+'});')(()=>request,()=> 'remote');
 const opened=[];Object.assign(view,{mode:'files',context:{cwd:'/repo/stream',root:null,on:'remote'},seen:new Set(),load:(...args)=>opened.push(args)});
 view.openRequested({});assert.equal(opened.length,0);assert.equal(view.seen.size,0);
 view.context.root='/Repo/stream';view.openRequested({});assert.equal(opened.length,1);assert.equal(opened[0][0],request.path);
 view.openRequested({});assert.equal(opened.length,1);
 view.seen.clear();view.context.cwd='/other';view.openRequested({});assert.equal(opened.length,1);
 view.context.cwd=request.root;view.mode='docs';view.openRequested({});assert.equal(opened.length,1);
});
