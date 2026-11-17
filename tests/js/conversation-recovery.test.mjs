import test from 'node:test';
import assert from 'node:assert/strict';
import {ensureConversation,findNode} from '../../desktop/shared/stream-tree.js';

test('recreates a removed conversation beside the preserved information pane',()=>{
 const info={id:'top-info',hidden:true};
 const tree={id:'top-body',children:[info]};
 const body=ensureConversation(tree,'top');
 assert.equal(tree.children[0],body);
 assert.equal(tree.children[1],info);
 body.content={terminal:'remote/new-terminal'};
 assert.equal(ensureConversation(tree,'top'),body);
 assert.equal(tree.children.length,2);
 assert.deepEqual(body.content,{terminal:'remote/new-terminal'});
 assert.equal(ensureConversation(tree,'removed-lane'),null);
});

test('recovered chat uses the surviving information pane weight scale',()=>{
 for(const weight of [.24,1,31]){
  const info={id:'top-info',size:{weight},max:430};
  const tree={id:'top-body',children:[info]};
  const body=ensureConversation(tree,'top');
  assert.equal(body.size.weight/info.size.weight,3);
  assert.equal(info.max,430);
  body.size.weight=weight*2;
  assert.equal(ensureConversation(tree,'top').size.weight,weight*2);
 }
});
