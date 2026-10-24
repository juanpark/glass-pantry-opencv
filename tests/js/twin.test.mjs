// node --test tests/js/   (TWIN=path/to/module.js to run against another implementation)
import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {pathToFileURL, fileURLToPath} from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const T = await import(pathToFileURL(process.env.TWIN || path.join(here, "../../web/twin.js")).href);
const ROWS = JSON.parse(readFileSync(path.join(here, "../../web/layouts/layouts.json"), "utf8"));
const A = ROWS.find(r => r.key === "model:samsung-rb38j-bottom");
const B = ROWS.find(r => r.key === "template:standard");
let seq = 0;
const rnd = () => (++seq) / 1000;

class Mem {  // a storage double whose faults are switched on per test
  constructor() { this.m = new Map(); this.failSet = false; this.failGet = false; this.lie = false; this.failRestore = false; this.sets = 0; }
  getItem(k) {  // with `lie`, the first read after a write returns something else (a corrupted read-back)
    if (this.failGet) throw new Error("get");
    const v = this.m.has(k) ? this.m.get(k) : null;
    if (this.lieNext) { this.lieNext = false; return v + " "; }
    return v;
  }
  setItem(k, v) {
    this.sets++;
    if (this.failSet || (this.failRestore && this.sets > 1)) throw new Error("quota");
    this.m.set(k, v);
    if (this.lie) this.lieNext = true;
  }
  removeItem(k) { this.m.delete(k); }
}

const thing = (n, more = {}) => ({appearance: n, label: null, count: 1, source: "s", ...more});

// ---- finding 1: Unplaced survives every model change ----
test("switching with only Unplaced things keeps them", () => {
  const a = {...T.newTwin(A, "h", rnd), unplaced: [thing("eggs", {count: 6})]};
  const b = T.replaceModel(a, B, "h", rnd);
  assert.deepEqual(b.unplaced.map(i => [i.appearance, i.count]), [["eggs", 6]]);
});

test("switching with placed and Unplaced things keeps all, with where they were", () => {
  const a = {...T.newTwin(A, "h", rnd), unplaced: [thing("kimchi")], items: {"cold/L0": [thing("milk")], "cold/L1": [thing("jam")]}};
  const b = T.replaceModel(a, B, "h", rnd);
  assert.deepEqual(b.unplaced.map(i => i.appearance + "@" + (i.was ?? "")), ["kimchi@", "milk@cold/L0", "jam@cold/L1"]);
});

test("consecutive switches lose nothing, and a stale saved fridge is carried too", () => {
  const a = {...T.newTwin(A, "old", rnd), items: {"cold/L0": [thing("milk")]}};
  const stale = {...T.newTwin(A, "older", rnd), unplaced: [thing("tofu")]};
  const b = T.replaceModel([a, stale], B, "h", rnd);
  const c = T.replaceModel(b, A, "h", rnd);
  const d = T.replaceModel(c, B, "h", rnd);
  assert.deepEqual(d.unplaced.map(i => i.appearance).sort(), ["milk", "tofu"]);
});

test("a model change survives the storage round trip", () => {
  const st = new Mem();
  const a = {...T.newTwin(A, "h", rnd), unplaced: [thing("eggs", {count: 6, label: "계란"})]};
  assert.equal(T.commit(st, T.KEY, a).ok, true);
  const b = T.replaceModel(JSON.parse(st.getItem(T.KEY)), B, "h", rnd);
  assert.equal(T.commit(st, T.KEY, b).ok, true);
  assert.deepEqual(JSON.parse(st.getItem(T.KEY)).unplaced, a.unplaced);
});

// ---- finding 2: answers are bound to fridge, holder and layout revision ----
test("an answer asked for one fridge is refused by another with the same holder ids", () => {
  const a = T.newTwin(A, "h", rnd);
  const t = T.ticket(a, "cold/L0");
  const b = T.replaceModel(a, A, "h", rnd);  // same model again: same ids, new fridge
  assert.equal(T.addItems(b, t, [thing("milk")]).error, "other_fridge");
});

