import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const src=readFileSync(new URL('../../herdr/mods/repo-portrait/tests.js',import.meta.url),'utf8');
const f=src.slice(src.indexOf('export function primaryAction'),src.indexOf('export default class'));
const {primaryAction}=await import('data:text/javascript;base64,'+Buffer.from(f).toString('base64'));
test('failures have one repair action, even stale or invalid config',()=>{
 for(const state of ['failed','stale','incomplete']){
  assert.equal(primaryAction({state,failure_prompt:'evidence',configured:false}).action,'fix');
  assert.equal(primaryAction({state,failure_prompt:'evidence'},false,false,false).action,'fix');
 }
 assert.equal(primaryAction({state:'running',failure_prompt:'evidence'}).disabled,true);
 assert.equal(primaryAction({configured:true,results:[{}]}).action,'run');
 assert.equal(primaryAction({configured:false}).action,'first');
 assert.ok(!src.includes("button('tests-send'"));
 assert.ok(!src.includes("button('tests-helper'"));
});

test('queued diagnosis is visible and prevents a second launch',()=>{
 for(const state of ['launching','investigating','waiting'])assert.equal(primaryAction({failure_prompt:'evidence',repair:{state}}).disabled,true);
});

test('repair progress is not a passing result or duplicate fix button',()=>{
 assert.equal(primaryAction({failure_prompt:'old',progress:{phase:'sent'}}).disabled,true);
 assert.equal(primaryAction({failure_prompt:'old',progress:{phase:'fixing',label:'Fixing',active:true}}).disabled,true);
 assert.equal(primaryAction({failure_prompt:'old',configured:true,progress:{phase:'awaiting-tests'}}).action,'run');
});
