// The fridge twin kept in the browser: pure state changes plus one storage commit (plan v4 R3, D1-D3).
// Every change returns a new twin; nothing here touches the page. Rules:
// - nothing is ever discarded: things that lose their level go to `unplaced`, and `unplaced` survives every change;
// - an answer is applied only to the fridge, holder and layout revision it was asked for (a ticket);
// - a save is believed only after it is read back.

export const KEY = "gp.twin.v1";

const clone = o => JSON.parse(JSON.stringify(o));

export function seedLevels(row) {
  const levels = {};
  for (const c of row.compartments)
    c.levels.forEach((l, i) => { levels[l.id] = {comp: c.id, kind: l.kind, top: l.top, floor: l.floor, order: i, from: "template"}; });
  for (const p of row.panels) for (const q of p.pockets) levels[q.id] = {panel: p.id, kind: "pocket", from: "template"};
  return levels;
}

export function newTwin(row, sha, rnd = Math.random) {
  return {v: 1, id: rnd().toString(36).slice(2) + Date.now().toString(36), key: row.key, version: row.version,
          layouts: sha, levels: seedLevels(row), items: {}, unplaced: [], traced: {}, next: 1, rev: {}};
}

/** Everything a twin holds that would lose its home if the twin were replaced: Unplaced first, then placed things. */
export function displaced(twin) {
  if (!twin) return [];
  return [...(twin.unplaced || []),
          ...Object.entries(twin.items || {}).flatMap(([lv, its]) => its.map(it => ({...it, was: lv})))];
}

/** A new fridge that keeps every thing the previous one(s) held, in Unplaced. */
export function replaceModel(prevs, row, sha, rnd = Math.random) {
  const next = newTwin(row, sha, rnd);
  next.unplaced = [].concat(...[].concat(prevs).map(displaced));
  return next;
}

export function holderOf(twin, id) {
  const l = twin.levels[id];
  return l ? (l.comp || l.panel) : null;
}

export function liveLevels(twin, comp) {
  return Object.entries(twin.levels).filter(([, l]) => l.comp === comp && !l.retired).sort((a, b) => a[1].top - b[1].top);
}

export function isLive(twin, id) {
  const l = twin.levels[id];
  return !!l && !l.retired;
}

/** Confirm a traced layout: `ys` are the interior lines (0-1). Each new band keeps the old level it overlaps most
 * (one to one, largest overlaps first); new bands get ids never used before; old levels left over retire and their
 * things move to Unplaced. */
export function applyTrace(twin, comp, ys, meta = {}) {
  const sorted = [...ys].sort((a, b) => a - b);
  if (sorted.some(y => !(y > 0 && y < 1))) return {error: "line_outside"};
  if (sorted.some((y, i) => i && y - sorted[i - 1] < 0.03)) return {error: "lines_too_close"};
  const bounds = [0, ...sorted, 1];
  const next = clone(twin);
  const old = liveLevels(twin, comp);
  const bands = bounds.slice(0, -1).map((b, i) => [b, bounds[i + 1]]);
  const pairs = [];
  bands.forEach(([t, f], i) => old.forEach(([, l], j) => {
    const o = Math.min(f, l.floor) - Math.max(t, l.top);
    if (o > 0) pairs.push([o, i, j]);
  }));
  pairs.sort((a, b) => b[0] - a[0]);
  const bandOf = {}, taken = new Set();
  for (const [, i, j] of pairs) if (!(i in bandOf) && !taken.has(j)) { bandOf[i] = j; taken.add(j); }
  bands.forEach(([t, f], i) => {
    let id;
    if (i in bandOf) id = old[bandOf[i]][0];
    else { id = `${comp}/N${next.next++}`; next.levels[id] = {comp, kind: "shelf", from: "added"}; }
    Object.assign(next.levels[id], {top: t, floor: f, order: i});
    delete next.levels[id].retired;
  });
  const moved = [];
  old.forEach(([id], j) => {
    if (taken.has(j)) return;
    next.levels[id].retired = true;
    for (const it of next.items[id] || []) moved.push({...it, was: id});
    delete next.items[id];
  });
  next.unplaced.push(...moved);
  next.traced[comp] = {...meta, levels: bands.length, at: Date.now()};
  next.rev[comp] = (next.rev[comp] || 0) + 1;
  return {next, moved: moved.length, levels: bands.length};
}

/** What an answer must still match when it comes back. */
export function ticket(twin, dest) {
  return {twin: twin.id, key: twin.key, version: twin.version, layouts: twin.layouts, dest,
          rev: twin.rev[holderOf(twin, dest)] || 0};
}

export function ticketProblem(twin, t) {
  if (!twin || twin.id !== t.twin || twin.key !== t.key || twin.version !== t.version || twin.layouts !== t.layouts)
    return "other_fridge";
  if (!isLive(twin, t.dest)) return "level_gone";
  if ((twin.rev[holderOf(twin, t.dest)] || 0) !== t.rev) return "layout_changed";
  return null;
}

/** A count as the person left it: blank = unknown (null), a whole number >= 1, anything else refused. */
export function parseCount(text) {
  const s = String(text ?? "").trim();
  if (s === "") return {ok: true, value: null};
  if (!/^[0-9]+$/.test(s)) return {ok: false};
  const n = Number(s);
  return n >= 1 && Number.isSafeInteger(n) ? {ok: true, value: n} : {ok: false};
}

/** Append the person's confirmed rows to the ticket's holder. A scan adds; it never removes. */
export function addItems(twin, t, rows) {
  const p = ticketProblem(twin, t);
  if (p) return {error: p};
  const next = clone(twin);
  next.items[t.dest] = [...(next.items[t.dest] || []), ...rows];
  return {next};
}

/** Move one Unplaced thing (with the person's edits) onto a live holder, in one change. */
export function placeUnplaced(twin, index, dest, edits = {}) {
  if (!(index >= 0 && index < twin.unplaced.length)) return {error: "no_such_thing"};
  if (!isLive(twin, dest)) return {error: "level_gone"};
  const next = clone(twin);
  const [it] = next.unplaced.splice(index, 1);
  const {was, ...kept} = it;
  next.items[dest] = [...(next.items[dest] || []), {...kept, ...edits, from_unplaced: was ?? null}];
  return {next};
}

/** Write, read back, compare. On any failure, put back what was stored before and say whether that worked:
 * "unchanged" (the write never landed), "restored" (it landed and was undone), "unknown" (storage cannot be
 * trusted; the page must stop saving). */
export function commit(storage, key, next) {
  const s = JSON.stringify(next);
  let before;
  try { before = storage.getItem(key); } catch { return {ok: false, durable: "unknown"}; }
  try {
    storage.setItem(key, s);
    if (storage.getItem(key) === s) return {ok: true};
  } catch { /* fall through to recovery */ }
  try {
    const now = storage.getItem(key);
    if (now === before) return {ok: false, durable: "unchanged"};
    if (before === null) storage.removeItem(key); else storage.setItem(key, before);
    return storage.getItem(key) === before ? {ok: false, durable: "restored"} : {ok: false, durable: "unknown"};
  } catch {
    return {ok: false, durable: "unknown"};
  }
}

/** Operation tickets for async page work: starting a new operation of a kind makes every older one of that kind
 * stale; `cancel` makes all stale (a model change). */
export class Ops {
  constructor() { this.n = 0; this.cur = {}; }
  start(kind) { this.cur[kind] = ++this.n; return {kind, n: this.n}; }
  live(op) { return !!op && this.cur[op.kind] === op.n; }
  cancel() { this.cur = {}; this.n++; }
}
