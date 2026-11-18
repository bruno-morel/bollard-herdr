import test from 'node:test';
import assert from 'node:assert/strict';
import {bindQuestion,findNode,renameLane} from '../../desktop/shared/stream-tree.js';
const tree=()=>({id:'top-lane',children:[{id:'top-conversation',content:{terminal:'box/lead'}},{id:'top-questions',type:'block',content:{mod:'repo-portrait',props:{kind:'questions',lane:'top'}}}]});
test('answering a child embeds its terminal without replacing the lead',()=>{
 const layout=tree();assert.equal(bindQuestion(layout,'top','box/child'),true);
 assert.equal(findNode(layout,'top-conversation').content.terminal,'box/lead');
 assert.equal(findNode(layout,'top-questions').content.terminal,'box/child');
 assert.equal(findNode(layout,'top-questions').children,undefined); // no extra layout nesting
 assert.equal(bindQuestion(layout,'top','box/child'),false);
 assert.equal(bindQuestion(layout,'top','box/other'),true);
 assert.equal(findNode(layout,'top-questions').content.terminal,'box/other');
});
test('closed child returns to the questions list and moving preserves the child',()=>{
 const layout=tree();bindQuestion(layout,'top','box/child');
 const moved=renameLane(layout,'top','new');
 assert.equal(findNode(moved,'new-questions').content.terminal,'box/child');
 assert.equal(findNode(moved,'new-questions').children,undefined);
 assert.equal(bindQuestion(layout,'top',null),true);
 assert.equal(findNode(layout,'top-questions').content.props.kind,'questions');
 assert.equal(findNode(layout,'top-conversation').content.terminal,'box/lead');
 assert.equal(bindQuestion(layout,'top',null),false);
 assert.equal(bindQuestion(layout,'absent','box/child'),false);
});
