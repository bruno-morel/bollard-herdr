import test from 'node:test';
import assert from 'node:assert/strict';
import {activity} from '../../desktop/shared/activity.js';
test('permission status is explicit and task duration is not invented',()=>{
 const r={state:'live',created_ms:1,status_ms:60000,status:{state:'blocked',kind:'permission'}};
 assert.equal(activity(r,120000).kind,'Permission needed');
 assert.equal(activity(r,120000).timing,'Last status 1m ago');
 assert.equal(activity({...r,status_ms:null},120000).timing,'Status time unavailable');
 assert.equal(activity({...r,status_ms:999999},120000).timing,'Status time unavailable');
});
test('stale reports do not claim a loop or disconnect; errors remain explicit',()=>{
 const r={state:'live',status_ms:1,status:{state:'working'}};
 assert.equal(activity(r,99999999).health,'Status available');
 assert.equal(activity(r,99999999,'Connection failed').health,'Status unavailable');
 assert.equal(activity({...r,state:'finished'}).health,'Conversation ended');
 assert.equal(activity(null).health,'No conversation');
});
