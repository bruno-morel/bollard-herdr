import test from 'node:test';
import assert from 'node:assert/strict';
import {moveLane,placeLane,renameLane,findNode,laneIds} from '../../desktop/shared/stream-tree.js';
const lane=id=>({id:id+'-lane',size:{weight:2},children:[{id:id+'-header',content:{mod:'repo-portrait',props:{kind:'header',lane:id}}},{id:id+'-conversation',content:{terminal:'box/'+id}},{id:id+'-views',active:id+'-read',hidden:false,children:[{id:id+'-read',content:{props:{lane:id}}}]}]});
const tree=()=>({id:'portrait-streams',type:'column',children:[lane('one'),lane('two'),lane('three')]});
test('moves preserve terminal and tool selection in every direction',()=>{
 for(const position of ['above','below','left','right']){
  const original=tree(),result=moveLane(original,'one',{target:'three',position});
  assert.deepEqual(laneIds(result).sort(),['one','three','two']);
  assert.equal(findNode(result,'one-conversation').content.terminal,'box/one');
  assert.equal(findNode(result,'one-views').active,'one-read');
  const split=findNode(result,'split-one-lane');
  assert.equal(split.type,['left','right'].includes(position)?'row':'column');
  assert.equal(split.children[0].id,['above','left'].includes(position)?'one-lane':'three-lane');
  assert.deepEqual(original,tree());
 }
});
test('nested moves retain all streams and reject stale destinations',()=>{
 const first=moveLane(tree(),'one',{target:'three',position:'left'});
 const second=moveLane(first,'three',{target:'two',position:'above'});
 assert.equal(laneIds(second).length,3);
 assert.throws(()=>moveLane(second,'one',{target:'one'}));
 assert.throws(()=>moveLane(second,'one',{target:'gone'}));
 assert.throws(()=>placeLane(second,lane('one'),{target:'two'}));
});
test('cross-window import renames view references without changing terminal identity',()=>{
 const source=lane('one'),imported=renameLane(source,'one','moved-123');
 const result=placeLane(tree(),imported,{target:'two',position:'right'});
 assert.equal(findNode(result,'moved-123-conversation').content.terminal,'box/one');
 assert.equal(findNode(result,'moved-123-views').active,'moved-123-read');
 assert.equal(findNode(result,'moved-123-read').content.props.lane,'moved-123');
 assert.equal(source.id,'one-lane');
});
