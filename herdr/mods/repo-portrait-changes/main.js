import {reportPanel} from './signals.js';
import {browseRows,ancestors} from './files.js';
import {askHelper} from './helper.js';
import {button as control,toolColors} from './ui.js';
import { View, div } from "gpui-kit";
import { v_flex, h_flex, InputState, Input, Scrollbar, v_virtual_list } from "gpui-base";
import { spaces, panes, focused, exec, readTextFile, watchFolder, theme, settings } from "herdr";

import {scopedLocation} from './scope.js';
import {props,shared,setShared,run,notify,openOverlay} from 'herdr';
function location(){return scopedLocation()||{};}
const key = () => JSON.stringify(location());
// Reads write nothing under .git (no index refresh or lock, no fsmonitor cookie):
// the folder watch would see it, and every refresh would start the next one.
const READ = ["--no-optional-locks", "-c", "core.fsmonitor=false", "-c", "diff.autoRefreshIndex=false"];
const countLines = (text) => text ? text.split("\n").length - Number(text.endsWith("\n")) : 0;

// Numbers each diff line once, so a frame only draws the rows on screen.
function diffRows(lines) {
  let old = 0, next = 0;
  return lines.map((line) => {
    const match = /^@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(line);
    if (match) { old = +match[1]; next = +match[2]; return { kind: "@", text: line }; }
    const kind = line[0];
    if (kind === "-") return { kind, number: old++, text: line.slice(1) || " " };
    if (kind === "+") return { kind, number: next++, text: line.slice(1) || " " };
    if (kind === " ") { old++; return { kind, number: next++, text: line.slice(1) || " " }; }
    return { kind: "", text: line };
  });
}

export default class Changes extends View {
  init(_props, cx) {
    this.browseMode=localStorage.getItem('repo.browser.mode.changes')||'tree';this.expanded=new Set();
    this.showFiles=true;this.filter='';this.search=InputState.new({placeholder:'Find a changed file…'});
    this.search.on('change',(_e,cx)=>{this.filter=this.search.value();cx.notify();});
    this.files = []; this.rows = []; this.diffWidth = 0; this.message = ""; this.handle = cx.focus_handle();
    this.input = InputState.new({ placeholder: "Commit message" });
    this.input.on("change", (_e, cx) => {
      const hadMessage = Boolean(this.message.trim());
      this.message = this.input.value();
      if (hadMessage !== Boolean(this.message.trim())) cx.notify();
    });
    this.input.on("submit", (_e, cx) => this.commit(cx));
    this.input.on("focus", (_e, cx) => { this.typing = true; cx.notify(); });
    this.input.on("blur", (_e, cx) => { this.typing = false; cx.notify(); });
    this.refresh(cx);
    cx.timer.every(10000, (cx) => this.refresh(cx));
  }

  watch(root, cx) {
    if (this.on || this.watched === root) return;
    this.watched = root;
    cx.spawn(async (cx) => {
      try {
        while (this.watched === root) {
          await watchFolder(root);
          if (this.watched === root) this.refresh(cx);
        }
      } catch { this.watched = null; }
    });
  }

  refresh(cx) {
    if (this.loading || this.busy) return;
    const { cwd, on } = location(), context = key();
    if (context !== this.context) {
      try{this.expanded=new Set(JSON.parse(localStorage.getItem('repo.browser.folders.changes:'+context)||'[]'));}catch{this.expanded=new Set();}
      this.filter="";this.search.set_value("");
      this.context = context; this.root = null; this.files = []; this.open = null;
      this.setLines([]); this.message = ""; this.input.set_value(""); this.error = null; this.note = null; this.watched = null; this.closed = false; this.limited = false;
    }
    if (!cwd) return;
    this.loading = true;
    cx.spawn(async (cx) => {
      try {
        const top = await exec("git", ["rev-parse", "--show-toplevel"], { cwd, on });
        if (key() !== context) return;
        if (top.code !== 0) { this.root = null; this.files = []; this.setLines([]); this.open = null; this.error = "Not a git repository"; return; }
        const root = top.stdout.trim(), git = (args) => exec("git", [...READ, ...args], { cwd: root, on });
        const status = await git(["status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all"]);
        if (status.code !== 0) throw new Error(status.stderr);
        const head = await git(["rev-parse", "--verify", "HEAD"]);
        const stats = {};
        const results = head.code === 0 ? [await git(["diff", "HEAD", "--numstat", "-z", "--no-renames"])] : [await git(["diff", "--cached", "--numstat", "-z", "--no-renames"]), await git(["diff", "--numstat", "-z", "--no-renames"])];
        for (const result of results) {
          if (result.code !== 0) throw new Error(result.stderr);
          for (const entry of result.stdout.split("\0")) {
            const [a, d, ...parts] = entry.split("\t");
            if (!parts.length) continue;
            const path = parts.join("\t"), old = stats[path] ?? { add: 0, del: 0 };
            stats[path] = { add: old.add + (Number(a) || 0), del: old.del + (Number(d) || 0), binary: a === "-" };
          }
        }
        const files = [];
        const entries = status.stdout.split("\0").filter(Boolean);
        for (const entry of entries.slice(0, 1000)) {
          const xy = entry.slice(0, 2), path = entry.slice(3), fresh = xy === "??";
          const conflict = xy.includes("U") || xy === "AA" || xy === "DD";
          const s = conflict ? "U" : xy.includes("D") ? "D" : fresh || xy.includes("A") ? "A" : "M";
          const stat = stats[path] ?? { add: 0, del: 0 };
          files.push({ path, status: s, xy, fresh, ...stat });
        }
        if (key() !== context) return;
        this.root = root; this.on = on; this.hasHead = head.code === 0; this.files = files; this.limited = entries.length > 1000; this.error = null;
        this.watch(root, cx);
        if (this.open && !files.some((f) => f.path === this.open)) { this.open = null; this.setLines([]); }
        // The first file's diff shows until you pick another.
        if (!this.open && !this.closed && files.length) {
          this.open=files[0].path;for(const id of ancestors(this.open,this.browseMode))this.expanded.add(id);
        }
        if (this.open) {
          try { await this.load(this.open, context); }
          catch { if (key() === context) this.setLines(["Cannot preview this diff (too large or unreadable)"]); }
        }
      } catch (e) { if (key() === context) this.error = String(e); }
      finally { this.loading = false; cx.notify(); }
    });
  }

