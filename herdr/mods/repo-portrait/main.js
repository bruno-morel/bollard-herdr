import {
  operation,
  stepText,
  progressText,
  currentOperation,
  requestCheckpoint,
  refreshStatuses
} from './operations.js';
import {
  showAccount
} from './account-pane.js';
import Account from './account.js';
import {
  addLane,
  removeLane,
  withoutLaneState,
  laneIds,
  findNode,
  ensureConversation
} from './stream-tree.js';
import {
  COMPLETE,
  agentState,
  interactionTone,
  panelFailed
} from './signals.js';
import {
  View,
  div
} from 'gpui-kit';
import {
  v_flex,
  h_flex,
  Input,
  InputState
} from 'gpui-base';
import {
  props,
  shared,
  setShared,
  spaces,
  panes,
  terminals,
  focused,
  layout,
  run,
  theme,
  openOverlay,
  closeOverlay,
  exec,
  notify,
  nextCommand,
  appHome
} from 'herdr';
import {
  KEY,
  VIEWS,
  laneConfig,
  leadFor,
  matching,
  machineOf,
  scopedRequest
} from './scope.js';
import {
  followOpens,
  openExisting,
  retryOpen
} from './navigation.js';
import Docker from './docker.js';
import Tests from './tests.js';
import Info, {
  Questions,
  relatives
} from './info.js';
import {
  button as control,
  INFO,
  info
} from './ui.js';

function find(n, id) {
  if (n?.id === id) return n;
  for (const c of n?.children || []) {
    const x = find(c, id);
    if (x) return x;
  }
  return null;
}

function picker(lane, extra = {}) {
  const context = laneConfig(lane) || Object.values(shared(KEY) || {}).find(Boolean);
  return openOverlay({
    mod: 'repo-stream-picker',
    kind: 'dialog',
    width: 720,
    props: {
      lane,
      context,
      ...extra
    }
  });
}

function dialog(lane, action, role) {
  const c = laneConfig(lane);
  if (!c) return;
  if (action === 'open') return picker(lane, {
    role: role || c.role
  });
  openOverlay({
    mod: 'repo-workflow',
    kind: 'dialog',
    width: 610,
    height: 590,
    props: {
      dialog: true,
      action,
      role: role || c.role,
      context: c,
      lane
    }
  });
}

