import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { parseFiles, fileChoices, browseRows, ancestors } from '../../desktop/shared/files.js';
import { requestOf, selectRequest } from '../../desktop/shared/routing-core.js';
import { selectLocation as pickerLocation, selectWorkflowContext } from '../../desktop/shared/stream-picker-routing.js';
import { addLane, removeLane, findNode, laneIds, withoutLaneState } from '../../desktop/shared/stream-tree.js';

// Real Git records: quoted/newline names, renames, deletes and untracked files.
test('file browser reads the actual no-renames porcelain contract', () => {
  const dir = mkdtempSync(join(tmpdir(), 'bollard-files-'));
  const git = (...args) => execFileSync('git', ['-C', dir, ...args], {
    encoding: 'utf8', env: {...process.env, GIT_CONFIG_GLOBAL:'/dev/null', GIT_CONFIG_NOSYSTEM:'1'},
  });
  try {
    git('init', '-q');
    mkdirSync(join(dir, 'docs'));
    const odd = 'docs/space "and\nnewline.md';
    writeFileSync(join(dir, odd), 'old\n');
    writeFileSync(join(dir, 'gone.txt'), 'gone\n');
    git('add', '.');
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'initial');
    writeFileSync(join(dir, odd), 'new\n');
    git('mv', 'gone.txt', 'renamed.txt');
    writeFileSync(join(dir, 'untracked.txt'), 'new\n');
    const snapshot = parseFiles(git('status','--porcelain=v1','-z','--no-renames','--untracked-files=all'), git('ls-files','-z'));
    assert.equal(snapshot.changed.length, 4);
    assert.equal(snapshot.changed.find(f => f.path === odd).label, 'Modified');
    assert.equal(snapshot.changed.find(f => f.path === 'gone.txt').deleted, true);
    assert.equal(snapshot.changed.find(f => f.path === 'renamed.txt').label, 'Added');
    assert.equal(snapshot.changed.find(f => f.path === 'untracked.txt').label, 'New');
  } finally { rmSync(dir, {recursive:true,force:true}); }
});

test('changed-first selection, conflicts, search and folder expansion agree', () => {
  const snapshot = parseFiles('UU docs/a.md\0?? src/new.ts\0', 'docs/a.md\0docs/quiet.txt\0src/new.ts\0');
  assert.equal(snapshot.changed[0].label, 'Conflict');
  assert.equal(snapshot.changed[0].deleted, false);
  assert.equal(fileChoices(snapshot, false).rows.length, 2);
  assert.equal(fileChoices(snapshot, true).rows.length, 3);
  assert.deepEqual(fileChoices(snapshot, true, 'DOCS QUIET').rows.map(f=>f.path), ['docs/quiet.txt']);
  assert.equal(fileChoices(parseFiles('', 'a\0b\0'), false).rows.length, 2);
  const files = fileChoices(snapshot, false).rows;
  assert.deepEqual(browseRows(files).map(r=>r.name), ['docs','src']);
  assert.deepEqual(browseRows(files, 'tree', new Set(ancestors('docs/a.md'))).map(r=>r.name), ['docs','a.md','src']);
  assert.equal(browseRows(files, 'tree', new Set(), 'a').filter(r=>r.kind==='file').length, 2);
  assert.deepEqual(ancestors('src/new.ts','type'), ['type:.ts']);
});

const terminal = (address, root, time=1, overrides={}) => ({address, cwd:root, labels:{
  'repo-tools.checkout':root, 'repo-tools.stream':root.split('/').pop(),
  'repo-read.request':JSON.stringify({v:1,id:'a'.repeat(24),root,path:'docs/brief.md',time,...overrides}),
}});
const spaces = [
  {id:'a',active:true,machine:'host-a',folder:'/repo/a',tabs:[{id:'ta',active:true}]},
  {id:'b',active:false,machine:'host-b',folder:'/repo/b',tabs:[{id:'tb',active:true}]},
];
const panes = [
  {pane:'pa',tab:'ta',terminal:'host-a/t1',cwd:'/repo/a'},
  {pane:'pb',tab:'tb',terminal:'host-b/t1',cwd:'/repo/b'},
];
const terminals = [terminal('host-a/t1','/repo/a'),terminal('host-b/t1','/repo/b',999)];

test('document routing rejects malformed or out-of-checkout requests', () => {
  for (const overrides of [{path:'../secret'}, {path:'/etc/passwd'}, {path:''}, {path:'x\0y'}, {root:'/different'}, {id:'invalid'}, {time:'now'}, {v:2}]) {
    assert.equal(requestOf(terminal('host-a/t1','/repo/a',1,overrides)), null);
  }
  assert.equal(requestOf(terminals[0]).path, 'docs/brief.md');
});

test('newer file request from another machine cannot steal the reader', () => {
  assert.equal(selectRequest(terminals, spaces, panes, {pane:'pa',terminal:'host-a/t1'}).address,'host-a/t1');
  assert.equal(selectRequest(terminals, [], panes, {}), null);
});