  async load(path, context) {
    const file = this.files.find((f) => f.path === path), root = this.root, on = this.on;
    if (!file) return;
    let lines;
    if (file.fresh || (!this.hasHead && file.status === "A")) {
      const preview=await exec('repo-read',['--herdr-read',path],{cwd:root,on});const text=preview.code?null:JSON.parse(preview.stdout).text;
      if (text === null) lines = ["Cannot preview this file (binary, too large, or unreadable)"];
      else if (text.includes("\0")) lines = ["Binary file · no text diff"];
      else {
        file.add = countLines(text);
        lines = [`@@ -0,0 +1,${file.add} @@`, ...text.slice(0, 400000).replace(/\n$/, "").split("\n").slice(0, 1500).map(l => `+${l}`)];
      }
    } else {
      const r = await exec("git", [...READ, "diff", ...(this.hasHead ? ["HEAD"] : []), "--no-ext-diff", "--no-textconv", "--no-color", "--", path], { cwd: root, on });
      if (r.code !== 0) throw new Error(r.stderr);
      const all = r.stdout.replace(/\n$/, "").split("\n"), first = all.findIndex((l) => l.startsWith("@@"));
      lines = first < 0 ? [file.binary ? "Binary file changed" : "No text diff available"] : all.slice(first);
    }
    if (key() === context && this.open === path) this.setLines(lines.slice(0, 1500).map(line => line.length > 4000 ? line.slice(0, 4000) + "… (line truncated)" : line));
  }

  setLines(lines) {
    this.rows = diffRows(lines);
    this.diffWidth = Math.max(300, ...lines.map(line => line.length * 7 + 50));
  }

  pick(path, cx) {
    if(this.context!==key()||!this.files.some(f=>f.path===path))return;
    this.open = this.open === path ? null : path; this.setLines([]); this.note = null;
    this.closed = !this.open;
    const context = this.context;
    if (this.open) cx.spawn(async (cx) => {
      try { await this.load(path, context); }
      catch (e) { if (key() === context && this.open === path) this.note = `Cannot preview this diff (too large or unreadable): ${e}`; }
      cx.notify();
    });
    cx.notify();
  }

  changeMode(mode,cx){
    this.browseMode=mode;localStorage.setItem('repo.browser.mode.changes',mode);
    for(const id of ancestors(this.open,mode))this.expanded.add(id);cx.notify();
  }
  toggleFolder(id,cx){
    if(this.expanded.has(id))this.expanded.delete(id);else this.expanded.add(id);
    localStorage.setItem('repo.browser.folders.changes:'+this.context,JSON.stringify([...this.expanded]));cx.notify();
  }
  fileRow(f,t){
    if(f.kind==='directory')return h_flex().id('change-'+f.id).h(28).flex_none().pl(8+f.depth*14).pr(8).gap(8).items_center().rounded(6)
      .cursor_pointer().hover(s=>s.bg(t.hover)).tooltip(f.path).accessibility_label(`${f.name}, ${f.count} changed files, ${f.open?'expanded':'collapsed'}`)
      .on_click((_e,cx)=>this.toggleFolder(f.id,cx))
      .child(div().w(14).text_color(t.muted).child(f.open?'▾':'▸'))
      .child(div().flex_1().min_w(0).truncate().font_semibold().child(f.name))
      .child(div().text_size(11).text_color(t.dim).child(String(f.count)));
    return h_flex().id('change-'+f.id).h(28).flex_none().pl(8+f.depth*14).pr(8).gap(8).items_center().rounded(6)
      .cursor_pointer().when(this.open===f.path,e=>e.bg(t.selected)).hover(s=>s.bg(t.hover)).tooltip(f.path)
      .on_click((_e,cx)=>this.pick(f.path,cx))
      .child(div().w(22).flex_none().text_size(11).text_color(f.status==='A'?t.ansi2:['D','U'].includes(f.status)?t.ansi1:t.blocked).child(f.xy))
      .child(div().flex_1().min_w(0).truncate().child(f.name))
      .when(f.add>0,e=>e.child(div().text_size(11).text_color(t.ansi2).child(`+${f.add}`)))
      .when(f.del>0,e=>e.child(div().text_size(11).text_color(t.ansi1).child(`−${f.del}`)));
  }