test("an answer for a re-traced compartment or a removed level is refused", () => {
  const a = T.newTwin(A, "h", rnd);
  const t0 = T.ticket(a, "cold/L0"), t4 = T.ticket(a, "cold/L4");
  const {next} = T.applyTrace(a, "cold", [0.2, 0.4, 0.6]);  // 4 levels: one retires
  assert.equal(T.addItems(next, t0, [thing("x")]).error, "layout_changed");
  const gone = Object.entries(next.levels).find(([, l]) => l.retired)[0];
  assert.equal(T.addItems(next, T.ticket(a, gone), [thing("x")]).error, "level_gone");
  assert.ok(t4);
});

test("a newer photo for the same holder makes the older reply stale (operation tickets)", () => {
  const ops = new T.Ops();
  const first = ops.start("fill"), second = ops.start("fill");
  assert.equal(ops.live(first), false);
  assert.equal(ops.live(second), true);
});

test("choosing to trace unstraightened makes a pending straighten stale; a model change cancels everything", () => {
  const ops = new T.Ops();
  const warp = ops.start("trace");
  const fallback = ops.start("trace");
  assert.equal(ops.live(warp), false);
  const fill = ops.start("fill");
  ops.cancel();
  assert.equal(ops.live(fallback) || ops.live(fill), false);
});

test("a valid answer appends and never removes", () => {
  const a = {...T.newTwin(A, "h", rnd), items: {"cold/L0": [thing("milk")]}};
  const {next} = T.addItems(a, T.ticket(a, "cold/L0"), [thing("jam")]);
  assert.deepEqual(next.items["cold/L0"].map(i => i.appearance), ["milk", "jam"]);
});

// ---- finding 3: no invented counts ----
test("counts: blank stays unknown, whole numbers pass, the rest is refused", () => {
  assert.deepEqual(T.parseCount(""), {ok: true, value: null});
  assert.deepEqual(T.parseCount(null), {ok: true, value: null});
  assert.deepEqual(T.parseCount(" 12 "), {ok: true, value: 12});
  for (const bad of ["1.5", "abc", "0", "-2", "1e3", "١"]) assert.equal(T.parseCount(bad).ok, false, bad);
});

// ---- finding 4: Unplaced can be put back ----
test("an Unplaced thing is placed on a live level in one change, keeping its values", () => {
  const a = {...T.newTwin(A, "h", rnd), unplaced: [thing("eggs", {count: 6, was: "cold/L1", source: "abc"})]};
  const {next} = T.placeUnplaced(a, 0, "cold/L2", {label: "계란"});
  assert.equal(next.unplaced.length, 0);
  assert.deepEqual(next.items["cold/L2"][0], {appearance: "eggs", label: "계란", count: 6, source: "abc", from_unplaced: "cold/L1"});
});

test("an Unplaced thing is not placed on a retired level, and a refused save keeps it in Unplaced", () => {
  const a = {...T.newTwin(A, "h", rnd), unplaced: [thing("eggs")]};
  const {next: traced} = T.applyTrace(a, "cold", [0.5]);
  const gone = Object.entries(traced.levels).find(([, l]) => l.retired)[0];
  assert.equal(T.placeUnplaced(traced, 0, gone).error, "level_gone");
  const st = new Mem();
  T.commit(st, T.KEY, traced);
  st.failSet = true;
  const {next} = T.placeUnplaced(traced, 0, "cold/L0");
  assert.equal(T.commit(st, T.KEY, next).ok, false);
  assert.equal(JSON.parse(st.m.get(T.KEY)).unplaced.length, 1);
});

// ---- finding 5: a save is believed only after read-back; a bad read-back is undone or reported ----
test("a refused write leaves storage unchanged and says so", () => {
  const st = new Mem(); const a = T.newTwin(A, "h", rnd);
  T.commit(st, T.KEY, a); const before = st.m.get(T.KEY);
  st.failSet = true;
  assert.deepEqual(T.commit(st, T.KEY, T.newTwin(B, "h", rnd)), {ok: false, durable: "unchanged"});
  assert.equal(st.m.get(T.KEY), before);
});

test("a write that lands but reads back wrong is restored", () => {
  const st = new Mem(); const a = T.newTwin(A, "h", rnd);
  T.commit(st, T.KEY, a); const before = st.m.get(T.KEY);
  st.lie = true;
  const r = T.commit(st, T.KEY, T.newTwin(B, "h", rnd));
  st.lie = false;
  assert.equal(r.ok, false);
  assert.equal(st.m.get(T.KEY), before);
});

