// node --test tests/js/   (plan v4 slice 5: the twin as shapes to draw)
import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import path from "node:path";
import * as T from "../../web/twin.js";
import {sceneOf, family} from "../../web/scene.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROWS = JSON.parse(readFileSync(path.join(here, "../../web/layouts/layouts.json"), "utf8"));
const A = ROWS.find(r => r.key === "model:samsung-rb38j-bottom");
const fresh = () => T.newTwin(A, "h", () => 0.5);
const inside = (b, o) => b[0] >= o[0] - 1e-6 && b[1] >= o[1] - 1e-6 && b[2] >= o[2] - 1e-6 &&
  b[0] + b[3] <= o[0] + o[3] + 1e-6 && b[1] + b[4] <= o[1] + o[4] + 1e-6 && b[2] + b[5] <= o[2] + o[5] + 1e-6;

test("the template draws one plate or drawer per live level, inside its compartment, top to bottom", () => {
  const s = sceneOf(fresh(), A);
  const cold = s.parts.find(p => p.kind === "compartment" && p.id === "cold");
  const lv = s.parts.filter(p => (p.kind === "shelf" || p.kind === "drawer") && p.level.startsWith("cold/"));
  assert.deepEqual(lv.map(p => p.kind), ["shelf", "shelf", "shelf", "drawer", "drawer"]);
  assert.ok(lv.every(p => inside(p.box, cold.box)));
  const ys = lv.map(p => p.box[1]);
  assert.deepEqual([...ys].sort((a, b) => b - a), ys);
});

test("a traced line moves its plate; a retired level is not drawn", () => {
  const a = fresh();
  const y0 = sceneOf(a, A).parts.find(p => p.level === "cold/L0" && p.kind === "shelf").box[1];
  const {next} = T.applyTrace(a, "cold", [0.1, 0.4, 0.6, 0.8]);
  const y1 = sceneOf(next, A).parts.find(p => p.level === "cold/L0" && p.kind === "shelf").box[1];
  assert.ok(y1 > y0, `${y1} > ${y0}`);  // a line nearer the top raises the plate
  const {next: merged} = T.applyTrace(a, "cold", [0.2, 0.4, 0.6]);
  const retired = Object.entries(merged.levels).filter(([, l]) => l.retired).map(([id]) => id);
  assert.ok(retired.length === 1 && !sceneOf(merged, A).parts.some(p => p.level === retired[0]));
});

test("items stand on their level, inside the walls, never taller than the level", () => {
  const a = fresh();
  a.items["cold/L0"] = [{appearance: "병", label: "들기름", vessel: "soju_bottle", xFrac: 0.99, wFrac: 0.9, hFrac: 3},
                        {appearance: "통", label: null, count: 3}, {appearance: "계란판", vessel: "tray", xFrac: -1}];
  a.unplaced = [{appearance: "lost"}];
  const s = sceneOf(a, A), cold = s.parts.find(p => p.id === "cold");
  const items = s.parts.filter(p => p.kind === "item");
  assert.equal(items.length, 3);  // Unplaced is not drawn
  const shelf = s.parts.find(p => p.level === "cold/L0" && p.kind === "shelf");
  for (const it of items) {
    assert.ok(inside(it.box, cold.box), JSON.stringify(it.box));
    assert.ok(Math.abs(it.box[1] - (shelf.box[1] + 3 + 3)) < 1e-6);
  }
  assert.equal(items[0].shape, "cyl");
  assert.equal(items[1].label, "통 ×3");
  assert.equal(items[0].label, "들기름");
});

test("vessel words map to basic families", () => {
  assert.equal(family("soju_bottle"), "bottle");
  assert.equal(family("milk_carton"), "carton");
  assert.equal(family(undefined), "other");
  assert.equal(family("spaceship"), "other");
});

test("drawing never changes the twin", () => {
  const a = fresh(), before = JSON.stringify(a);
  sceneOf(a, A);
  assert.equal(JSON.stringify(a), before);
});

// ---- Codex R1 ----
import {cameraFor} from "../../web/scene.js";
const live = t => Object.entries(t.levels).filter(([, l]) => l.comp && !l.retired).map(([id]) => id).sort();