function view(lane, name) {
  if (['read', 'files', 'changes'].includes(name)) setShared('repo.portrait.browser', {
    ...(shared('repo.portrait.browser') || {}),
    [lane]: name
  });
  setShared(VIEWS, {
    ...(shared(VIEWS) || {}),
    [lane]: name
  });
  if (!find(layout(), lane + '-views')) return;
  run(name ? 'layout.show' : 'layout.hide', {
    id: lane + '-views'
  });
  if (name) run('layout.select', {
    stack: lane + '-views',
    child: lane + '-' + name
  });
}
async function focusConversation(lane) {
  view(lane, null);
  const c = laneConfig(lane);
  if (!c) return;
  const lead = leadFor(terminals(), c);
  if (lead) {
    const done = {
      ...(shared(COMPLETE) || {})
    };
    delete done[lead.address];
    setShared(COMPLETE, done);
    run('pane.focus', {
      terminal: lead.address
    });
  } else try {
    await openExisting(c.cwd, c.stream, c.role, c.on, lane);
  }
  catch (e) {
    notify({
      title: 'Cannot open conversation',
      body: String(e),
      level: 'warning'
    });
  }
}
export default class Portrait extends View {
  init(_p, cx) {
    this.kind = props()?.kind || 'header';
    this.busy = false;
    this.error = '';
    this.seen = new Set();
    this.polling = false;
    this.agentStates = {};
    this.splitAxis = null;
    this.separateWindow = false;
    const panel = {
      docker: Docker,
      tests: Tests,
      info: Info,
      questions: Questions,
      'account-header': Account
    } [this.kind];
    if (panel) {
      this.panel = new panel();
      this.panel.init?.(_p, cx);
      return;
    }
    if (this.kind === 'manager') {
      if (shared('repo.portrait.debug')) setShared('repo.portrait.debug', null);
      if (shared('repo.portrait.inspect')) setShared('repo.portrait.inspect', null);
      cx.spawn(async cx => {
        for (;;) {
          const cmd = await nextCommand();
          const accountCommand = /^show-account-(claude|cursor)$/.exec(cmd);
          if (accountCommand) {
            const row = terminals().filter(t => t.state === 'live' && t.labels?.['repo-tools.account'] === accountCommand[1]).at(-1);
            if (row) showAccount(row.address, cx);
            else notify({
              title: 'Sign-in',
              body: 'Use Sign in / setup in the Usage panel to start a login.',
              level: 'info'
            });
            continue;
          }
          if (/^window-[a-z0-9-]+$/.test(cmd)) {
            this.openWindow(cmd.slice(7), cx);
            continue;
          }
          if (cmd.startsWith('retry-checkpoint:')) {
            this.newConversation(JSON.parse(decodeURIComponent(cmd.slice(17))), cx, true);
            continue;
          }
          if (cmd.startsWith('retry-open:')) {
            const request = JSON.parse(decodeURIComponent(cmd.slice(11)));
            cx.spawn(async cx => {
              try {
                await retryOpen(request);
              } catch (e) {
                notify({
                  title: 'Stream retry needs attention',
                  body: String(e),
                  level: 'warning'
                });
              }
              cx.notify();
            });
            continue;
          }
          if (cmd.startsWith('fresh-chat:')) {
            this.newConversation(JSON.parse(decodeURIComponent(cmd.slice(11))), cx);
            continue;
          }
          if (cmd === 'prune-empty-views') {
            this.pruneEmpty(cx);
            continue;
          }
          if (cmd === 'add-stream' || cmd === 'remove-stream') {
            openOverlay({
              mod: 'repo-portrait',
              kind: 'popup',
              width: 340,
              props: {
                kind: 'layout-menu',
                operation: cmd === 'add-stream' ? 'add' : 'remove'
              }
            });
            continue;
          }
          const syncCommand = /^([a-z0-9-]+)-(update|merge)$/.exec(cmd);
          if (syncCommand) {
            const c = laneConfig(syncCommand[1]);
            if (c) openOverlay({
              mod: 'repo-sync',
              kind: 'dialog',
              width: 780,
              height: 690,
              props: {
                context: c,
                source: syncCommand[2] === 'update' ? 'default' : null
              }
            });
            cx.notify();
            continue;
          }
          const infoCommand = /^([a-z0-9-]+)-info-(agents|context|usage|services|git)$/.exec(cmd);
          if (infoCommand) {
            info(infoCommand[1], infoCommand[2]);
            cx.notify();
            continue;
          }
          const m = /^([a-z0-9-]+)-(conversation|read|files|changes|tests|review|docker|questions|actions|info|choose|browser|quality|interaction)$/.exec(cmd);
          if (m) {
            const lane = m[1],
              name = m[2];
            if (['browser', 'quality', 'interaction'].includes(name)) openOverlay({
              mod: 'repo-portrait',
              kind: 'popup',
              width: 240,
              props: {
                kind: name,
                lane
              }
            });
            else if (name === 'actions') openOverlay({
              mod: 'repo-portrait',
              kind: 'popup',
              width: 285,
              props: {
                kind: 'actions',
                lane
              }
            });
            else if (name === 'choose') picker(lane);
            else if (name === 'info') info(lane, (shared(INFO) || {})[lane] ? null : 'agents');
            else if (name === 'conversation') await focusConversation(lane);
            else view(lane, name);
          }
          cx.notify();
        }
      });
      if (!shared(KEY)) setShared(KEY, props().defaults || {});
      if (!shared(VIEWS)) setShared(VIEWS, {
        top: null,
        bottom: 'docker'
      });
      cx.timer.every(5000, cx => {
        if (this.polling) return;
        this.polling = true;
        cx.spawn(async cx => {
          try {
            await followOpens();
          } finally {
            this.polling = false;
            cx.notify();
          }
        });
      });
      cx.timer.every(3000, cx => this.refresh(cx));
      this.refresh(cx);
    }
    if (this.kind === 'choose') {
      const id = props().overlay;
      picker(props().lane);
      if (id) closeOverlay(id);
    }

  }
  newConversation(target, cx, retry = false) {
    if (this.chatBusy) return;
    this.chatBusy = true;
    cx.spawn(async cx => {
      try {
        const result = await requestCheckpoint(target, retry);
        notify({
          title: 'New conversation',
          body: result.message,
          level: 'info'
        });
      } catch (e) {
        notify({
          title: 'New conversation needs attention',
          body: String(e),
          level: 'warning'
        });
      } finally {
        this.chatBusy = false;
        cx.notify();
      }
    });
  }
  button(id, text, fn, on = false) {
    const t = theme();
    return div().id(id).px(9).py(5).rounded(5).text_size(12).text_color(on ? t.foreground : t.accent).bg(on ? t.selected : t.chrome).hover(s => s.bg(t.hover)).cursor_pointer().on_click(fn).child(text);
  }
  refresh(cx) {
    if (this.busy) return;
    this.busy = true;
    cx.spawn(async cx => {
      try {
        await refreshStatuses(shared(KEY) || {});
      } finally {
        this.busy = false;
        cx.notify();
      }
    });
  }

