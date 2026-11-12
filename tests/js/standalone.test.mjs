import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

test('standalone backend routes plain Compose and managed stream commands without losing their original scope',async()=>{
 const calls=[];
 globalThis.panelHostTest={hostExec:(...args)=>{calls.push(args);return Promise.resolve({code:0,stdout:'{}'});},props:()=>({}),terminals:()=>[],spaces:()=>[],panes:()=>[],focused:()=>({}),selectLocation:()=>null,selectRequest:()=>null,machineOf:()=>null};
 const source=readFileSync(new URL('../../desktop/standalone/panel-host.js',import.meta.url),'utf8').replace(/import\s*\{[^}]*\}\s*from\s*'[^']+';/g,'');
 const prelude='const {hostExec,props,terminals,spaces,panes,focused,selectLocation,selectRequest,machineOf}=globalThis.panelHostTest;\n';
 const mod=await import('data:text/javascript;base64,'+Buffer.from(prelude+source).toString('base64'));
 const ctx={cwd:'/repo',on:'server'};
 await mod.exec('work',['observe',undefined,'--json'],ctx);
 assert.deepEqual(calls.pop(),['bollard-panel.py',['docker-status'],ctx]);
 await mod.exec('work',['docker','start','demo','--json'],ctx);
 assert.deepEqual(calls.pop(),['work',['docker','start','demo','--json'],ctx]);
 await mod.exec('repo-read',['--herdr-read','docs/a.md'],ctx);
 assert.deepEqual(calls.pop(),['bollard-panel.py',['read','docs/a.md'],ctx]);
 assert.equal(mod.workflowAvailable(),false);
 delete globalThis.panelHostTest;
});