test("a write that lands and cannot be undone is reported as unknown", () => {
  const st = new Mem(); T.commit(st, T.KEY, T.newTwin(A, "h", rnd));
  st.lie = true; st.failRestore = true; st.sets = 0;
  assert.deepEqual(T.commit(st, T.KEY, T.newTwin(B, "h", rnd)), {ok: false, durable: "unknown"});
});

test("a read that throws after a landed write is restored or reported, never called unchanged", () => {
  const st = new Mem(); T.commit(st, T.KEY, T.newTwin(A, "h", rnd)); const before = st.m.get(T.KEY);
  const orig = st.setItem.bind(st);
  st.setItem = (k, v) => { orig(k, v); st.failGet = true; };  // the write lands, then reads fail
  const r = T.commit(st, T.KEY, T.newTwin(B, "h", rnd));
  st.failGet = false;
  assert.equal(r.ok, false);
  assert.notEqual(r.durable, "unchanged");
  assert.ok(r.durable === "unknown" || st.m.get(T.KEY) === before);
});

// ---- the trace rules (carried over from the page) ----
test("removing a line merges the two levels it divided; the loser's things go to Unplaced", () => {
  const a = {...T.newTwin(B, "h", rnd), items: {"cold/L0": [thing("top")], "cold/L1": [thing("eggs")], "cold/L4": [thing("veg")]}};
  const lines = T.liveLevels(a, "cold").slice(0, -1).map(([, l]) => l.floor).slice(1);
  const {next, moved} = T.applyTrace(a, "cold", lines);
  assert.equal(moved, 1);
  assert.deepEqual(next.unplaced.map(i => i.appearance + "@" + i.was), ["eggs@cold/L1"]);
  assert.deepEqual(next.items["cold/L0"].map(i => i.appearance), ["top"]);
  assert.deepEqual(next.items["cold/L4"].map(i => i.appearance), ["veg"]);
});

test("added levels get ids never used before", () => {
  const a = T.newTwin(A, "h", rnd);
  const {next} = T.applyTrace(a, "cold", [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]);
  const {next: again} = T.applyTrace(next, "cold", [0.5]);
  const {next: third} = T.applyTrace(again, "cold", [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]);
  const added = Object.keys(third.levels).filter(k => k.includes("/N"));
  assert.equal(new Set(added).size, added.length);
  assert.ok(added.length >= 3);
});

test("lines too close or outside are refused", () => {
  const a = T.newTwin(A, "h", rnd);
  assert.equal(T.applyTrace(a, "cold", [0.5, 0.51]).error, "lines_too_close");
  assert.equal(T.applyTrace(a, "cold", [1.2]).error, "line_outside");
});

// ---- outline geometry ----
const Q = [[100, 120], [900, 80], [950, 1400], [60, 1350]];

test("the unit square's corners land on the person's corners", () => {
  const m = T.squareToQuad(Q);
  [[0, 0], [1, 0], [1, 1], [0, 1]].forEach((p, i) => {
    const [x, y] = T.applyH(m, p);
    assert.ok(Math.abs(x - Q[i][0]) < 1e-6 && Math.abs(y - Q[i][1]) < 1e-6, `${p} -> ${x},${y}`);
  });
});

test("a point on the photo maps back to the height it was drawn at", () => {
  const m = T.squareToQuad(Q);
  for (const v of [0.1, 0.37, 0.8]) {
    const [a, b] = T.lineOnPhoto(m, v);
    const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    assert.ok(Math.abs(T.vAt(m, mid) - v) < 0.02, `${v}`);   // the chord's midpoint is near the line in perspective
    assert.ok(Math.abs(T.vAt(m, a) - v) < 1e-9);
  }
});

test("points outside the outline have no height, and a degenerate outline has no geometry", () => {
  const m = T.squareToQuad(Q);
  assert.equal(T.vAt(m, [5000, 700]), null);
  assert.equal(T.squareToQuad([[0, 0], [0, 0], [0, 0], [0, 0]]), null);
});

test("the starting lines are the boundaries between the template's levels", () => {
  const a = T.newTwin(A, "h", rnd);
  assert.deepEqual(T.levelLines(a, "cold").map(l => l.id), ["cold/L0", "cold/L1", "cold/L2", "cold/L3"]);
  assert.ok(T.levelLines(a, "cold").every(l => l.v > 0 && l.v < 1));
});

