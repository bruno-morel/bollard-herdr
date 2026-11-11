// Uses Herdr's native Markdown and source viewers; no terminal replaces the conversation.
import { View, div } from 'gpui-kit';
import { v_flex, h_flex, TextView, Editor, EditorState, Input, InputState, v_virtual_list, Scrollbar, VirtualListScrollHandle } from 'gpui-base';
import { terminals, spaces, panes, focused, exec, hc, theme, settings, nextCommand } from 'herdr';
import { selectRequest, selectLocation, machineOf } from './routing.js';
import { parseFiles, fileChoices } from './files.js';
const LANG = { ts: 'js', tsx: 'js', jsx: 'js', mjs: 'js', toml: 'yaml', yml: 'yaml', py: 'python', sh: 'bash', zsh: 'bash' };
const location = () => selectLocation(terminals(), spaces(), panes(), focused());
const requested = () => selectRequest(terminals(), spaces(), panes(), focused());
const GIT = ['--no-optional-locks', '-c', 'core.fsmonitor=false'];

export default class RepoReader extends View {
  init(_props, cx) {
    this.context = null; this.saved = new Map(); this.seen = new Set(); this.generation = 0;
    this.path = null; this.text = null; this.code = null; this.source = false;
    this.files = { all: [], changed: [] }; this.showFiles = true; this.forceAll = false; this.filter = '';
    this.input = InputState.new({ placeholder: 'Find a file…' });
    this.scroll = VirtualListScrollHandle.new();
    this.input.on('change', (_e,cx) => { this.filter = this.input.value(); this.scroll.scroll_to_item(0); cx.notify(); });
    this.input.on('submit', (_e,cx) => { const row = this.choices().rows.find(f => !f.deleted); if (row) this.pick(row.path,cx); });
    cx.timer.every(10000, cx => this.refreshFiles(cx));
    // Also available to Herdr's command palette/key bindings; never sends agent keystrokes.
    cx.spawn(async cx => { for (;;) {
      const command = await nextCommand();
      if (command === 'files') this.showFiles = !this.showFiles;
      if (command === 'all') { this.forceAll = !this.forceAll; this.scroll.scroll_to_item(0); }
      if (command === 'refresh') { this.refreshFiles(cx); if (this.path) this.load(this.path,cx); }
      if (command === 'source') this.source = !this.source;
      if (command.startsWith('open:')) this.pick(command.slice(5),cx);
      cx.notify();
    } });
  }
  current(context) { return this.context === context && location()?.key === context.key; }
  sync(cx) {
    const next = location();
    if ((next?.key ?? null) === (this.context?.key ?? null)) return;
    if (this.context) this.saved.set(this.context.key, this.path);
    this.context = next ? { ...next, root: null } : null;
    this.path = null; this.text = null; this.error = null; this.listError = null;
    this.files = { all: [], changed: [] }; this.forceAll = false; this.filter = '';
    this.code?.release(); this.code = null; ++this.generation;
    if (this.context) this.refreshFiles(cx);
  }
  async git(args, context) {
    const r = await exec('git', [...GIT, ...args], { cwd: context.root || context.cwd, on: context.on });
    if (r.code) throw new Error(r.stderr.trim() || 'Cannot read repository files');
    return r.stdout;
  }
  refreshFiles(cx) {
    const context = this.context;
    if (!context || !this.current(context) || context.loading) return;
    context.loading = true;
    cx.spawn(async cx => {
      try {
        if (!context.root) {
          const root = (await this.git(['rev-parse','--show-toplevel'],context)).replace(/\n$/, '');
          if (!this.current(context)) return;
          context.root = root; this.input.set_value('');
        }
        const status = await this.git(['status','--porcelain=v1','-z','--no-renames','--untracked-files=all'],context);
        const tracked = await this.git(['ls-files','--cached','--others','--exclude-standard','-z'],context);
        if (!this.current(context)) return;
        this.files = parseFiles(status,tracked); this.listError = null;
        if (!this.path && this.saved.get(context.key)) this.load(this.saved.get(context.key),cx);
      } catch (e) { if (this.current(context)) this.listError = String(e); }
      finally { context.loading = false; cx.notify(); }
    });
  }
  choices() { return fileChoices(this.files,this.forceAll,this.filter); }
  pick(path,cx) {
    const entry = this.choices().rows.find(f => f.path === path);
    if (!entry || entry.deleted) return;
    this.load(path,cx); cx.notify();
  }
  async acknowledge(request, status, message = '') {
    if (!request) return;
    try { await hc(['label',request.address,'repo-read.result='+JSON.stringify({id:request.id,status,message})]); }
    catch { /* Display remains usable if an acknowledgement cannot reach the core. */ }
  }
  load(path,cx,request=null) {
    const context = this.context;
    if (!context?.root) return;
    this.path = path; this.text = null; this.error = null; this.source = false;
    this.code?.release(); this.code = null;
    const generation = ++this.generation;
    cx.spawn(async cx => {
      try {
        // Shared remote checks prevent symlink escapes, binary reads, and oversized previews.
        const result = await exec('repo-read',['--herdr-read',path],{cwd:context.root,on:context.on});
        if (!this.current(context) || generation !== this.generation) return;
        if (result.code) throw new Error(result.stderr.trim() || 'Cannot read this file');
        const document = JSON.parse(result.stdout);
        if (document.root !== context.root || document.path !== path || typeof document.text !== 'string') throw new Error('File identity changed; select it again.');
        this.text = document.text; this.markdown = /\.(md|markdown|mdown|mkd)$/i.test(path);
        const t=theme(), ext=path.split('.').pop().toLowerCase();
        this.code=EditorState.new({language:LANG[ext]??ext,readonly:true,value:this.text,font_family:settings().font_family,font_size:13,
          syntax:{keyword:t.ansi5,string:t.ansi2,comment:t.dim,function:t.ansi4,type:t.ansi3,number:t.ansi1,constant:t.ansi6}});
        this.saved.set(context.key,path); cx.notify();
        await this.acknowledge(request,'shown');
      } catch (e) {
        if (!this.current(context) || generation !== this.generation) return;
        this.error=String(e); this.text=null; cx.notify();
        await this.acknowledge(request,'error',this.error.slice(0,300));
      }
    });
  }
  button(id,label,action) {
    const t=theme(); return div().id(id).px(8).py(5).rounded(5).cursor_pointer().text_size(12).text_color(t.muted)
      .hover(s=>s.bg(t.hover)).on_click(action).child(label);
  }
  browser(t) {
    const {rows,total,modified}=this.choices();
    return v_flex().flex_none().border_b(1).border_color(t.border)
      .child(h_flex().px(12).py(5).items_center()
        .child(div().flex_1().text_size(12).text_color(t.muted).child(`${modified?'Modified':'All files'} · ${total}`))
        .when(this.files.changed.length>0,el=>el.child(this.button('read-all',this.forceAll?'Modified only':'All files',(_e,cx)=>{this.forceAll=!this.forceAll;this.scroll.scroll_to_item(0);cx.notify();}))))
      .child(div().px(12).pb(6).child(Input.new(this.input).h(30).px(8).rounded(6).border_1().border_color(t.input).bg(t.background).text_size(12)))
      .child(v_flex().relative().h(Math.min(224,Math.max(36,rows.length*28)))
        .when(rows.length>0,el=>el.child(v_virtual_list('read-files',rows.length,28,i=>rows[i].path,
          range=>rows.slice(range.start,range.end).map(row=>h_flex().h(28).px(12).gap(8).items_center().min_w(0)
            .when(row.path===this.path,el=>el.bg(t.selected)).when(!row.deleted,el=>el.cursor_pointer())
            .child(div().flex_1().min_w(0).truncate().text_size(12).text_color(row.deleted?t.dim:t.foreground).child(row.path))
            .child(div().flex_none().text_size(10).text_color(t.dim).child(row.label))))
          .track_scroll(this.scroll).size_full().on_item_click((path,cx)=>this.pick(path,cx)))
          .child(Scrollbar.vertical('read-files').absolute().inset_0()))
        .when(!rows.length,el=>el.child(div().p(12).text_size(12).text_color(t.dim).child(this.listError||
          (this.context?.loading?'Loading files…':this.filter?'No matching files':this.context?'No files':'Select a repository stream')))))
      .when(Boolean(this.listError)&&rows.length>0,el=>el.child(div().px(12).py(5).text_size(12).text_color(t.blocked).child(this.listError)));
  }
  render(cx) {
    this.sync(cx);
    const request=requested();
    if (request && this.context?.root===request.root && this.context?.on===machineOf(request.address) && !this.seen.has(request.key)) {
      this.seen.add(request.key); this.load(request.path,cx,request);
    }
    const t=theme();
    let panel=v_flex().id('repo-reader').size_full().min_h(0).min_w(0).rounded(10).overflow_hidden().bg(t.background)
      .border_1().border_color(t.border).text_color(t.foreground).text_size(14)
      .child(h_flex().h(42).flex_none().px(12).gap(4).items_center().border_b(1).border_color(t.border)
        .child(div().font_semibold().flex_1().child('READ'))
        .child(this.button('read-files-toggle',this.showFiles?'Hide files':'Files',(_e,cx)=>{this.showFiles=!this.showFiles;cx.notify();}))
        .when(this.text!==null&&this.markdown,el=>el.child(this.button('read-mode',this.source?'Preview':'Source',(_e,cx)=>{this.source=!this.source;cx.notify();})))
        .child(this.button('read-refresh','Refresh',(_e,cx)=>{this.refreshFiles(cx);if(this.path)this.load(this.path,cx);cx.notify();})))
      .when(this.showFiles,el=>el.child(this.browser(t)))
      .when(Boolean(this.path),el=>el.child(v_flex().flex_none().px(14).py(8).gap(3).border_b(1).border_color(t.border)
        .child(div().text_size(11).text_color(t.dim).truncate().child(`${this.context?.root?.split('/').pop()??''} · ${this.context?.on??'This computer'}`))
        .child(div().text_size(13).truncate().child(this.path))));
    if (!this.path) return panel.child(div().p(18).text_color(t.dim).child('Choose a file above, or ask the agent to show one.'));
    if (this.text===null) return panel.child(div().p(18).text_color(this.error?t.blocked:t.dim).child(this.error||'Opening file…'));
    if (this.markdown&&!this.source) return panel.child(TextView.markdown(`read-${this.generation}`,this.text).selectable(true).scrollable(true).flex_1().min_h(0).p(18));
    return panel.child(Editor.new(this.code).flex_1().min_h(0));
  }
  async close() { this.code?.release(); this.input.release(); this.scroll.release(); }
}