  sync() {
    const current = layout();
    if (!find(current, 'portrait-root')) return;
    const complete = {
      ...(shared(COMPLETE) || {})
    };
    let completionChanged = false;
    for (const row of terminals()) {
      const state = agentState(row),
        old = this.agentStates[row.address];
      if (state === 'working' && complete[row.address]) {
        delete complete[row.address];
        completionChanged = true;
      } else if (state === 'done' || (old === 'working' && state === 'idle')) {
        if (!complete[row.address]) {
          complete[row.address] = true;
          completionChanged = true;
        }
      }
      this.agentStates[row.address] = state;
    }
    if (completionChanged) setShared(COMPLETE, complete);
    const copy = JSON.parse(JSON.stringify(current));
    let changed = false;
    const selected = shared(VIEWS) || {};
    for (const lane of laneIds(copy)) {
      const c = laneConfig(lane),
        lead = leadFor(terminals(), c),
        existingBody = find(copy, lane + '-conversation'),
        body = ensureConversation(copy, lane);
      if (body && !existingBody) changed = true;
      const content = lead ? {
        terminal: lead.address
      } : {
        mod: 'repo-portrait',
        props: {
          kind: 'empty',
          lane
        }
      };
      if (!body) continue;
      if (JSON.stringify(body.content) !== JSON.stringify(content)) {
        body.content = content;
        changed = true;
      }
      const dock = find(copy, lane + '-views'),
        stack = dock,
        hide = !selected[lane];
      if (!dock) {
        this.error = 'Missing view: ' + lane + '-views';
        continue;
      }
      const side = find(copy, lane + '-info');
      if (side && side.hidden !== !(shared(INFO) || {})[lane]) {
        side.hidden = !(shared(INFO) || {})[lane];
        changed = true;
      }
      if (dock.hidden !== hide) {
        dock.hidden = hide;
        changed = true;
      }
      if (selected[lane] && stack.active !== lane + '-' + selected[lane]) {
        stack.active = lane + '-' + selected[lane];
        changed = true;
      }
    }
    if (changed) {
      try {
        run('layout.set', {
          layout: copy
        });
        this.error = '';
      } catch (e) {
        this.error = String(e);
      }
    }
  }
  openWindow(lane, cx) {
    if (this.busy) return;
    this.busy = true;
    this.error = '';
    cx.notify();
    const overlay = props()?.overlay;
    cx.spawn(async cx => {
      try {
        const r = await exec('python3', [appHome() + '/helpers/window.py', 'open', '--source', appHome(), '--lane', lane]);
        if (r.code) throw Error(r.stderr || r.stdout);
        const out = JSON.parse(r.stdout);
        if (overlay) closeOverlay(overlay);
        notify({
          title: 'Separate Herdr window',
          body: out.message,
          level: 'success'
        });
      } catch (e) {
        this.error = String(e);
        notify({
          title: 'Cannot open a separate window',
          body: this.error,
          level: 'warning'
        });
      } finally {
        this.busy = false;
        cx.notify();
      }
    });
  }
  render(cx) {
    const t = theme(),
      p = props() || {},
      lane = p.lane,
      c = laneConfig(),
      lead = leadFor(terminals(), c),
      buttons = (items) => h_flex().gap(4).flex_wrap().items_center().children(items);
    if (this.panel) return this.panel.render(cx);
    if (this.kind === 'progress') {
      const job = (shared('repo.checkpoint-status') || {})[p.key] || {},
        op = operation(job),
        bad = op.failed;
      return v_flex().p(16).gap(10).bg(t.background).text_color(t.foreground)
        .child(div().font_semibold().child('Conversation checkpoint'))
        .children((op.steps || []).map(step => div().text_size(12).text_color(step.status === 'failed' ? t.blocked : step.status === 'active' ? t.accent : t.muted).child(stepText(step))))
        .child(div().text_size(12).text_color(bad ? t.blocked : t.foreground).child(job.message || 'Waiting for checkpoint status…'))
        .when(op.can_retry, e => e.child(control('retry-checkpoint', 'Retry unfinished step', () => {
          const c = Object.values(shared(KEY) || {}).find(c => JSON.stringify([c.on, c.cwd]) === p.key);
          if (c) this.newConversation({
            ...c,
            terminal: job.target,
            token: job.token
          }, cx, true);
        }, {
          icon: 'refresh'
        })))
        .child(div().text_size(11).text_color(t.muted).child('Stage reports show activity. Only verification confirms the saved checkpoint.'));
    }
    if (this.kind === 'manager') {
      this.sync();
      return h_flex().size_full().pl(85).pr(10).gap(8).items_center().bg(t.chrome)
        .child(div().flex_1().text_size(13).font_semibold().text_color(t.foreground).child(this.error || p.windowTitle || 'Studio / Work · Portrait'))
        .child(control('portrait-sidebar', 'Spaces & agents', () => run('layout.toggle', {
          id: 'sidebar'
        }), {
          icon: 'tree',
          compact: true
        }))
        .child(control('portrait-add', 'Add stream', () => openOverlay({
          mod: 'repo-portrait',
          kind: 'popup',
          width: 340,
          props: {
            kind: 'layout-menu',
            operation: 'add'
          }
        }), {
          icon: 'plus',
          dropdown: true
        }))
        .child(control('portrait-remove', 'Remove stream view', () => openOverlay({
          mod: 'repo-portrait',
          kind: 'popup',
          width: 340,
          props: {
            kind: 'layout-menu',
            operation: 'remove'
          }
        }), {
          icon: 'minus',
          compact: true
        }));
    }
    if (this.kind === 'empty') return v_flex().size_full().justify_center().items_center().gap(12).bg(t.background).text_color(t.muted)
      .child(div().text_size(16).child((c?.repo || 'Repository') + ' · ' + (c?.stream || '')))
      .child(div().text_size(12).child('No live ' + (c?.role === 'studio' ? 'Studio' : 'Work') + ' conversation in Herdr.'))
      .child(this.button('empty-open', c ? 'Open conversation' : 'Choose stream', () => c ? dialog(lane, 'open') : picker(lane)))
      .child(div().text_size(11).child('Your checkout and saved conversations remain available.'));
    if (this.kind === 'layout-menu') {
      const ids = laneIds(layout()),
        configs = shared(KEY) || {};
      let el = v_flex().p(12).gap(5).bg(t.surface).text_color(t.foreground)
        .child(div().px(8).py(4).font_semibold().child(p.operation === 'remove' ? 'Remove a stream view' : this.separateWindow ? 'Open which stream in a new window?' : this.splitAxis ? 'Which stream should split?' : 'Add a stream'));
      if (this.error) el = el.child(div().text_size(12).text_color(t.muted).child(this.error));
      if (this.confirmLast) return el
        .child(div().text_size(12).child('This is the last stream view. Close this Herdr instance too? Agents and Docker keep running; other windows stay open.'))
        .child(control('close-last-window', 'Close this Herdr instance', (_e, cx) => this.removeSlot(this.confirmLast.id, cx, this.confirmLast.discard, 'close'), {icon:'external'}))
        .child(control('keep-empty-window', 'Keep an empty window', (_e, cx) => this.removeSlot(this.confirmLast.id, cx, this.confirmLast.discard, 'keep'), {icon:'minus'}))
        .child(control('cancel-last-window', 'Cancel', (_e, cx) => { this.confirmLast=null; this.confirmRemove=null; cx.notify(); }));
      if (this.confirmRemove) return el
        .child(div().text_size(12).child('This view has unsaved editor text. Close it and discard that text? Files on disk and running agents will be preserved.'))
        .child(control('confirm-remove-view', 'Discard editor text and close view', (_e, cx) => this.removeSlot(this.confirmRemove, cx, true), {icon:'minus'}))
        .child(control('cancel-remove-view', 'Keep view', (_e, cx) => { this.confirmRemove=null; cx.notify(); }));
      if (p.operation === 'remove' || this.splitAxis || this.separateWindow) {
        el = el.children(ids.map(id => control('target-' + id, (configs[id]?.repo || 'Empty') + ' / ' + (configs[id]?.stream || id), (_e, cx) => p.operation === 'remove' ? this.removeSlot(id, cx) : this.separateWindow ? this.openWindow(id, cx) : this.addSlot(this.splitAxis, id, cx), {
          icon: p.operation === 'remove' ? 'minus' : this.separateWindow ? 'external' : 'columns'
        }).w_full()));
        if (p.operation === 'remove') el = el.child(div().px(8).py(5).text_size(11).text_color(t.muted).child('Removes this view only. Agents, Docker and Git worktrees keep running.'));
      } else {
        el = el.child(control('add-below', 'Below · stack vertically', (_e, cx) => this.addSlot('column', null, cx), {
            icon: 'rows'
          }).w_full())
          .child(control('add-beside', 'Beside · side by side', (_e, cx) => this.addSlot('row', null, cx), {
            icon: 'columns'
          }).w_full())
          .child(control('split-below', 'Split a stream · top / bottom', (_e, cx) => {
            this.splitAxis = 'column';
            cx.notify();
          }, {
            icon: 'rows'
          }).w_full())
          .child(control('split-beside', 'Split a stream · left / right', (_e, cx) => {
            this.splitAxis = 'row';
            cx.notify();
          }, {
            icon: 'columns'
          }).w_full())
          .child(control('add-window', 'In a separate Herdr window', (_e, cx) => {
            const template = ids[0];
            closeOverlay(p.overlay);
            picker(template, {
              newWindow: true
            });
          }, {
            icon: 'external'
          }).w_full());
      }
      return el.when(!!this.error, e => e.child(div().px(8).text_size(12).text_color(t.blocked).child(this.error)));
    }
    if (this.kind === 'interaction') {
      const rows = relatives(c),
        flow = (shared('repo.flow-status') || {})[JSON.stringify([c?.on, c?.cwd])],
        tone = interactionTone(rows, lead, shared(COMPLETE)) || (flow?.state === 'needs-you' ? 'attention' : null);
      return v_flex().p(8).gap(4).bg(t.surface).text_color(t.foreground)
        .child(control('interaction-conversation', 'Conversation', (_e, cx) => {
          closeOverlay(p.overlay);
          cx.spawn(async cx => {
            await focusConversation(lane);
            cx.notify();
          });
        }, {
          icon: 'message',
          tone: tone === 'ready' ? 'ready' : tone === 'error' ? 'error' : null
        }).w_full())
        .child(control('interaction-questions', 'Questions' + ((rows.some(r => agentState(r) === 'blocked') || flow?.state === 'needs-you') ? ' · needs you' : ''), () => {
          view(lane, 'questions');
          closeOverlay(p.overlay);
        }, {
          icon: 'question',
          tone: tone === 'attention' ? 'attention' : null
        }).w_full());
    }
    if (this.kind === 'actions') {
      const item = (id, label, action, role) => control(id, label, () => {
        closeOverlay(p.overlay);
        dialog(lane, action, role);
      }, {
        icon: ({
          open: 'message',
          prepare: 'book',
          implement: 'play',
          helper: 'agents',
          pause: 'pause'
        })[action]
      });
      return v_flex().p(12).gap(5).bg(t.surface).text_color(t.foreground)
        .child(div().px(8).py(4).text_size(12).font_semibold().child(c.repo + ' · ' + c.stream))
        .when(!!lead, e => e.child(control('new-chat', 'New conversation · same stream', () => {
          const target = {
            ...c,
            terminal: lead.address
          };
          closeOverlay(p.overlay);
          openOverlay({
            mod: 'confirm',
            kind: 'dialog',
            width: 470,
            height: 260,
            props: {
              title: 'Save checkpoint and start fresh?',
              detail: 'Ask the current agent to save progress and next steps in the handoff, commit intended changes (WIP is fine), and push this stream branch. Restart only after that checkpoint is verified. No full test run or review. Busy agents/workflows must finish first; commit or push failures keep the chat open.',
              command: {
                name: 'repo-portrait.fresh-chat:' + encodeURIComponent(JSON.stringify(target))
              }
            }
          });
        }, {
          icon: 'message'
        })))
        .when(!!lead, e => e.child(control('handoff-role', 'Hand off to…', () => {
          closeOverlay(p.overlay);
          openOverlay({mod:'repo-stream-picker',kind:'dialog',width:560,height:340,props:{handoff:true,lane,context:{...c,terminal:lead.address}}});
        }, {icon:'message'})))
        .child(item('open-studio', 'Open Studio conversation', 'open', 'studio'))
        .child(item('open-work', 'Open Work conversation', 'open', 'work'))
        .child(item('prepare', 'Prepare implementation', 'prepare', 'work'))
        .child(item('implement', 'Implement → Review', 'implement', 'work'))
        .child(item('helper', 'Add scoped helper', 'helper', c.role))
        .child(item('pause', 'Pause workflow', 'pause', c.role));
    }
    if (this.kind === 'browser') {
      const picked = (shared(VIEWS) || {})[lane];
      return v_flex().p(8).gap(4).bg(t.surface).text_color(t.foreground)
        .children([
          ['read', 'Docs', 'book', 'Markdown and text documents'],
          ['files', 'Files', 'folder', 'Browse and edit repository files'],
          ['changes', 'Git', 'changes', 'Working changes and staging']
        ].map(([id, label, icon, detail]) =>
          control('browser-' + id, label, () => {
            view(lane, id);
            closeOverlay(p.overlay);
          }, {
            icon,
            selected: picked === id
          }).w_full().tooltip(detail)));
    }
    if (this.kind === 'quality') {
      const picked = (shared(VIEWS) || {})[lane];
      return v_flex().p(8).gap(4).bg(t.surface).text_color(t.foreground)
        .children([
          ['tests', 'Tests', 'test'],
          ['review', 'Review', 'shield']
        ].map(([id, label, icon]) => control('quality-' + id, label, () => {
          view(lane, id);
          closeOverlay(p.overlay);
        }, {
          icon,
          selected: picked === id
        }).w_full()));
    }
    if (this.kind === 'choose') return div();
    const r = scopedRequest();
    if (r && !this.seen.has(r.key)) {
      this.seen.add(r.key);
      let ack = false;
      try {
        ack = JSON.parse(terminals().find(t => t.address === r.address)?.labels?.['repo-read.result'] || '{}').id === r.id;
      } catch {}
      if (!ack) view(lane, /\.(md|markdown|mdown|mkd|txt)$/i.test(r.path) ? 'read' : 'files');
    }
    const key = c ? JSON.stringify([c.on, c.cwd]) : null,
      status = key ? (shared('repo.flow-status') || {})[key] : null;
    const picked = (shared(VIEWS) || {})[lane],
      browser = ['read', 'files', 'changes'].includes(picked) ? picked : (shared('repo.portrait.browser') || {})[lane] || 'read';
    const state = agentState(lead) || 'not open';
    if (!c) return h_flex().size_full().px(10).items_center().bg(t.chrome).child(control('configure-empty', 'Choose a stream', () => picker(lane), {
      icon: 'plus',
      dropdown: true
    }));
    const tone = interactionTone(relatives(c), lead, shared(COMPLETE)) || (status?.state === 'needs-you' ? 'attention' : null),
      failed = panels => panelFailed(lane, c, panels);
    const compact = (this.width || 1500) < 1250;
    return h_flex().id('stream-controls').size_full().px(8).gap(4).items_center().bg(t.chrome).text_color(t.foreground)
      .on_size_change((size, cx) => {
        if ((size.width < 1250) !== ((this.width || 1500) < 1250)) {
          this.width = size.width;
          cx.notify();
        }
      })
      .child(div().id('choose-stream').min_w(120).max_w(300).flex_none().truncate().font_semibold().text_size(12).cursor_pointer().tooltip('Change stream or agent · ' + (c?.repo || '') + ' / ' + (c?.stream || ''))
        .on_click(() => picker(lane)).child((c?.repo || 'Choose') + ' / ' + (c?.stream || 'stream') + ' ▾'))
      .child(div().text_size(10).flex_none().text_color(state === 'working' ? t.working : state === 'blocked' ? t.blocked : t.muted).child((c?.role || '') + ' · ' + state))
      .when(!!((shared('repo.checkpoint-status') || {})[key]?.state || (shared('repo.operation-status') || {})[lane]?.message || ['queued', 'preparing', 'implementing', 'fixing', 'reviewing', 'needs-you'].includes(status?.state)), e => {
        const job = (shared('repo.checkpoint-status') || {})[key] || {},
          op = (shared('repo.operation-status') || {})[lane];
        const j = currentOperation(job, op, status),
          bad = operation(j).failed || j?.error;
        const text = progressText(j);
        return e.child(div().max_w(190).truncate().text_size(11).text_color(bad ? t.blocked : t.accent).cursor_pointer().on_click(() => {
          if (j === job) openOverlay({
            mod: 'repo-portrait',
            kind: 'dialog',
            width: 430,
            props: {
              kind: 'progress',
              key
            }
          });
          else notify({
            title: 'Stream progress',
            body: j?.message || j?.state,
            level: bad ? 'warning' : 'info'
          });
        }).tooltip((j?.message || '') + '\n' + (j?.history || []).map(h => h.stage).join(' → ')).child(text));
      })
      .when(!!(shared('repo.operation-status') || {})[lane]?.retry, e => e.child(control('retry-opening', 'Retry', () => run('repo-portrait.retry-open:' + encodeURIComponent(JSON.stringify((shared('repo.operation-status') || {})[lane].retry))), {
        icon: 'refresh',
        compact: true
      })))
      .when(!!(shared('repo.operation-errors') || {})[key], e => e.child(div().text_size(11).text_color(t.blocked).tooltip((shared('repo.operation-errors') || {})[key]).child('⚠ Status unavailable')))
      .child(div().flex_1().min_w(8))
      .child(control('view-agent', picked === 'questions' ? 'Questions' : 'Conversation', () => openOverlay({
        mod: 'repo-portrait',
        kind: 'popup',
        width: 245,
        props: {
          kind: 'interaction',
          lane
        }
      }), {
        icon: picked === 'questions' ? 'question' : 'message',
        selected: !picked || picked === 'questions',
        compact,
        dropdown: true,
        tone
      }))
      .child(control('view-docker', 'Docker', () => view(lane, picked === 'docker' ? null : 'docker'), {
        icon: 'docker',
        selected: picked === 'docker',
        compact,
        tone: failed(['docker']) ? 'error' : null
      }))
      .child(control('view-browser', browser === 'read' ? 'Docs' : browser === 'files' ? 'Files' : 'Git', () => openOverlay({
        mod: 'repo-portrait',
        kind: 'popup',
        width: 230,
        props: {
          kind: 'browser',
          lane
        }
      }), {
        icon: browser === 'read' ? 'book' : browser === 'files' ? 'folder' : 'changes',
        selected: ['read', 'files', 'changes'].includes(picked),
        compact,
        dropdown: true,
        tone: failed(['read', 'files', 'changes']) ? 'error' : null
      }))
      .child(control('view-quality', picked === 'review' ? 'Review' : 'Tests', () => openOverlay({
        mod: 'repo-portrait',
        kind: 'popup',
        width: 210,
        props: {
          kind: 'quality',
          lane
        }
      }), {
        icon: picked === 'review' ? 'shield' : 'test',
        selected: ['tests', 'review'].includes(picked),
        compact,
        dropdown: true,
        tone: failed(['tests', 'review']) ? 'error' : null
      }))
      .child(control('flow-actions', 'Actions', () => openOverlay({
        mod: 'repo-portrait',
        kind: 'popup',
        width: 300,
        props: {
          kind: 'actions',
          lane
        }
      }), {
        icon: 'bolt',
        compact,
        dropdown: true
      }))
      .child(control('stream-info', 'Information', () => info(lane, (shared(INFO) || {})[lane] ? null : 'agents'), {
        icon: 'sidebar',
        selected: !!(shared(INFO) || {})[lane],
        compact: true
      }));
  }