// ---- outline review R1: what step 2 shows is what Confirm saves; an unusable outline never reaches step 2 ----
test("the names shown for the spaces are the kinds Confirm will save, even when the count is unchanged", () => {
  const a = T.newTwin(A, "h", rnd);
  const same = T.levelLines(a, "cold").map(l => l.v);
  assert.deepEqual(T.traceNames(a, "cold", same), ["Shelf 1", "Shelf 2", "Shelf 3", "Drawer 1", "Drawer 2"]);
  const moved = [0.05, 0.10, 0.15, 0.20];  // five spaces again, but the drawers' bands no longer overlap them
  const names = T.traceNames(a, "cold", moved), res = T.applyTrace(a, "cold", moved);
  assert.deepEqual(names, T.liveLevels(res.next, "cold").map(([, l]) => l.kind === "drawer" ? "Drawer" : "Shelf")
    .map((k, i, all) => `${k} ${all.slice(0, i + 1).filter(x => x === k).length}`));
  assert.equal(T.traceNames(a, "cold", [0.5, 0.51]), null);  // a refused layout has no names to promise
});

test("a crossed, collapsed or out-of-order outline is unusable; a fair one is not", () => {
  assert.equal(T.outlineProblem(Q), null);
  assert.equal(T.outlineProblem([[100, 100], [900, 100], [100, 900], [900, 900]]), "not_convex");
  assert.equal(T.outlineProblem([[0, 0], [0, 0], [0, 0], [0, 0]]), "repeated_corner");
  assert.equal(T.outlineProblem([[100, 100], [100, 100], [900, 900], [100, 900]]), "repeated_corner");
  assert.equal(T.outlineProblem([[100, 100], [500, 100], [900, 100], [500, 100.5]]), "repeated_corner");
  assert.equal(T.outlineProblem([[900, 100], [100, 100], [100, 900], [900, 900]]), "not_ordered");  // mirrored
  assert.equal(T.outlineProblem([[100, 100], [900, NaN], [900, 900], [100, 900]]), "not_finite");
  assert.equal(T.squareToQuad([[100, 100], [900, 100], [100, 900], [900, 900]]), null);  // no drawing through it either
});

// ---- red team 10/23: an outline with a corner on the diagonal, or a sliver, is not drawable either ----
test("a corner pushed onto the diagonal (an angle near 180°) or a tiny outline is refused", () => {
  assert.equal(T.outlineProblem([[94, 125], [600, 800], [1082, 1443], [94, 1443]]), "not_convex");
  assert.equal(T.outlineProblem([[100, 100], [1000, 100], [1000, 110], [100, 110]], [1176, 1568]), "too_small");
  assert.equal(T.outlineProblem([[500, 700], [680, 700], [680, 900], [500, 900]], [1176, 1568]), "too_small");
  assert.equal(T.outlineProblem(Q, [1176, 1568]), null);
  assert.equal(T.outlineProblem([[94, 125], [1082, 125], [1082, 1443], [94, 1443]], [1176, 1568]), null);
});

// ---- red-team fixes R1: a saved twin is believed only if every part the page reads has its shape ----
test("only a well-formed twin is accepted from storage", () => {
  const a = T.newTwin(A, "h", rnd);
  a.items["cold/L0"] = [thing("a")];
  assert.equal(T.isTwin(a), true);
  const bad = f => { const t = JSON.parse(JSON.stringify(a)); f(t); return T.isTwin(t); };
  assert.equal(bad(t => { t.levels["cold/L0"] = null; }), false);
  assert.equal(bad(t => { t.levels["cold/L0"].top = "x"; }), false);
  assert.equal(bad(t => { delete t.levels["cold/L0"].comp; }), false);
  assert.equal(bad(t => { t.items["cold/L0"] = {}; }), false);
  assert.equal(bad(t => { t.items["cold/L0"] = [null]; }), false);
  assert.equal(bad(t => { t.unplaced = [3]; }), false);
  assert.equal(bad(t => { delete t.rev; }), false);
  assert.equal(bad(t => { t.v = 2; }), false);
  assert.equal(T.isTwin(null), false);
});

