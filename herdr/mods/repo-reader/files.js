// NUL-separated Git output preserves spaces, quotes, and newlines in file names.
export function parseFiles(status, tracked) {
  const changed = new Map();
  for (const record of status.split('\0').filter(Boolean)) {
    const xy = record.slice(0,2), path = record.slice(3);
    if (!path || path.endsWith('/')) continue;
    const conflict = xy.includes('U') || xy === 'AA' || xy === 'DD';
    const deleted = !conflict && (xy[1] === 'D' || xy === 'D ');
    const label = conflict ? 'Conflict' : deleted ? 'Deleted' : xy === '??' ? 'New' : xy.includes('A') ? 'Added' : 'Modified';
    changed.set(path, { path, label, deleted });
  }
  const paths = new Set([...tracked.split('\0').filter(Boolean), ...changed.keys()]);
  const all = [...paths].sort().map(path => changed.get(path) ?? { path, label: '', deleted: false });
  return { all, changed: all.filter(f => changed.has(f.path)) };
}
export function fileChoices(snapshot, forceAll, query = '') {
  const modified = !forceAll && snapshot.changed.length > 0;
  const source = modified ? snapshot.changed : snapshot.all;
  const words = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
  return { modified, total: source.length, rows: source.filter(f => words.every(w => f.path.toLowerCase().includes(w))) };
}
