import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {laneIds,removeLane,withoutLaneState} from '../../desktop/shared/stream-tree.js';

function fixture(two=false) {
  let tree=JSON.parse(readFileSync(new URL('../../herdr/layouts/studio-work-portrait.json',import.meta.url)));
  const ids=laneIds(tree),id=ids[0];
  if(!two)tree=removeLane(tree,ids[1]);
  const store={'lanes':{[id]:{cwd:'/gone'}},'repo.open-requests':{old:{lane:id}}};
  const calls=[];
  const source=readFileSync(new URL('../../herdr/mods/repo-portrait/main.js',import.meta.url),'utf8');
  const method=source.slice(source.indexOf('  removeSlot('),source.indexOf('\n  close() {'));
  const make=new Function('shared','setShared','layout','run','props','closeOverlay','laneIds','removeLane','withoutLaneState',
    "const KEY='lanes',VIEWS='views',INFO='info'; return ({"+method+'});');
  const view=make(k=>store[k],(k,v)=>store[k]=v,()=>tree,(cmd,args)=>{
    calls.push(cmd);if(cmd==='layout.set')tree=args.layout;
  },()=>({overlay:'test'}),()=>calls.push('overlay.close'),laneIds,removeLane,withoutLaneState);
  return {view,id,store,calls,cx:{notify(){}}};
}
test('last stream asks before changing anything; explicit close targets only this window',()=>{
  const f=fixture();f.view.removeSlot(f.id,f.cx);
  assert.deepEqual(f.calls,[]);
  assert.equal(f.view.confirmLast.id,f.id);
  assert.ok(f.store.lanes[f.id]);
  f.view.removeSlot(f.id,f.cx,false,'close');
  assert.deepEqual(f.calls,['layout.set','overlay.close','app.quit']);
  assert.deepEqual(f.store.lanes,{});
  assert.deepEqual(f.store['repo.open-requests'],{});
});
test('keeping an empty window or removing a non-last stream never closes the app',()=>{
  for(const two of [false,true]) {
    const f=fixture(two);f.view.removeSlot(f.id,f.cx,false,'keep');
    assert.deepEqual(f.calls,['layout.set','overlay.close']);
  }
});
test('unsaved edits require discard before last-window confirmation',()=>{
  const f=fixture();f.store['repo.portrait.unsaved']={[f.id+':file']:true};
  f.view.removeSlot(f.id,f.cx);
  assert.equal(f.view.confirmRemove,f.id);assert.equal(f.view.confirmLast,undefined);
  f.view.removeSlot(f.id,f.cx,true);
  assert.equal(f.view.confirmLast.discard,true);assert.deepEqual(f.calls,[]);
});
