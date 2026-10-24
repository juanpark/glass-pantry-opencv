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

/** Is this (read from storage) a twin every function here can use? Checks each part the page reads, not only the
 * wrappers: a level is an object with a comp (and numeric top/floor) or a panel, items are arrays of objects. */
export function isTwin(t) {
  const obj = o => !!o && typeof o === "object" && !Array.isArray(o);
  const things = a => Array.isArray(a) && a.every(obj);
  if (!obj(t) || t.v !== 1 || typeof t.id !== "string" || typeof t.key !== "string") return false;
  if (![t.levels, t.items, t.traced, t.rev].every(obj) || !things(t.unplaced)) return false;
  for (const l of Object.values(t.levels)) {
    if (!obj(l) || typeof l.kind !== "string") return false;
    if (typeof l.comp === "string") { if (!Number.isFinite(l.top) || !Number.isFinite(l.floor)) return false; }
    else if (typeof l.panel !== "string") return false;
  }
  return Object.values(t.items).every(things);
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

/** The person says these things are no longer on the ticket's holder (after a rescan asked). They move to
 * Unplaced with where they were; nothing is discarded. `pids` name things by the photo they were read from. */
export function unplaceItems(twin, t, pids) {
  const p = ticketProblem(twin, t);
  if (p) return {error: p};
  const want = new Set(pids);
  const next = clone(twin);
  const here = next.items[t.dest] || [];
  const gone = here.filter(it => want.has(it.pid));
  next.items[t.dest] = here.filter(it => !want.has(it.pid));
  next.unplaced.push(...gone.map(it => ({...it, was: t.dest})));
  return {next, moved: gone.length};
}

/** What a rescan of one holder compares against: its last photo (reduced) and where each thing stood in it.
 * Kept beside the twin, never inside it; only things still on that holder, read from that photo, are sent. */
export const RESCAN_KEY = "gp.rescan.v1";
export function rescanItems(twin, rec) {
  if (!rec || rec.twin !== twin.id || !isLive(twin, rec.level)) return [];
  const pids = new Set((twin.items[rec.level] || []).map(it => it.pid).filter(Boolean));
  return (rec.items || []).filter(it => pids.has(it.pid) && Array.isArray(it.box) && it.box.length === 4
    && it.box.every(Number.isFinite) && it.box[2] > it.box[0] && it.box[3] > it.box[1]);
}

/** Who a rescan record belongs to: the fridge, holder and layout revision at the moment the photo is confirmed.
 * Taken before any await; checked again just before the record is written (a switch or re-trace in between wins). */
export function recordOwner(twin, level) {
  return {twin: twin.id, level, rev: twin.rev[holderOf(twin, level)] || 0};
}
export function ownerStill(twin, o) {
  return !!twin && twin.id === o.twin && isLive(twin, o.level) && (twin.rev[holderOf(twin, o.level)] || 0) === o.rev;
}

/** The strip of a shelf photo that is read and compared: between the person's two lines (fractions of the
 * height, either order), full width, with a small margin so a lid touching a line is not cut. Null when the band is
 * too thin to be a shelf. */
export const BAND_PAD = 0.03, BAND_MIN = 0.08;
export function bandCrop(w, h, a, b) {
  const top = Math.min(a, b), bottom = Math.max(a, b);
  if (!(top >= 0 && bottom <= 1) || bottom - top < BAND_MIN) return null;
  const y0 = Math.max(0, Math.round((top - BAND_PAD) * h)), y1 = Math.min(h, Math.round((bottom + BAND_PAD) * h));
  return {x: 0, y: y0, w, h: y1 - y0};
}

/** The page's shelf-band steps, one open at a time. A step opens only if the pick that asked for it is still live
 * once its photo is ready, so a slow older photo never replaces a newer step. An answer (a crop, a cancel) ends only
 * the step it was made for, so a late crop is never handed to a newer pick, holder or fridge. */
export class BandSteps {
  constructor() { this.cur = null; }
  /** prepare() -> the step's data; live() -> is the pick still current; show(step) draws it. Resolves to the
   * step's answer, or null when it was replaced, cancelled or went stale. */
  async open(prepare, live, show) {
    const data = await prepare();
    if (!live()) return null;
    this.end(null);
    const step = {...data, live};
    return new Promise(res => { step.res = res; this.cur = step; show(step); });
  }
  /** End `step` (default: the open one) with `result`; a stale step's result is dropped. False if not open. */
  end(result, step = this.cur) {
    if (!step || this.cur !== step) return false;
    this.cur = null;
    step.res(step.live() ? result : null);
    return true;
  }
}

/** A rescan found things moved on the same holder: their place for the 3D view follows (nothing else changes). */
export function setPlacement(twin, t, byPid) {
  const p = ticketProblem(twin, t);
  if (p) return {error: p};
  const next = clone(twin);
  let moved = 0;
  next.items[t.dest] = (next.items[t.dest] || []).map(it => {
    const u = it.pid && byPid[it.pid];
    if (!u) return it;
    moved++;
    return {...it, ...u};
  });
  return {next, moved};
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

// ---- outline geometry: the unit square (u, v in 0-1, the compartment's front) <-> the person's quad on the photo ----

/** 3x3 homography taking the unit square's corners (0,0) (1,0) (1,1) (0,1) to the quad's TL, TR, BR, BL. */
export function squareToQuad(q) {
  const [[x0, y0], [x1, y1], [x2, y2], [x3, y3]] = q;
  const dx1 = x1 - x2, dx2 = x3 - x2, dy1 = y1 - y2, dy2 = y3 - y2;
  const sx = x0 - x1 + x2 - x3, sy = y0 - y1 + y2 - y3;
  const den = dx1 * dy2 - dx2 * dy1;
  if (!Number.isFinite(den) || Math.abs(den) < 1e-12) return null;
  const g = (sx * dy2 - dx2 * sy) / den, h = (dx1 * sy - sx * dy1) / den;
  // w = g u + h v + 1 is linear, so positive at the square's four corners means no point of it maps to infinity
  if (!(g + 1 > 1e-9 && h + 1 > 1e-9 && g + h + 1 > 1e-9)) return null;
  return [[x1 - x0 + g * x1, x3 - x0 + h * x3, x0], [y1 - y0 + g * y1, y3 - y0 + h * y3, y0], [g, h, 1]];
}

/** Why an outline cannot be drawn into, or null. Looser than the server's straightening limits (the unverified path
 * skips those), but still a real shape: four finite, distinct corners in TL, TR, BR, BL order around a convex shape,
 * every corner between 20° and 160° (a corner pushed onto the diagonal is not a corner), and, given the photo's
 * [w, h], at least 5% of the photo. */
export const OUTLINE_MIN_AREA = 0.05;
export function outlineProblem(q, size) {
  if (!Array.isArray(q) || q.length !== 4 || !q.every(p => p.length === 2 && p.every(Number.isFinite))) return "not_finite";
  for (let i = 0; i < 4; i++) for (let j = i + 1; j < 4; j++)
    if (Math.hypot(q[i][0] - q[j][0], q[i][1] - q[j][1]) < 1) return "repeated_corner";
  const turns = q.map((a, i) => {
    const b = q[(i + 1) % 4], c = q[(i + 2) % 4];
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
  });
  if (turns.every(t => t < 0)) return "not_ordered";  // a mirror image: the corners go round the wrong way
  if (!turns.every(t => t > 0)) return "not_convex";
  for (let i = 0; i < 4; i++) {
    const p = q[i], a = q[(i + 3) % 4], b = q[(i + 1) % 4];
    const u = [a[0] - p[0], a[1] - p[1]], v = [b[0] - p[0], b[1] - p[1]];
    const deg = Math.acos(Math.max(-1, Math.min(1, (u[0] * v[0] + u[1] * v[1]) / (Math.hypot(...u) * Math.hypot(...v))))) * 180 / Math.PI;
    if (deg < 20 || deg > 160) return "not_convex";
  }
  if (size) {
    const area = Math.abs(q.reduce((s, p, i) => s + p[0] * q[(i + 1) % 4][1] - q[(i + 1) % 4][0] * p[1], 0)) / 2;
    if (area < OUTLINE_MIN_AREA * size[0] * size[1]) return "too_small";
  }
  return squareToQuad(q) ? null : "not_convex";
}

export function applyH(m, [x, y]) {
  const w = m[2][0] * x + m[2][1] * y + m[2][2];
  return [(m[0][0] * x + m[0][1] * y + m[0][2]) / w, (m[1][0] * x + m[1][1] * y + m[1][2]) / w];
}

export function invertH(m) {
  const [[a, b, c], [d, e, f], [g, h, i]] = m;
  const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g;
  const det = a * A + b * B + c * C;
  if (!Number.isFinite(det) || Math.abs(det) < 1e-12) return null;
  return [[A / det, -(b * i - c * h) / det, (b * f - c * e) / det],
          [B / det, (a * i - c * g) / det, -(a * f - c * d) / det],
          [C / det, -(a * h - b * g) / det, (a * e - b * d) / det]];
}

/** Where a level line at height v of the compartment sits on the photo: its two ends. */
export function lineOnPhoto(m, v) { return [applyH(m, [0, v]), applyH(m, [1, v])]; }

/** The compartment height (0-1) a point on the photo corresponds to, or null outside the outline. */
export function vAt(m, p) {
  const inv = invertH(m);
  if (!inv) return null;
  const [u, v] = applyH(inv, p);
  return u >= -0.05 && u <= 1.05 && v >= 0 && v <= 1 ? v : null;
}

/** The names Confirm would give the spaces between these lines ("Shelf 1" ... "Drawer 2", numbered within a kind, top
 * to bottom), taken from the same applyTrace result that Confirm saves; null when that layout would be refused. */
export function traceNames(twin, comp, vs) {
  const res = applyTrace(twin, comp, vs);
  if (res.error) return null;
  const seen = {};
  return liveLevels(res.next, comp).map(([, l]) => {
    const k = l.kind === "drawer" ? "Drawer" : "Shelf";
    seen[k] = (seen[k] || 0) + 1;
    return `${k} ${seen[k]}`;
  });
}

/** Interior lines (heights 0-1) between a compartment's live levels, top to bottom. */
export function levelLines(twin, comp) {
  return liveLevels(twin, comp).slice(0, -1).map(([id, l]) => ({v: l.floor, id}));
}

/** (level, pid) -> {photo, box} from the stored rescan records of this twin, per shelf: a photo id that two shelves
 * share keeps each shelf's own photo. null when that shelf has no record of the thing. */
export function facesOf(records, twinId) {
  return (level, pid) => {
    const r = records && records[level];
    if (!r || r.twin !== twinId) return null;
    const it = (r.items || []).find(i => i.pid === pid);
    return it ? {photo: r.photo, box: it.box} : null;
  };
}

/** Forget this page's fridge and kept photos on this device (both keys); other sites' and pages' data stay.
 * {ok} only when both keys are read back as absent; a refused or partial removal is {ok: false}. */
export function forget(st) {
  try {
    for (const k of [KEY, RESCAN_KEY]) { try { st.removeItem(k); } catch { /* checked below */ } }
    return {ok: [KEY, RESCAN_KEY].every(k => st.getItem(k) === null)};
  } catch { return {ok: false}; }
}

/** One tab writes the fridge at a time: hold the browser's lock for this page's lifetime when it is free. Resolves true
 * for the writer, false when another tab holds it. Without Web Locks (old browsers) the tab writes, as before. */
export function claimWriter(locks, name = "gp.fridge.writer") {
  if (!locks || !locks.request) return Promise.resolve(true);
  return new Promise(res => {
    locks.request(name, {ifAvailable: true}, lock => {
      if (!lock) { res(false); return null; }
      res(true);
      return new Promise(() => {});  // held until the tab closes
    });
  });
}
