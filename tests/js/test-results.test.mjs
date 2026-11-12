import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../../herdr/mods/repo-portrait/test-results.js',import.meta.url),'utf8').replace(/import[^;]+;/g,'');
const {checkRows,countLabel}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('stale results preserve original failure without presenting it as a current failure',()=>{
 const s={state:'stale',checks:[{id:'check'},{id:'new'}],results:[{id:'check',exit_code:1,tail:'unknown flag'}]};
 const rows=checkRows(s);
 assert.equal(rows[0].state,'stale');assert.equal(rows[0].previousState,'failed');
 assert.equal(rows[0].result.tail,'unknown flag');assert.equal(rows[1].previousState,'not run');
 assert.equal(checkRows({...s,state:'failed'})[0].state,'failed');
});

test('success and unknown counts do not display a failure label',()=>{
 assert.equal(countLabel({passed:244,failed:0,skipped:0}),'244 passed');
 assert.equal(countLabel(null),'Count unavailable');
 assert.equal(countLabel({passed:8,failed:2}),'2 failed');
 assert.equal(countLabel({passed:8,failed:0,skipped:1}),'8 passed · 1 skipped');
});
