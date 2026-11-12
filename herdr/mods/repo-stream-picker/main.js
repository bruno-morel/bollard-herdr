import {
  dropdown
} from './dropdown.js';
import {
  View,
  div,
  svg
} from 'gpui-kit';
import {
  v_flex,
  h_flex,
  Input,
  InputState,
  VirtualListScrollHandle
} from 'gpui-base';
import {
  props,
  theme,
  exec,
  terminals,
  spaces,
  panes,
  focused,
  machines,
  pickFolder,
  shared,
  setShared,
  notify,
  closeOverlay
} from 'herdr';
import {
  selectWorkflowContext
} from './routing.js';
import {
  showConversation,
  showInWindow,
  openExisting,
  watchOpen
} from './navigation.js';
import {
  machineOf,
  slug,
  running,
  sourceForTree,
  sourceForRef,
  pairedNames,
  defaultNames
} from './model.js';
export default class StreamPicker extends View {
  init(_p, cx) {
    this.dropdowns = {};
    for (const id of ['conversation', 'machine', 'repository', 'source', 'worktree', 'branch', 'agent', 'handoff-role']) this.dropdowns[id] = {
      open: false,
      at: 0,
      focus: cx.focus_handle(),
      list: cx.focus_handle(),
      scroll: VirtualListScrollHandle.new()
    };
    const p = props() || {},
      loc = p.context || selectWorkflowContext(terminals(), spaces(), panes(), focused(), p);
    this.handoff = p.handoff ? loc : null;
    this.on = loc?.on ?? p.on ?? null;
    this.role = p.role || loc?.role || 'studio';
    this.agent = 'codex';
    this.active = running(terminals()).find(r => machineOf(r.address) === this.on && (r.labels['repo-tools.checkout'] || r.cwd) === loc?.cwd && r.labels['repo-tools.role'] === this.role)?.address || running(terminals())[0]?.address || null;
    this.mode = p.fresh ? 'new' : this.active ? 'existing' : 'new';
    if (this.mode === 'new') this.active = null;
    this.advanced = false;
    this.activeNames = {};
    if (this.active && loc?.repo) this.activeNames[this.active] = loc.repo;
    this.data = null;
    this.repos = null;
    this.loading = false;
    this.busy = false;
    this.error = '';
    this.tab = 'new';
    this.selection = null;
    this.names = defaultNames();
    this.syncing = false;
    this.generation = 0;
    this.folder = InputState.new({
      value: loc?.cwd || '',
      placeholder: 'Repository path on ' + (this.on || 'this computer')
    });
    this.search = InputState.new({
      value: '',
      placeholder: 'Filter worktrees or branches'
    });
    this.stream = InputState.new({
      value: '',
      placeholder: 'e.g. waiting-list'
    });
    this.checkoutName = InputState.new({
      value: '',
      placeholder: 'Worktree folder name'
    });
    this.folder.on('change', (_e, cx) => {
      if (!this.syncing) {
        this.generation++;
        this.loading = false;
        this.data = null;
        this.selection = null;
        this.error = '';
      }
      cx.notify();
    });
    this.folder.on('submit', (_e, cx) => this.load(cx));
    this.search.on('change', (_e, cx) => cx.notify());
    for (const [field, input] of [
        ['stream', this.stream],
        ['folder', this.checkoutName]
      ]) input.on('change', (_e, cx) => {
      if (!this.syncing) {
        this.names = pairedNames(this.names, field, input.value());
        this.syncNames();
      }
      cx.notify();
    });
    this.loadActiveNames(cx);
    if (this.folder.value()) this.load(cx);
  }
  loadActiveNames(cx) {
    cx.spawn(async cx => {
      await Promise.allSettled(running(terminals()).map(async row => {
        const r = await exec('repo-streams.py', ['catalog', '--repo', row.labels['repo-tools.checkout'] || row.cwd], {
          on: machineOf(row.address)
        });
        if (!r.code) {
          this.activeNames[row.address] = JSON.parse(r.stdout).repo;
          cx.notify();
        }
      }));
    });
  }
  syncNames() {
    this.syncing = true;
    this.stream.set_value(this.names.stream);
    this.checkoutName.set_value(this.names.folder);
    this.syncing = false;
  }
  pick(selection, cx) {
    this.selection = selection;
    this.active = null;
    this.error = '';
    this.names = {
      ...defaultNames(),
      stream: selection.stream || '',
      folder: selection.folder || ''
    };
    this.syncNames();
    cx.notify();
  }
  load(cx, fetch = false) {
    if (this.busy || this.loading) return;
    const path = this.folder.value().trim();
    if (!path) {
      this.error = 'Choose a repository folder first.';
      cx.notify();
      return;
    }
    const token = ++this.generation,
      on = this.on;
    this.loading = true;
    this.error = '';
    cx.notify();
    cx.spawn(async cx => {
      try {
        const r = await exec('repo-streams.py', [fetch ? 'fetch' : 'catalog', '--repo', path], {
          on
        });
        if (token !== this.generation) return;
        if (r.code) throw Error(r.stderr || r.stdout);
        this.data = JSON.parse(r.stdout);
        this.syncing = true;
        this.folder.set_value(this.data.primary);
        this.syncing = false;
        this.discoverRepos(cx, token);
        if (this.tab === 'new' && !this.selection) {
          const active = this.active;
          this.pick({
            source: 'new',
            ref: this.data.default
          }, cx);
          this.active = active;
        } else if (this.selection?.source === 'tree' && !this.data.trees.some(t => t.path === this.selection.checkout)) this.selection = null;
      } catch (e) {
        if (token === this.generation) {
          this.data = null;
          this.error = String(e);
        }
      } finally {
        if (token === this.generation) {
          this.loading = false;
          cx.notify();
        }
      }
    });
  }
  candidates() {
    return [...new Set([...running(terminals()).filter(r => machineOf(r.address) === this.on).map(r => r.labels['repo-tools.checkout'] || r.cwd), ...spaces().filter(s => s.machine === this.on && s.folder && s.folder !== '~').map(s => s.folder)])].slice(0, 8);
  }
  discoverRepos(cx, token) {
    const on = this.on,
      current = this.data;
    this.repos = [{
      path: current.primary,
      name: current.repo
    }];
    cx.spawn(async cx => {
      const results = await Promise.allSettled(this.candidates().map(async path => {
        if (path === current.primary || path === current.root) return current;
        const r = await exec('repo-streams.py', ['catalog', '--repo', path], {
          on
        });
        if (r.code) return null;
        return JSON.parse(r.stdout);
      }));
      if (token !== this.generation) return;
      const unique = new Map([
        [current.primary, {
          path: current.primary,
          name: current.repo
        }]
      ]);
      for (const r of results)
        if (r.status === 'fulfilled' && r.value) unique.set(r.value.primary, {
          path: r.value.primary,
          name: r.value.repo
        });
      this.repos = [...unique.values()];
      cx.notify();
    });
  }
  chooseRepo(path, on, cx) {
    if (this.busy) return;
    this.generation++;
    this.loading = false;
    if (this.on !== on) this.repos = null;
    this.on = on;
    this.data = null;
    this.selection = null;
    this.active = null;
    this.folder.set_value(path);
    this.load(cx);
  }
  button(id, label, fn, {
    selected = false,
    strong = false,
    icon = null
  } = {}) {
    const t = theme();
    return h_flex().id(id).gap(6).px(10).py(7).rounded(7).items_center().text_size(12).bg(strong ? t.solid : selected ? t.selected : t.chrome).text_color(strong ? t.solid_foreground : selected ? t.foreground : t.muted).cursor_pointer().hover(x => x.opacity(.85)).on_click((_e, cx) => {
      cx.stop_propagation();
      if (!this.busy && !this.loading) fn(cx);
    }).when(!!icon, e => e.child(svg('mods/repo-portrait/icons/' + icon + '.svg').size(14))).child(label);
  }
  zone(title, icon, child) {
    const t = theme();
    return v_flex().flex_none().p(10).gap(8).rounded(10).border_1().border_color(t.border).bg(t.canvas).child(h_flex().gap(6).items_center().text_size(11).text_color(t.muted).child(svg('mods/repo-portrait/icons/' + icon + '.svg').size(14)).child(title)).child(child);
  }
  field(label, input) {
    const t = theme();
    return v_flex().gap(3).flex_1().min_w(0).child(div().text_size(11).text_color(t.muted).child(label)).child(Input.new(input).h(33).px(8).rounded(5).border_1().border_color(t.border).bg(t.background));
  }
  row(id, title, detail, selected, fn) {
    const t = theme();
    return v_flex().id(id).flex_none().px(10).py(6).gap(2).rounded(6).bg(selected ? t.selected : t.background).border_1().border_color(selected ? t.accent : t.border).cursor_pointer().hover(x => x.bg(t.hover)).on_click((_e, cx) => {
      cx.stop_propagation();
      if (!this.busy && !this.loading) fn(cx);
    }).child(div().text_size(12).font_semibold().truncate().child(title)).tooltip(detail).when(selected, e => e.child(div().text_size(10).text_color(t.muted).truncate().child(detail)));
  }
  async present(row, on, options) {
    if (props().newWindow) await showInWindow(row, on, props().lane, options);
    else showConversation(row, on, props().lane, options);
  }
  progress(message, cx) {
    this.progressText = message;
    this.startedAt = this.startedAt || Date.now();
    setShared('repo.operation-status', {
      ...(shared('repo.operation-status') || {}),
      [props().lane]: {
        active: true,
        message,
        stage: message,
        state: 'preparing'
      }
    });
    cx.notify();
  }
  submit(cx, retry = false) {
    if (this.busy || this.loading) return;
    this.busy = true;
    this.error = '';
    this.startedAt = Date.now();
    this.progress('Checking conversation…', cx);
    cx.notify();
    cx.spawn(async cx => {
      try {
        if (this.handoff) {
          const c = this.handoff;
          const r = await exec('repo-new-conversation.py', [c.stream, '--target', c.terminal.split('/').pop(), '--handoff-profile', this.role, '--confirm'], {cwd:c.cwd, on:c.on});
          if (r.code) throw Error(r.stderr || r.stdout);
          notify({title:'Role handoff', body:JSON.parse(r.stdout).message || 'Checkpoint started'});
          closeOverlay(props().overlay);
          return;
        }
        if (this.active) {
          const row = running(terminals()).find(t => t.address === this.active);
          if (!row) throw Error('That conversation has ended. Choose its worktree to reopen it.');
          const cwd = row.labels['repo-tools.checkout'] || row.cwd,
            on = machineOf(row.address);
          const r = await exec('repo-streams.py', ['catalog', '--repo', cwd], {
            on
          });
          if (r.code) throw Error(r.stderr || r.stdout);
          const data = JSON.parse(r.stdout);
          const stream = row.labels['repo-tools.stream'];
          if (data.current?.stream !== stream) throw Error('The agent’s checkout no longer matches its stream. Refresh before continuing.');
          await this.present(row, on, {
            placement: props().placement,
            repo: data.repo
          });
          closeOverlay(props().overlay);
          return;
        }
        if (!this.data || !this.selection) throw Error('Choose a worktree, branch, or new stream first.');
        const s = this.selection,
          stream = s.source === 'tree' || s.source === 'recover' ? s.stream : this.stream.value().trim(),
          folder = s.source === 'tree' ? stream : this.checkoutName.value().trim();
        if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(stream || '')) throw Error('Use lowercase words separated by hyphens for the stream.');
        if (s.source !== 'tree' && !s.ref) throw Error('Choose a base branch first. Detached checkouts cannot be resumed as a named stream.');
        const baseRole = this.data.roles?.[this.role]?.base || this.role;
        const options = {
          profile: this.role,
          placement: props().placement,
          repo: this.data.repo
        };
        // Reuse the selected role without changing its model or sending it another prompt.
        if (s.source !== 'new' && await openExisting(this.data.primary, stream, baseRole, this.on, props().lane, !!props().newWindow, options)) {
          closeOverlay(props().overlay);
          return;
        }
        const args = ['prepare', '--repo', this.data.primary, '--source', s.source, '--stream', stream, '--folder', folder || stream];
        if (s.ref) args.push('--ref', s.ref);
        if (s.checkout) args.push('--checkout', s.checkout);
        this.progress('Preparing worktree and handoff…', cx);
        if (retry) args.push('--retry');
        const prepared = await exec('repo-streams.py', args, {
          on: this.on
        });
        if (prepared.code) throw Error(prepared.stderr || prepared.stdout);
        const out = JSON.parse(prepared.stdout);
        this.progress('Starting agent / Docker setup…', cx);
        const r = await exec(baseRole, ['flow', 'open', stream, '--role', baseRole, '--agent', this.agent, '--profile', this.role], {
          cwd: out.cwd,
          on: this.on
        });
        if (r.code) throw Error((r.stderr || r.stdout) + ' The prepared checkout is preserved.');
        const job = JSON.parse(r.stdout.trim().split('\n').pop());
        watchOpen({
          terminal: job.terminal,
          stream,
          cwd: out.cwd,
          on: this.on,
          lane: props().lane,
          newWindow: !!props().newWindow,
          placement: props().placement,
          repo: out.repo
        });
        notify({
          title: 'Opening ' + out.repo + ' / ' + stream,
          body: props().newWindow ? 'The new window opens when the conversation is ready.' : 'The view opens when setup is ready. Follow the Workflow tab for progress.',
          level: 'success'
        });
        closeOverlay(props().overlay);
      } catch (e) {
        this.error = String(e);
        notify({
          title: 'Stream setup needs attention',
          body: this.error,
          level: 'warning'
        });
        setShared('repo.operation-status', {
          ...(shared('repo.operation-status') || {}),
          [props().lane]: {
            state: 'needs-you',
            error: true,
            message: this.error,
            stage: this.progressText
          }
        });
      } finally {
        this.busy = false;
        const op = (shared('repo.operation-status') || {})[props().lane];
        if (op) setShared('repo.operation-status', {
          ...(shared('repo.operation-status') || {}),
          [props().lane]: {
            ...op,
            active: false
          }
        });
        cx.notify();
      }
    });
  }
  render(cx) {
    const t = theme(),
      p = props() || {},
      all = running(terminals()),
      current = all.find(r => r.address === this.active),
      data = this.data;
    const caption = s => div().text_size(11).text_color(t.muted).child(s);
    const select = (id, title, value, options, fn) => dropdown(this, cx, id, title, value, options, fn);
    const option = (value, label, detail = '') => ({
      value,
      label,
      detail
    });
    if (this.handoff) {
      const sourceId = all.find(r => r.address === this.handoff.terminal)?.labels?.['repo-tools.profile'] || this.handoff.role;
      const suggested = data?.roles?.[sourceId]?.handoff_to || [];
      const choices = Object.entries(data?.roles || {}).filter(([id]) => id !== sourceId).sort(([a],[b]) => Number(suggested.includes(b))-Number(suggested.includes(a))).map(([id, r]) => option(id, r.label, r.description + ' · ' + r.base));
      if (!choices.some(r => r.value === this.role)) this.role = choices[0]?.value || '';
      return v_flex().p(18).gap(14).bg(t.background).text_color(t.foreground)
        .child(div().font_semibold().child('Hand off to…'))
        .child(caption('Save progress, commit and push this stream, then start the destination role. The current agent must be idle.'))
        .child(select('handoff-role', 'Destination role', this.role, choices, (id, cx) => {this.role=id;cx.notify();}))
        .when(!!this.error, e => e.child(div().text_color(t.danger || t.foreground).child(this.error)))
        .child(this.button('handoff-submit', this.busy ? 'Starting checkpoint…' : 'Save checkpoint & hand off', cx => this.submit(cx), {strong:true}));
    }
    let body = v_flex().id('stream-picker-scroll').flex_1().min_h(0).overflow_y_scrollbar().gap(12);
    const tabs = h_flex().gap(5).children([
      ['existing', 'Existing conversation', 'message'],
      ['new', 'New conversation', 'plus']
    ].map(([mode, label, icon]) =>
      this.button('mode-' + mode, label, cx => {
        this.mode = mode;
        this.active = mode === 'existing' ? (current?.address || all[0]?.address || null) : null;
        this.error = '';
        cx.notify();
      }, {
        selected: this.mode === mode,
        icon
      }).flex_1().justify_center()));
    if (this.mode === 'existing') {
      body = body.child(this.zone('CONTINUE WHERE YOU LEFT OFF', 'message', v_flex().gap(12)
        .child(select('conversation', 'Conversation', this.active, all.map(r => option(r.address, (this.activeNames[r.address] || r.cwd?.split('/').slice(-2, -1)[0]?.replace(/-worktrees$/, '') || '') + ' / ' + r.labels['repo-tools.stream'], r.labels['repo-tools.role'] + ' · ' + (machineOf(r.address) || 'This computer') + ' · ' + r.labels['repo-tools.agent'])), (value, cx) => {
          this.active = value;
          cx.notify();
        }))
        .when(!!current, e => e.child(caption(current.labels['repo-tools.role'].toUpperCase() + ' · ' + (machineOf(current.address) || 'This computer'))).child(caption(current.labels['repo-tools.checkout'] || current.cwd)))
        .child(caption(all.length ? 'Your existing role, model, prompt and conversation stay together.' : 'No active conversations. Use New conversation to open a worktree or start a stream.'))));
    } else {
      const roleOptions = data?.roles || {studio:{label:'Studio',base:'studio'},work:{label:'Work',base:'work'}};
      if (!roleOptions[this.role]) this.role = 'studio';
      let setup = v_flex().gap(12)
        .child(h_flex().gap(10).flex_wrap().children(Object.entries(roleOptions).map(([id, role]) =>
          div().id('role-card-'+id).flex_1().min_w(180).p(12).rounded(8).border_1()
            .border_color(this.role===id ? theme().solid : theme().border)
            .bg(this.role===id ? theme().selected : theme().surface).cursor_pointer()
            .accessibility_label(role.label || id)
            .on_click((_e,cx)=>{this.role=id;cx.notify();})
            .child(v_flex().gap(5)
              .child(div().text_size(15).font_semibold().child(id==='studio'?'Studio · Plan':id==='work'?'Work · Implement':role.label || id))
              .child(caption(role.description || (role.base==='work' || id==='work'?'Code, Docker, tests and review':'Research, docs and handoffs')))))));
      setup = setup.child(select('machine', 'Machine', this.on, machines().map(m => option(m.name, m.name || 'This computer')), (on, cx) => {
        if (this.on !== on) {
          const row = all.find(r => machineOf(r.address) === on);
          this.chooseRepo(row?.labels?.['repo-tools.checkout'] || '', on, cx);
        }
      }));
      const repos = this.repos || [];
      setup = setup.child(select('repository', 'Repository', data?.primary || null, [...repos.map(r => option(r.path, r.name, r.path)), option('@other', 'Choose another repository…')], (path, cx) => {
        if (path === '@other') {
          this.advanced = true;
          cx.notify();
        } else this.chooseRepo(path, this.on, cx);
      }));
      if (!data || this.advanced) setup = setup.child(h_flex().gap(6).items_end().child(this.field('Repository folder', this.folder))
        .when(!this.on, e => e.child(this.button('browse-folder', 'Browse', cx => {
          cx.spawn(async cx => {
            const folder = await pickFolder({
              prompt: 'Choose a Git repository'
            });
            if (folder) this.chooseRepo(folder, null, cx);
          });
        }, {
          icon: 'folder'
        })))
        .child(this.button('load-repo', this.loading ? 'Loading…' : 'Load', cx => this.load(cx), {
          icon: 'refresh'
        })));
      if (data) {
        setup = setup.child(select('source', 'Start from', this.tab, [option('new', 'New stream', 'Create from the default branch'), option('trees', 'Existing worktree', 'Open a checkout already on this machine'), option('refs', 'Existing branch', 'Recover a local or fetched remote stream')], (tab, cx) => {
          this.tab = tab;
          this.selection = null;
          if (tab === 'new') this.pick({
            source: 'new',
            ref: data.default
          }, cx);
          else cx.notify();
        }));
        if (this.tab === 'trees') setup = setup.child(select('worktree', 'Worktree', this.selection?.checkout, data.trees.filter(r => !r.primary).map(r => option(r.path, r.stream || r.branch || 'Detached checkout', r.available ? r.path : 'Unavailable · ' + r.path)), (path, cx) => {
          const r = data.trees.find(r => r.path === path);
          if (!r.available) {
            this.error = 'Restore this unavailable checkout first.';
            cx.notify();
            return;
          }
          this.pick(sourceForTree(r), cx);
        }));
        if (this.tab === 'refs' || this.tab === 'new') setup = setup.child(h_flex().items_end().gap(8)
          .child(select('branch', this.tab === 'new' ? 'Base branch' : 'Branch', this.selection?.ref, data.refs.map(r => option(r.ref, r.label, r.remote ? 'Last fetched remote reference' : 'Local branch')), (ref, cx) => {
            const r = data.refs.find(r => r.ref === ref);
            if (this.tab === 'refs') this.pick(sourceForRef(r), cx);
            else {
              this.selection = {
                ...this.selection,
                source: 'new',
                ref
              };
              cx.notify();
            }
          }))
          .child(this.button('fetch-refs', 'Fetch', cx => this.load(cx, true), {
            icon: 'refresh'
          }).tooltip('Refresh remote branches; checked-out files stay as they are')));
        const s = this.selection;
        if (s) {
          if (s.source === 'tree') setup = setup.child(caption('Resume ' + s.stream + ' · ' + s.checkout));
          else if (s.source === 'recover') setup = setup.child(h_flex().items_center().gap(8).child(caption('Resume ' + s.stream + ' · branch name preserved')).child(this.button('fork-branch', 'New from this branch', cx => {
            this.tab = 'new';
            this.pick({
              ...s,
              source: 'new',
              stream: '',
              folder: ''
            }, cx);
          })));
          else setup = setup.child(this.field('Stream name', this.stream));
          if (s.source !== 'tree') setup = setup.child(caption('codex/' + (s.source === 'recover' ? s.stream : this.stream.value() || '…') + ' · ' + data.worktree_parent + '/' + (this.checkoutName.value() || '…')));
          setup = setup.child(this.button('advanced', this.advanced ? 'Less customization ▴' : 'Customize agent or folder ▾', cx => {
            this.advanced = !this.advanced;
            cx.notify();
          }));
          if (this.advanced) {
            setup = setup.child(select('agent', 'Agent', this.agent, ['codex', 'claude', 'cursor'].map(a => option(a, a)), (value, cx) => {
              this.agent = value;
              cx.notify();
            }));
            if (s.source !== 'tree') setup = setup.child(this.field('Worktree folder', this.checkoutName));
          }
        }
      }
      body = body.child(this.zone('OPEN OR CREATE', 'folder', setup));
    }
    return v_flex().w_full().h(this.mode === 'existing' ? 375 : this.advanced ? 700 : 610).p(18).gap(12).bg(t.surface).text_color(t.foreground)
      .child(div().text_size(19).font_semibold().child(p.newWindow ? 'Open in a new window' : 'Choose a conversation'))
      .child(tabs).child(body)
      .when(!!this.error, e => e.child(div().text_size(12).text_color(t.blocked).child(this.error)).child(this.button('retry-setup', 'Retry unfinished setup', cx => this.submit(cx, true), {
        strong: true,
        icon: 'refresh'
      })))
      .child(h_flex().gap(8).items_center().child(caption(this.busy ? (this.progressText || 'Preparing…') : this.mode === 'existing' ? 'Attach to the same conversation.' : this.role === 'work' ? 'Handoff, prompt and Docker setup included.' : 'Repository docs and handoff rules included.')).child(div().flex_1())
        .child(this.button('picker-cancel', 'Cancel', () => closeOverlay(p.overlay)))
        .when(!this.busy && (this.mode === 'existing' ? !!current : !!this.selection), e => e.child(this.button('picker-open', this.mode === 'existing' ? 'Open conversation' : this.selection?.source === 'new' ? 'Create stream' : 'Open stream', cx => this.submit(cx), {
          strong: true,
          icon: p.newWindow ? 'external' : 'play'
        }))));
  }

  close() {
    for (const d of Object.values(this.dropdowns || {})) d.scroll.release();
    for (const i of [this.folder, this.search, this.stream, this.checkoutName]) i?.release();
  }
}
