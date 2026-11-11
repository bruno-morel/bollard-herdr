import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

test('a window acknowledgement failure cannot replay the opening request', async()=>{
 const id='host/t9'; const store={'repo.open-requests':{[id]:{on:'host',terminal:'t9',stream:'demo',cwd:'/repo',lane:'top',newWindow:true,time:Date.now()}}};
 let launches=0;
 globalThis.navigationTest={
  operation:()=>({}),addLane:()=>{},laneIds:()=>['top'],layout:()=>({}),
  shared:key=>store[key],setShared:(key,v)=>{store[key]=v;},terminals:()=>[],
  exec:async(command)=>{
   if(command==='work')return {code:0,stdout:JSON.stringify({terminal:'t9',state:'ready',lead:'t1'})};
   launches++;throw Error('window opened but socket timed out');
  },
  hc:async()=>({code:0,stdout:JSON.stringify({address:'t1',cwd:'/repo',labels:{'repo-tools.stream':'demo','repo-tools.role':'work'}})}),
  run:()=>{},notify:()=>{},appHome:()=>'/app'
 };
 const source=readFileSync(new URL('../../desktop/shared/navigation.js',import.meta.url),'utf8').replace(/import\s*\{[^}]*\}\s*from\s*'[^']+';/g,'');
 const prelude='const {operation,addLane,laneIds,shared,setShared,terminals,exec,hc,run,notify,appHome,layout}=globalThis.navigationTest;\n';
 const {followOpens}=await import('data:text/javascript;base64,'+Buffer.from(prelude+source).toString('base64'));
 await Promise.all([followOpens(),followOpens()]);
 await followOpens();
 assert.equal(launches,1);
 assert.deepEqual(store['repo.open-requests'],{});
 assert.equal(store['repo.operation-status'].top.error,true);
 delete globalThis.navigationTest;
});
