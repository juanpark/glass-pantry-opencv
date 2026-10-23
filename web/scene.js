// The twin as a list of shapes to draw (plan v4 slice 5, I-68). Pure: no three.js, no page, never changes the twin.
// The tree says where things are; this says how they look, and may be approximate and thrown away.
// Units: millimetres. Origin: the cabinet's floor centre; x right, y up, z towards the person (front = +z).

const WALL = 40, DOOR_ZONE = 60;  // approximate wall thickness and the space the door's bins take, mm

// a basic family per vessel word, as width : height : depth (the scan's words are richer: "soju_bottle")
export const FAMILIES = {
  bottle: ["cyl", 0.35, 1, 0.35], can: ["cyl", 0.6, 1, 0.6], jar: ["cyl", 0.8, 1, 0.8], carton: ["box", 0.6, 1, 0.6],
  tub: ["cyl", 1, 0.6, 1], tray: ["box", 1, 0.25, 0.8], pouch: ["box", 0.8, 1, 0.25], bag: ["box", 0.9, 0.7, 0.5],
  box: ["box", 1, 0.7, 0.8], other: ["box", 1, 0.8, 0.8]};
export const family = v => Object.keys(FAMILIES).find(f => f !== "other" && String(v || "").includes(f)) || "other";

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

export function sceneOf(twin, row) {
  const [W, H, D] = row.mm;
  const iw = W - 2 * WALL, ih = H - 2 * WALL, id = D - WALL - DOOR_ZONE;
  const at = (fx, fy, fz) => [-iw / 2 + fx * iw, WALL + fy * ih, -D / 2 + WALL + fz * id];
  const parts = [];
  for (const c of row.compartments) {
    const [bx, by, bz, bw, bh, bd] = c.box;
    const [x0, y0, z0] = at(bx, by, bz), [x1, y1, z1] = at(bx + bw, by + bh, bz + bd);
    const cw = x1 - x0, ch = y1 - y0, cd = z1 - z0;
    parts.push({kind: "compartment", id: c.id, cold: c.kind !== "freezer", box: [x0, y0, z0, cw, ch, cd]});
    const levels = Object.entries(twin.levels).filter(([, l]) => l.comp === c.id && !l.retired)
      .sort((a, b) => a[1].top - b[1].top);
    for (const [lid, l] of levels) {
      const floor = y0 + (1 - l.floor) * ch, top = y0 + (1 - l.top) * ch, lh = top - floor;
      if (l.kind === "drawer") parts.push({kind: "drawer", level: lid, box: [x0 + 10, floor, z0 + 10, cw - 20, lh * 0.85, cd - 20]});
      else if (l.floor < 0.999) parts.push({kind: "shelf", level: lid, box: [x0, floor - 3, z0, cw, 6, cd]});
      const its = twin.items[lid] || [];
      its.forEach((it, i) => {
        const [shape, sw, sh, sd] = FAMILIES[family(it.vessel)];
        const h = clamp((it.hFrac || 0.45) * lh, Math.min(30, lh * 0.8), lh * 0.8);
        const w = clamp(it.wFrac ? it.wFrac * cw : h * sw / sh, 25, cw / 2);
        const d = Math.min(cd - 20, w * sd / sw);
        const fx = Number.isFinite(it.xFrac) ? clamp(it.xFrac, 0, 1) : (its.length > 1 ? 0.12 + 0.76 * i / (its.length - 1) : 0.5);
        const cx = clamp(x0 + fx * cw, x0 + w / 2, x1 - w / 2);
        parts.push({kind: "item", level: lid, shape, label: `${it.label || it.appearance}${it.count > 1 ? " ×" + it.count : ""}`,
                    box: [cx - w / 2, floor + 3, clamp(z0 + cd / 2 + 40 - d / 2, z0, z1 - d), w, h, d]});  // a little forward
      });
    }
  }
  return {cabinet: {w: W, h: H, d: D}, parts};
}
