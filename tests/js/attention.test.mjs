import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const src=readFileSync(new URL('../../herdr/mods/repo-portrait/attention.js',import.meta.url),'utf8').replace(/import[^;]+;/g,'');
const {attentionRows}=await import('data:text/javascript;base64,'+Buffer.from(src).toString('base64'));
const row=(address,status,extra={})=>({address,status,state:'live',...extra});
test('global attention excludes idle, working, seen and exited agents',()=>{
 const rows=[row('a/t1','blocked'),row('b/t1','done',{turn:3}),row('a/t2','idle'),row('a/t3','working'),row('a/t4','done',{turn:4,labels:{'herdr.seen':'4'}}),row('a/t5','blocked',{state:'exited'})];
 assert.deepEqual(attentionRows(rows).map(x=>x.address),['a/t1','b/t1']);
});
test('duplicates across windows count once; helpers preserve parent and host',()=>{
 const child=row('box/t2','blocked',{parent:'box/t1',labels:{'repo-tools.role':'helper','repo-tools.stream':'demo','repo-tools.checkout':'/repo'}});
 const results=attentionRows([child,child]);assert.equal(results.length,1);
 assert.deepEqual(results[0].context,{terminal:'box/t2',parent:'box/t1',on:'box',cwd:'/repo',stream:'demo',role:'helper'});
});

test('missing window reports a message instead of opening a preview',async()=>{
 const messages=[];
 const source=src.replace("export async function focusAttention(row)","export async function focusAttention(row)");
 globalThis.__attentionMessages=messages;
 const prefix="const exec=async()=>({code:0,stdout:JSON.stringify({found:false})});const appHome=()=>'/app';const notify=x=>globalThis.__attentionMessages.push(x);";
 const mod=await import('data:text/javascript;base64,'+Buffer.from(prefix+source).toString('base64'));
 await mod.focusAttention({address:'box/t1',context:{terminal:'box/t1'}});
 assert.equal(messages[0].title,'No open window for this agent');
 delete globalThis.__attentionMessages;
});

test('multi-agent selection queues the exact target before closing its own menu',async()=>{
 const calls=[];globalThis.__attentionCalls=calls;
 const prefix="const run=(...args)=>globalThis.__attentionCalls.push(['run',...args]);const closeOverlay=id=>globalThis.__attentionCalls.push(['close',id]);";
 const mod=await import('data:text/javascript;base64,'+Buffer.from(prefix+src).toString('base64'));
 const rows=[row('box/t1','blocked'),row('box/t2','blocked')];
 const selected=mod.attentionRows(rows)[1];
 mod.requestAttention(selected,'attention-popup');
 assert.equal(calls[0][0],'run');
 const payload=JSON.parse(decodeURIComponent(calls[0][1].split('attention-open:')[1]));
 assert.equal(payload.context.terminal,'box/t2');
 assert.deepEqual(calls[1],['close','attention-popup']);
 calls.length=0;mod.requestAttention(selected);
 assert.equal(calls.length,1);
 delete globalThis.__attentionCalls;
});
