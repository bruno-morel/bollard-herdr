import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../../desktop/shared/terminal-display.js',import.meta.url),'utf8').replace(/^import .*\n/,'').replace('export function','function');
test('desktop launches carry the current window palette and preserve command arguments',()=>{
 for(const colors of [{foreground:'#202020',background:'#ffffff'},{foreground:'#eeeeee',background:'#181818'}]){
  const calls=[];
  const run=new Function('exec','theme',source+';return viewerExec;')((...args)=>calls.push(args),()=>colors);
  run('work',['flow','open','a-stream'],{on:'remote',cwd:'/repo with spaces'});
  const [cmd,args,options]=calls[0];assert.equal(cmd,'env');
  assert.deepEqual(JSON.parse(args[0].split('=').slice(1).join('=')),{fg:colors.foreground,bg:colors.background});
  assert.deepEqual(args.slice(1),['work','flow','open','a-stream']);
  assert.equal(options.on,'remote');assert.equal(options.cwd,'/repo with spaces');
 }
});
