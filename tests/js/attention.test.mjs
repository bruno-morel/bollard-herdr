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