// rescan: an answer of "not here any more" moves things to Unplaced; the record only names things still there
test("things the person says are gone move to Unplaced with where they were, nothing else changes", () => {
  const row = {key: "k", version: 1, compartments: [{id: "c", levels: [{id: "c/1", kind: "shelf", top: 0, floor: 1}]}], panels: []};
  let tw = T.newTwin(row, "sha", () => 0.5);
  tw = T.addItems(tw, T.ticket(tw, "c/1"), [{appearance: "a", pid: "p:i1"}, {appearance: "b", pid: "p:i2"}]).next;
  const r = T.unplaceItems(tw, T.ticket(tw, "c/1"), ["p:i2"]);
  assert.equal(r.moved, 1);
  assert.deepEqual(r.next.items["c/1"].map(i => i.pid), ["p:i1"]);
  assert.deepEqual(r.next.unplaced.map(i => [i.pid, i.was]), [["p:i2", "c/1"]]);
  assert.ok(T.isTwin(r.next));
});

test("a gone answer for a re-traced holder is refused", () => {
  const row = {key: "k", version: 1, compartments: [{id: "c", levels: [{id: "c/1", kind: "shelf", top: 0, floor: 1}]}], panels: []};
  let tw = T.newTwin(row, "sha", () => 0.5);
  tw = T.addItems(tw, T.ticket(tw, "c/1"), [{appearance: "a", pid: "p:i1"}]).next;
  const t = T.ticket(tw, "c/1");
  tw = T.applyTrace(tw, "c", [0.5]).next;
  assert.equal(T.unplaceItems(tw, t, ["p:i1"]).error, "layout_changed");
});

test("a rescan record sends only things still on that holder, with a usable box, for this fridge", () => {
  const row = {key: "k", version: 1, compartments: [{id: "c", levels: [{id: "c/1", kind: "shelf", top: 0, floor: 1}]}], panels: []};
  let tw = T.newTwin(row, "sha", () => 0.5);
  tw = T.addItems(tw, T.ticket(tw, "c/1"), [{appearance: "a", pid: "p:i1"}, {appearance: "b", pid: "p:i2"}]).next;
  const rec = {twin: tw.id, level: "c/1", items: [{pid: "p:i1", box: [1, 2, 3, 4]}, {pid: "p:i2", box: [5, 5, 5, 9]},
                                                   {pid: "p:gone", box: [1, 1, 2, 2]}]};
  assert.deepEqual(T.rescanItems(tw, rec).map(i => i.pid), ["p:i1"]);
  assert.deepEqual(T.rescanItems(tw, {...rec, twin: "other"}), []);
});

// Codex R1 #3: a record's owner is taken when the photo is confirmed, never from the page's twin after an await
test("a rescan record's owner is fixed at confirm time and checked before writing", () => {
  const row = {key: "k", version: 1, compartments: [{id: "c", levels: [{id: "c/1", kind: "shelf", top: 0, floor: 1}]}], panels: []};
  const a = T.newTwin(row, "sha", () => 0.1), b = T.newTwin(row, "sha", () => 0.9);
  const owner = T.recordOwner(a, "c/1");
  assert.equal(owner.twin, a.id);
  assert.ok(T.ownerStill(a, owner));
  assert.ok(!T.ownerStill(b, owner), "a fridge switched during the save");
  const retraced = T.applyTrace(a, "c", [0.5]).next;
  assert.ok(!T.ownerStill(retraced, owner), "the holder's layout changed during the save");
});

// shelf crop: the person's two lines decide the strip that is read and compared
test("the crop strip is the band between the two lines plus a small margin, inside the photo", () => {
  const r = T.bandCrop(1000, 800, 0.30, 0.60);
  assert.deepEqual(r, {x: 0, y: Math.round(0.30 * 800 - 0.03 * 800), w: 1000, h: Math.round(0.33 * 800 + 0.03 * 800)});
  const edge = T.bandCrop(1000, 800, 0.01, 0.99);
  assert.ok(edge.y === 0 && edge.y + edge.h <= 800);
});

test("a band too thin to hold a shelf is refused, and the lines may come in either order", () => {
  assert.equal(T.bandCrop(1000, 800, 0.50, 0.55), null);
  assert.deepEqual(T.bandCrop(1000, 800, 0.60, 0.30), T.bandCrop(1000, 800, 0.30, 0.60));
});

