// Pure selection: an inactive stream never changes the currently displayed document.
export function requestOf(terminal) {
  try {
    const r = JSON.parse(terminal.labels?.['repo-read.request'] ?? '{}');
    if (r.v !== 1 || typeof r.id !== 'string' || !/^[a-f0-9]{24}$/.test(r.id)
      || typeof r.path !== 'string' || !r.path || r.path.startsWith('/')
      || r.path.split('/').some(p => p === '..') || r.path.includes('\0')
      || typeof r.root !== 'string' || !r.root.startsWith('/')
      || r.root !== (terminal.labels?.['repo-tools.checkout'] || terminal.cwd)
      || !Number.isFinite(r.time)) return null;
    return { ...r, address: terminal.address, key: `${terminal.address}:${r.id}` };
  } catch { return null; }
}
export function machineOf(address) {
  return address.includes('/') ? address.slice(0, address.lastIndexOf('/')) : null;
}
export function selectRequest(all, spaceList, paneList, focus) {
  const space = spaceList.find(s => s.active);
  if (!space) return null;
  const shown = all.find(t => t.address === (focus?.shown || focus?.terminal));
  const root = shown?.labels?.['repo-tools.checkout'];
  const on = shown ? machineOf(shown.address) : space.machine;
  const visible = new Set(paneList.filter(p => space.tabs.some(t => t.id === p.tab)).map(p => p.terminal));
  return all.filter(t => machineOf(t.address) === on
    && (root ? t.labels?.['repo-tools.checkout'] === root : visible.has(t.address)))
    .map(requestOf).filter(Boolean).sort((a,b) => b.time - a.time || b.id.localeCompare(a.id))[0] ?? null;
}

// A reader can browse the checkout even before an agent has requested a file.
export function selectLocation(all, spaceList, paneList, focus) {
  const space = spaceList.find(s => s.active);
  if (!space) return null;
  const pane = paneList.find(p => p.pane === focus?.pane)
    ?? paneList.find(p => space.tabs.some(t => t.active && t.id === p.tab) && p.terminal);
  const terminal = all.find(t => t.address === (focus?.shown || focus?.terminal || pane?.terminal));
  const cwd = terminal?.labels?.['repo-tools.checkout'] || pane?.cwd || focus?.cwd || terminal?.cwd || space.folder;
  const on = terminal ? machineOf(terminal.address) : space.machine;
  return cwd ? { cwd, on, key: JSON.stringify([on, cwd]) } : null;
}

// Dialogs target the clicked space/machine, never a different focused repository.
export function selectWorkflowContext(all, spaceList, paneList, focus, options={}) {
  const requested=options.space===undefined?null:spaceList.find(s=>s.id===options.space);
  let space=requested||spaceList.find(s=>s.active), f=focus;
  if(requested) {
    const inSpace=paneList.filter(p=>requested.tabs.some(t=>t.id===p.tab));
    const pane=inSpace.find(p=>p.pane===focus?.pane)
      ||inSpace.find(p=>requested.tabs.some(t=>t.active&&t.id===p.tab)&&p.terminal)
      ||inSpace.find(p=>p.terminal);
    f=pane?{pane:pane.pane,terminal:pane.terminal,cwd:pane.cwd}:{};
  }
  const loc=selectLocation(all,spaceList.map(s=>({...s,active:s===space})),paneList,f);
  const on=options.on!==undefined?options.on:loc?.on??requested?.machine??null;
  if(!loc||on!==loc.on||(options.space!==undefined&&!requested))return {on,cwd:'',stream:''};
  const pane=paneList.find(p=>p.pane===f?.pane)
    ||paneList.find(p=>space?.tabs.some(t=>t.active&&t.id===p.tab)&&p.terminal);
  const terminal=all.find(t=>t.address===(f?.shown||f?.terminal||pane?.terminal));
  const branch=pane?.branch||space?.branch||'';
  return {...loc,on,stream:terminal?.labels?.['repo-tools.stream']||(branch.startsWith('codex/')?branch.slice(6):'')};
}
