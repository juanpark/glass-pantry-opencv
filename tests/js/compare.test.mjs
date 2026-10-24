import {test} from "node:test";
import assert from "node:assert/strict";
import {layout, summary} from "../../web/compare.js";

test("both photos share the width, the old one on top with a gap", () => {
  const L = layout([1568, 400], [3136, 800], 784);
  assert.equal(L.old.k, 0.5); assert.equal(L.old.h, 200);
  assert.equal(L.now.k, 0.25); assert.ok(L.now.y > 200);
  assert.equal(L.height, L.now.y + 200);
});

const trace = (ok, ms = 4400) => [{step: "frames", size: [100, 50]}, {step: "align", ok, inliers: 312, pairs: []}, {step: "decide", ms}];

test("the sentence counts what OpenCV found, without the AI", () => {
  const s = summary({trace: trace(true), items: [{outcome: "no_visible_change"}, {outcome: "no_visible_change"},
    {outcome: "moved"}, {outcome: "possible_change"}], new: [{kind: "new"}, {kind: "changed"}]});
  assert.equal(s, "OpenCV matched 312 points between the photos and checked 4 thing(s) in 4.4 s, with no AI: "
    + "2 still there, 1 moved, 1 not seen where it was; 1 spot(s) look new.");
});

test("photos that did not line up claim nothing", () => {
  assert.match(summary({trace: trace(false), items: [{outcome: "cannot_compare"}]}), /compared nothing/);
});