test("every live compartment level is drawn exactly once, on every catalogue layout and after tracing", () => {
  for (const r of ROWS) {
    const a = T.newTwin(r, "h", () => 0.5);
    const drawn = sceneOf(a, r).parts.filter(p => p.kind === "shelf" || p.kind === "drawer").map(p => p.level).sort();
    assert.deepEqual(drawn, live(a), r.key);
  }
  const t = T.applyTrace(fresh(), "cold", [0.01, 0.2, 0.4, 0.6]).next;
  assert.deepEqual(sceneOf(t, A).parts.filter(p => p.kind === "shelf" || p.kind === "drawer").map(p => p.level).sort(), live(t));
});

test("plates stay inside their compartment, items inside their own level, even in thin first and last bands", () => {
  const t = T.applyTrace(fresh(), "cold", [0.01, 0.2, 0.4, 0.99]).next;
  for (const id of live(t)) t.items[id] = [{appearance: "tall", hFrac: 1, wFrac: 1}, {appearance: "x"}];
  const s = sceneOf(t, A), cold = s.parts.find(p => p.id === "cold");
  const y0 = cold.box[1], ch = cold.box[4];
  for (const p of s.parts.filter(p => p.level && p.level.startsWith("cold/"))) {
    assert.ok(inside(p.box, cold.box), `${p.kind} ${p.level} ${p.box}`);
    if (p.kind !== "item") continue;
    const l = t.levels[p.level], floor = y0 + (1 - l.floor) * ch, top = y0 + (1 - l.top) * ch;
    assert.ok(p.box[1] >= floor - 1e-6 && p.box[1] + p.box[4] <= top + 1e-6, `${p.level} ${p.box[1]}+${p.box[4]} in [${floor}, ${top}]`);
  }
});

function project(cam, p) {
  const sub = (a, b) => a.map((v, i) => v - b[i]), dot = (a, b) => a.reduce((s, v, i) => s + v * b[i], 0);
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const norm = a => a.map(v => v / Math.hypot(...a));
  const f = norm(sub(cam.target, cam.position)), r = norm(cross(f, [0, 1, 0])), u = cross(r, f), d = sub(p, cam.position);
  const tv = Math.tan(cam.fov * Math.PI / 360), th = tv * cam.aspect;
  return [dot(d, r) / (dot(d, f) * th), dot(d, u) / (dot(d, f) * tv)];
}

test("the starting camera shows the whole cabinet, portrait phone and desktop, for every layout", () => {
  for (const r of ROWS) for (const aspect of [324 / 560, 946 / 560, 0.4]) {
    const [W, H, D] = r.mm, cam = {...cameraFor({w: W, h: H, d: D}, aspect), aspect};
    for (const x of [-W / 2, W / 2]) for (const y of [0, H]) for (const z of [-D / 2, D / 2]) {
      const [nx, ny] = project(cam, [x, y, z]);
      assert.ok(Math.abs(nx) <= 1 && Math.abs(ny) <= 1, `${r.key} @${aspect.toFixed(2)}: ${nx.toFixed(2)}, ${ny.toFixed(2)}`);
    }
  }
});

test("the box around a level holds its plate and its things, and the camera can be aimed at it", async () => {
  const {levelBox, cameraFor: cam} = await import("../../web/scene.js");
  const parts = [{level: "L", kind: "shelf", box: [-300, 400, -200, 600, 6, 400]},
                 {level: "L", kind: "item", box: [-100, 406, -50, 80, 200, 80]},
                 {level: "M", kind: "item", box: [0, 900, 0, 80, 200, 80]}];
  const b = levelBox(parts, "L");
  assert.deepEqual(b.at, [0, 503, 0]); assert.equal(b.w, 600); assert.equal(b.h, 206);
  assert.equal(levelBox(parts, "none"), null);
  assert.deepEqual(cam(b, 1, 35, b.at).target, b.at);
});