  commit(cx) {
    if (!this.message.trim() || !this.root || this.busy || this.loading || this.context !== key()) return;
    const root = this.root, on = this.on, context = this.context, message = this.message.trim();
    this.busy = true; this.note = null;
    cx.spawn(async (cx) => {
      try {
        for (const args of [["commit", "-m", message]]) {
          const r = await exec("git", args, { cwd: root, on });
          if (r.code !== 0) throw new Error((r.stderr || r.stdout).trim());
        }
        if (key() === context) { this.message = ""; this.input.set_value(""); }
      } catch (e) { if (key() === context) this.note = `Commit failed: ${e}`; }
      finally { this.busy = false; this.refresh(cx); cx.notify(); }
    });
    cx.notify();
  }

  stage(unstage,cx){if(!this.open||this.busy||this.loading||this.context!==key())return;const c=location(),path=this.open,context=key();this.busy=true;
    cx.spawn(async cx=>{try{const args=unstage?['restore','--staged','--',path]:['add','--',path];const r=await exec('git',args,{cwd:c.cwd,on:c.on});if(r.code)throw new Error(r.stderr||r.stdout);}catch(e){if(key()===context)this.note=String(e);}finally{this.busy=false;this.refresh(cx);cx.notify();}});
  }
  diffRow({ kind, number, text }, t) {
    if (kind === "@") return div().w_full().px(12).h(20).flex_none().truncate().bg(t.raised).text_color(t.dim).child(text);
    return h_flex().w_full().h(20).flex_none().gap(10).when(kind === "+", (e) => e.bg(t.ansi2 + "18")).when(kind === "-", (e) => e.bg(t.ansi1 + "18"))
      .child(div().w(30).flex_none().text_right().text_color(t.dim).child(number === undefined ? "" : String(number)))
      .child(div().flex_1().min_w(0).truncate().child(text));
  }

