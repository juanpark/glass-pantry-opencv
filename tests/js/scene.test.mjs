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