test("the shown change is scoped to the shelf that changed; unidentified or other-shelf rows never animate", async () => {
  const {changeOf} = await import("../../web/scene.js");
  const P = (level, pid, x) => ({kind: "item", level, pid, box: [x, 0, 0, 10, 10, 10]});
  const before = [P("A", "s:1", 0), P("A", "s:2", 50), P("B", "s:1", 0), P("B", undefined, 90)];
  const after = [P("A", "s:1", 30), P("A", "s:3", 80), P("B", "s:1", 0), P("B", undefined, 90)];
  const c = changeOf(before, after, "A");
  assert.deepEqual(c.moved.map(m => m.pid), ["s:1"]);
  assert.deepEqual(c.added, ["s:3"]);
  assert.deepEqual(c.gone.map(p => p.pid), ["s:2"]);
  // shelf B's unchanged rows (one with no pid, one sharing A's photo id) are not part of the change
  const all = [...c.moved.map(m => m.pid), ...c.added, ...c.gone.map(p => p.pid)];
  assert.equal(all.length, 3);
});

test("a tap picks the first hit that is still shown, skipping faded-out things", async () => {
  const {firstShown} = await import("../../web/scene.js");
  const gone = {visible: false, parent: null}, live = {visible: true, parent: null};
  const hits = [{object: {isMesh: true, visible: true, parent: gone}}, {object: {isMesh: true, visible: true, parent: live}}];
  assert.equal(firstShown(hits), hits[1]);
  assert.equal(firstShown([hits[0]]), undefined);
});

test("a reading matches the library by its longest word, ties on key; a match is drawn at the item's real size", async () => {
  const {matchItem, sceneOf: draw} = await import("../../web/scene.js");
  const lib = [{key: "coke_500", match: ["콜라", "코카콜라"], mm: [65, 220, 65]},
               {key: "coke_1500", match: ["콜라 1.5", "콜라1.5"], mm: [90, 320, 90]},
               {key: "ssamjang_450", match: ["쌈장"], mm: [120, 90, 90]}];
  assert.equal(matchItem("코카콜라 1.5L", lib).key, "coke_1500");  // "콜라 1.5" is longer than "코카콜라"
  assert.equal(matchItem("코카콜라", lib).key, "coke_500");
  assert.equal(matchItem("순창 양념듬뿍 쌈장", lib).key, "ssamjang_450");
  assert.equal(matchItem("흰 비닐봉지", lib), null);
  const t = fresh(); const lid = Object.keys(t.levels)[0];
  t.items[lid] = [{pid: "p1", label: "순창 양념듬뿍 쌈장", vessel: "tub", count: 1}, {pid: "p2", label: "흰 비닐봉지", count: 1}];
  const items = draw(t, A, lib).parts.filter(p => p.kind === "item");
  assert.equal(items[0].model, "ssamjang_450");
  assert.deepEqual(items[0].box.slice(3).map(Math.round), [120, 90, 90]);
  assert.equal(items[1].model, undefined);
});

test("a thing lower in its shelf photo stands further forward", () => {
  const t = fresh(); const lid = Object.keys(t.levels)[0];
  t.items[lid] = [{pid: "back", appearance: "x", xFrac: 0.3, yFrac: 0.5}, {pid: "front", appearance: "y", xFrac: 0.7, yFrac: 0.98}];
  const [b, f] = sceneOf(t, A).parts.filter(p => p.kind === "item");
  assert.ok(f.box[2] > b.box[2] + 50, [b.box[2], f.box[2]]);
});

test("a fade multiplies each material's own opacity, so see-through parts stay see-through and instances fade alone", async () => {
  const {setFade} = await import("../../web/scene.js");
  const mat = o => ({opacity: o, transparent: o < 1, userData: {}});
  const a = {children: [{material: mat(0.1), children: []}, {material: [mat(1), mat(1)], children: []}]};
  const b = {children: [{material: mat(0.1), children: []}]};
  setFade(a, 1); setFade(b, 1);
  assert.deepEqual([a.children[0].material.opacity, a.children[1].material[0].opacity], [0.1, 1]);
  setFade(a, 0.5);
  assert.ok(Math.abs(a.children[0].material.opacity - 0.05) < 1e-9 && a.children[1].material[1].opacity === 0.5);
  assert.equal(b.children[0].material.opacity, 0.1);
  setFade(a, 1);
  assert.equal(a.children[0].material.opacity, 0.1);
});