  render(cx) {
    if (key() !== this.context) this.refresh(cx);
    reportPanel('changes',location(),this.error||this.note);
    const t = theme(), add = this.files.reduce((n, f) => n + f.add, 0), del = this.files.reduce((n, f) => n + f.del, 0);
    const words=this.filter.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const filtered=this.files.filter(f=>words.every(w=>f.path.toLowerCase().includes(w)));
    const fileRows=browseRows(filtered,this.browseMode,this.expanded,this.filter);
    const enabled = Boolean(this.message.trim() && this.root && !this.busy && !this.loading);
    return v_flex().id("changes").size_full().p(4).min_h(0).rounded(10).overflow_hidden().bg(toolColors().background).border_1().border_color(t.border).text_color(t.foreground).text_size(13).track_focus(this.handle)
      .on_key_down((e, cx) => {
        if (e.key === "escape" && this.typing) { this.typing = false; this.handle.focus(); cx.stop_propagation(); cx.notify(); }
      })
      .child(h_flex().h(42).flex_none().px(14).gap(8).items_center().border_b(1).border_color(t.border)
        .child(div().font_semibold().child("Changes"))
        .child(div().text_size(11).text_color(t.muted).child(`${this.files.length} files`))
        .child(div().text_size(11).text_color(t.ansi2).child(`+${add}`)).child(div().text_size(11).text_color(t.ansi1).child(`−${del}`))
        .child(div().flex_1())
        .child(control('changes-main','Update from main',()=>openOverlay({mod:'repo-sync',kind:'dialog',width:780,height:690,props:{context:location(),source:'default'}}),{icon:'refresh'}))
        .child(control('changes-merge','Merge branch…',()=>openOverlay({mod:'repo-sync',kind:'dialog',width:780,height:690,props:{context:location()}}),{icon:'changes'}))
        .when(key()===this.context&&!!this.open&&this.rows.length>0,e=>e.child(control('changes-helper','Ask a helper',()=>askHelper(location(),{pane:'changes',source:this.open,text:this.rows.map(r=>(['+','-',' '].includes(r.kind)?r.kind:'')+r.text).join('\n'),truncated:this.rows.length>=1500}),{icon:'agents'})))
        .child(control('changes-list-toggle',this.showFiles?'Hide list':'File list',(_e,cx)=>{this.showFiles=!this.showFiles;cx.notify();},{icon:'folder'}))
        .child(control('changes-refresh','Refresh',(_e,cx)=>this.refresh(cx),{icon:'refresh',compact:true})))
      .child(h_flex().flex_none().p(10).gap(8).border_t(1).border_color(t.border)
        .child(div().id("commit-message").flex_1().min_w(0).h(32).px(10).flex().items_center().rounded(8).border_1().border_color(this.typing ? t.accent : t.border).cursor_text().on_mouse_down("left", (_e, cx) => cx.stop_propagation()).child(Input.new(this.input).h_full().text_size(12).text_color(t.foreground)))
        .child(div().id("commit").h(32).px(14).flex().items_center().rounded(8).bg(enabled ? t.solid : t.raised).text_color(enabled ? t.solid_foreground : t.dim).text_size(12).when(enabled, (e) => e.cursor_pointer()).on_click((_e, cx) => this.commit(cx)).child(this.busy ? "Committing…" : "Commit staged")))
      .child(h_flex().flex_1().min_h(0).min_w(0).items_stretch()
        .when(this.showFiles,e=>e.child(v_flex().w(245).min_w(140).flex_none().h_full().border_r(1).border_color(t.border)
          .child(h_flex().px(7).py(5).gap(1).items_center().flex_none()
            .child(div().flex_1().min_w(0).px(5).text_size(11).text_color(t.muted).truncate().child(`Changed · ${this.files.length}`))
            .children([['tree','Folders','tree'],['type','File types','types'],['list','List','list']].map(([id,label,icon])=>
              control('changes-mode-'+id,label,(_e,cx)=>this.changeMode(id,cx),{icon,compact:true,selected:this.browseMode===id})))
            .when(this.browseMode!=='list',e=>e.child(control('changes-collapse','Collapse folders',(_e,cx)=>{
              this.expanded.clear();localStorage.setItem('repo.browser.folders.changes:'+this.context,'[]');cx.notify();
            },{icon:'collapse',compact:true}))))
          .child(div().px(12).pb(6).flex_none().child(Input.new(this.search).h(30).px(8).rounded(6).border_1().border_color(t.input).bg(t.background).text_size(12)))
          .child(v_flex().id('changes-list').flex_1().min_h(0).overflow_y_scrollbar().px(3).py(5)
            .children(fileRows.map(f=>this.fileRow(f,t)))
            .when(!fileRows.length,e=>e.child(div().p(8).text_size(12).text_color(t.dim).child(this.error||(this.loading?'Loading changes…':this.filter?'No matching changes':this.root?'No uncommitted changes':'No folder')))))
          .when(this.limited,e=>e.child(div().px(12).py(4).text_size(11).text_color(t.dim).child('First 1,000 changed files')))))
        .child(v_flex().flex_1().min_w(0).min_h(0).h_full().bg(t.background)
          .child(h_flex().px(12).py(5).gap(6).items_center().flex_none().border_b(1).border_color(t.border)
            .child(div().flex_1().min_w(0).truncate().text_size(12).text_color(t.muted).tooltip(this.open||'Changes').child(this.open||'Select a file to view its changes'))
            .when(!!this.open,e=>e.child(control('stage-file','Stage file',(_e,cx)=>this.stage(false,cx),{icon:'changes'}))
              .child(control('unstage-file','Unstage file',(_e,cx)=>this.stage(true,cx),{icon:'changes'}))))
          .child(div().flex_1().min_h(0).min_w(0).relative().font_family(settings().font_family??'JetBrains Mono').text_size(11)
            .child(div().id('changes-diff-x').size_full().overflow_x_scrollbar()
              .child(div().w_full().min_w(this.diffWidth).h_full().child(v_virtual_list('changes-diff',this.rows.length,20,i=>String(i),
                range=>this.rows.slice(range.start,range.end).map(row=>this.diffRow(row,t))).size_full())))
            .child(Scrollbar.vertical('changes-diff').viewport_from_layout().absolute().inset_0())
            .when(!this.open,e=>e.child(div().absolute().top(12).px(16).text_color(t.dim).child(this.files.length?'Choose a file from the tree.':this.loading?'Loading changes…':'No uncommitted changes.'))))))
      .when(Boolean(this.note), (e) => e.child(div().px(10).pb(8).text_size(11).text_color(t.ansi1).child(this.note)))
;
  }
  close(){this.watched=null;this.input?.release();this.search?.release();}

}