test("moved things take their new place in the twin; other things and other holders are untouched", () => {
  const row = {key: "k", version: 1, compartments: [{id: "c", levels: [{id: "c/1", kind: "shelf", top: 0, floor: 1}]}], panels: []};
  let tw = T.newTwin(row, "sha", () => 0.5);
  tw = T.addItems(tw, T.ticket(tw, "c/1"), [{appearance: "a", pid: "p:i1", xFrac: 0.2}, {appearance: "b", pid: "p:i2", xFrac: 0.5}]).next;
  const r = T.setPlacement(tw, T.ticket(tw, "c/1"), {"p:i1": {xFrac: 0.8, wFrac: 0.1, hFrac: 0.4}, "p:nope": {xFrac: 0.1}});
  assert.deepEqual(r.next.items["c/1"].map(i => i.xFrac), [0.8, 0.5]);
  assert.equal(r.next.items["c/1"][0].hFrac, 0.4);
  assert.equal(r.moved, 1);
});

test("band steps: a slow older photo never replaces a newer step", async () => {
  const s = new T.BandSteps(), shown = [];
  let readyA, cur = "B";
  const a = s.open(() => new Promise(r => { readyA = r; }), () => cur === "A", st => shown.push(st.id));
  const b = s.open(async () => ({id: "B"}), () => cur === "B", st => shown.push(st.id));
  await new Promise(r => setTimeout(r, 0));
  readyA({id: "A"});
  assert.equal(await a, null);
  assert.deepEqual(shown, ["B"]);
  assert.equal(s.cur.id, "B");
  assert.ok(s.end("cropB"));
  assert.equal(await b, "cropB");
});

test("band steps: a late answer ends only its own step; a stale step's answer is dropped", async () => {
  const s = new T.BandSteps();
  let cur = "A";
  const a = s.open(async () => ({id: "A"}), () => cur === "A", () => {});
  await new Promise(r => setTimeout(r, 0));
  const stepA = s.cur;
  cur = "B";
  const b = s.open(async () => ({id: "B"}), () => cur === "B", () => {});
  assert.equal(await a, null);  // replaced
  await new Promise(r => setTimeout(r, 0));
  assert.equal(s.end("cropA", stepA), false);  // A's crop arrives late: B stays open
  assert.equal(s.cur.id, "B");
  cur = "C";  // B's pick went stale (closed, another fridge): its answer is dropped
  assert.ok(s.end("cropB"));
  assert.equal(await b, null);
  assert.equal(s.cur, null);
});

test("photo faces are looked up per shelf: a shared photo id on two shelves keeps each shelf's own photo and box", () => {
  const all = {"c/1": {twin: "t", photo: "A", items: [{pid: "s:1", box: [0, 0, 5, 5]}]},
               "c/2": {twin: "t", photo: "B", items: [{pid: "s:1", box: [9, 9, 20, 20]}]},
               "c/3": {twin: "other", photo: "C", items: [{pid: "s:9", box: [1, 1, 2, 2]}]}};
  const f = T.facesOf(all, "t");
  assert.deepEqual(f("c/1", "s:1"), {photo: "A", box: [0, 0, 5, 5]});
  assert.deepEqual(f("c/2", "s:1"), {photo: "B", box: [9, 9, 20, 20]});
  assert.equal(f("c/3", "s:9"), null);
});

test("forget removes this page's fridge and photos from the device, and nothing else", () => {
  const m = new Map([[T.KEY, "x"], [T.RESCAN_KEY, "y"], ["other.site", "z"]]);
  const st = {removeItem: k => m.delete(k), getItem: k => m.get(k) ?? null};
  T.forget(st);
  assert.deepEqual([...m.keys()], ["other.site"]);
});

test("forget says whether both keys are really gone; a refused or partial removal is not reported as done", () => {
  const mk = (failOn) => { const m = new Map([[T.KEY, "x"], [T.RESCAN_KEY, "y"]]);
    return {m, st: {removeItem: k => { if (k === failOn) throw new Error("denied"); m.delete(k); }, getItem: k => m.get(k) ?? null}}; };
  assert.equal(T.forget(mk(null).st).ok, true);
  for (const k of [T.KEY, T.RESCAN_KEY]) assert.equal(T.forget(mk(k).st).ok, false, k);
  assert.equal(T.forget(null).ok, false);
});

test("only one tab may write: the writer lock is taken if free, refused if another tab holds it, assumed without Web Locks", async () => {
  const locks = held => ({request: (name, opts, cb) => { assert.equal(opts.ifAvailable, true); const r = cb(held ? null : {name}); return Promise.resolve(r); }});
  assert.equal(await T.claimWriter(locks(false)), true);
  assert.equal(await T.claimWriter(locks(true)), false);
  assert.equal(await T.claimWriter(undefined), true);
});