test('stream picker targets the clicked space, not the focused conversation', () => {
  const focus={pane:'pa',terminal:'host-a/t1'};
  assert.equal(pickerLocation(terminals,spaces,panes,focus).cwd,'/repo/a');
  const context=selectWorkflowContext(terminals,spaces,panes,focus,{space:'b'});
  assert.equal(context.on,'host-b');
  assert.equal(context.cwd,'/repo/b');
  assert.equal(context.stream,'b');
  assert.equal(selectWorkflowContext(terminals,spaces,panes,focus,{on:'host-b'}).cwd,'');
  assert.equal(selectWorkflowContext(terminals,spaces,panes,focus,{space:'missing'}).cwd,'');
});

const layout = () => JSON.parse(readFileSync(new URL('../../herdr/layouts/studio-work-portrait.json',import.meta.url)));
test('split and remove preserve other conversations and never mutate input', () => {
  const tree=layout();
  const ids=laneIds(tree);
  assert.equal(ids.length,2);
  const conversation=findNode(tree,ids[0]+'-conversation');
  conversation.content={terminal:'host-a/t99'};
  const original=structuredClone(tree);
  const next=addLane(tree,'extra',{axis:'row',target:ids[0]});
  assert.deepEqual(tree,original);
  assert.equal(findNode(next,ids[0]+'-conversation').content.terminal,'host-a/t99');
  assert.equal(findNode(next,'extra-conversation').content.props.kind,'empty');
  assert.equal(findNode(next,'extra-views').hidden,true);
  const removed=removeLane(next,'extra');
  assert.deepEqual(laneIds(removed),ids);
  assert.equal(findNode(removed,ids[0]+'-conversation').content.terminal,'host-a/t99');
  assert.equal(findNode(removed,'split-extra'),null);
  assert.throws(()=>addLane(tree,ids[0]));
  assert.throws(()=>addLane(tree,'extra',{target:'missing'}));
  assert.throws(()=>addLane(tree,'extra',{axis:'diagonal'}));
});

test('removing the last stream leaves an empty reusable slot', () => {
  const tree=layout(), ids=laneIds(tree);
  const one=removeLane(tree,ids[1]);
  findNode(one,ids[0]+'-conversation').content={terminal:'host-a/t99'};
  const empty=removeLane(one,ids[0]);
  assert.deepEqual(laneIds(empty),[ids[0]]);
  assert.equal(findNode(empty,ids[0]+'-conversation').content.props.kind,'empty');
  assert.equal(findNode(one,ids[0]+'-conversation').content.terminal,'host-a/t99');
});

test('closing a stale stream tolerates null siblings, deleted terminal content and repeated close', () => {
  const tree=layout(), ids=laneIds(tree);
  const root=findNode(tree,'portrait-streams');
  root.children.push(null);
  findNode(tree,ids[0]+'-conversation').content=null;
  findNode(tree,ids[1]+'-conversation').content={terminal:'host/t-kept'};
  const removed=removeLane(tree,ids[0]);
  assert.deepEqual(laneIds(removed),[ids[1]]);
  assert.equal(findNode(removed,ids[1]+'-conversation').content.terminal,'host/t-kept');
  assert.deepEqual(removeLane(removed,ids[0]),removed);
  assert.deepEqual(laneIds(null),[]);
  assert.throws(()=>removeLane(null,ids[0]),/Layout is unavailable/);
});

test('last stale stream resets even when optional panels have disappeared', () => {
  const tree=layout(), ids=laneIds(tree), one=removeLane(tree,ids[1]);
  const strip=n=>{if(n.children)n.children=n.children.filter(c=>c && c.id!==ids[0]+'-info' && c.id!==ids[0]+'-views').map(strip);return n;};
  strip(one);
  findNode(one,ids[0]+'-conversation').content=null;
  const reset=removeLane(one,ids[0]);
  assert.equal(findNode(reset,ids[0]+'-conversation').content.props.kind,'empty');
});


test('closing a view cleans only its state and resets embedded context in the last slot', () => {
  const state={top:{terminal:'gone'},bottom:{terminal:'keep'}};
  assert.deepEqual(withoutLaneState(state,'top'),{bottom:state.bottom});
  assert.equal(state.top.terminal,'gone');
  assert.deepEqual(withoutLaneState({'top:doc':true,'bottom:doc':true},'top',true),{'bottom:doc':true});
  const tree=layout(),ids=laneIds(tree),one=removeLane(tree,ids[1]);
  findNode(one,ids[0]+'-conversation').content={mod:'repo-portrait',props:{lane:ids[0],context:{cwd:'/deleted'}}};
  const reset=removeLane(one,ids[0]);
  assert.equal(findNode(reset,ids[0]+'-conversation').content.props.context,undefined);
});