  addSlot(axis, target, cx) {
    const template = target || laneIds(layout())[0];
    closeOverlay(props().overlay);
    picker(template, {
      placement: {
        axis,
        target
      },
      fresh: true
    });
  }
  pruneEmpty(cx) {
    let tree = layout();
    const configs = shared(KEY) || {};
    let changed = false;
    for (const id of laneIds(tree)) {
      if (laneIds(tree).length <= 1) break;
      const node = find(tree, id + '-conversation');
      if (!configs[id] && node?.content?.mod === 'repo-portrait' && node.content.props?.kind === 'empty' && !Object.entries(shared('repo.portrait.unsaved') || {}).some(([key, value]) => key.startsWith(id + ':') && value)) {
        tree = removeLane(tree, id);
        changed = true;
      }
    }
    if (changed) run('layout.set', {
      layout: tree
    });
    cx.notify();
  }
  removeSlot(id, cx, discard=false, lastChoice=null) {
    try {
      if (!discard && Object.entries(shared('repo.portrait.unsaved') || {}).some(([key, value]) => key.startsWith(id + ':') && value)) {
        this.confirmRemove=id;
        cx.notify();
        return;
      }
      const current = layout();
      const last = laneIds(current).length === 1 && laneIds(current)[0] === id;
      if (last && !lastChoice) {
        this.confirmLast={id, discard};
        this.confirmRemove=null;
        cx.notify();
        return;
      }
      const tree = removeLane(current, id);
      run('layout.set', {
        layout: tree
      });
      for (const key of [KEY, VIEWS, INFO, 'repo.portrait.browser']) {
        setShared(key, withoutLaneState(shared(key), id));
      }
      setShared('repo.portrait.unsaved', withoutLaneState(shared('repo.portrait.unsaved'), id, true));
      // A pending open must not put a closed stream back in this view.
      setShared('repo.open-requests', Object.fromEntries(Object.entries(shared('repo.open-requests') || {}).filter(([, request]) => request?.lane !== id)));
      closeOverlay(props()?.overlay);
      // Each managed window is its own Herdr app instance; never stop hc.
      if (last && lastChoice === 'close') run('app.quit');
    } catch (e) {
      this.error = e?.message || (e ? String(e) : 'Could not close this view. Reopen the stream menu and try again.');
      cx.notify();
    }
  }

  close() {
    this.panel?.close?.();
    this.path?.release();
    this.stream?.release();
    this.repo?.release();
  }
}
