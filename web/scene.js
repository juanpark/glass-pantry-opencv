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

/** The library item a reading names, as the phone app picks it (object_catalog.dart specFor): the longest match word
 * found in the text wins, ties on key; null when nothing matches. */
export function matchItem(text, lib) {
  const hay = String(text || "").toLowerCase();
  let best = null, len = 0;
  for (const it of lib || []) for (const m of it.match) {
    if (m.length < 2 || !hay.includes(m.toLowerCase())) continue;
    if (m.length > len || (m.length === len && it.key < best.key)) { best = it; len = m.length; }
  }
  return best;
}

export function sceneOf(twin, row, lib = null) {
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
      const plate = Math.min(6, lh * 0.2);  // a glass plate, thinner in a thin band; the compartment floor is a plate too
      if (l.kind === "drawer") parts.push({kind: "drawer", level: lid, box: [x0 + 10, floor, z0 + 10, cw - 20, lh * 0.85, cd - 20]});
      else parts.push({kind: "shelf", level: lid, box: [x0, floor, z0, cw, plate, cd]});
      const base = floor + plate, room = (top - base) * 0.9;  // items stand on the plate and stay under the next one
      const its = twin.items[lid] || [];
      its.forEach((it, i) => {
        const [shape, sw, sh, sd] = FAMILIES[family(it.vessel)];
        const lm = matchItem(`${it.label || ""} ${it.appearance || ""}`, lib);
        let h = clamp((it.hFrac || 0.45) * lh, Math.min(30, room), room);
        let w = clamp(it.wFrac ? it.wFrac * cw : h * sw / sh, 25, cw / 2);
        let d = Math.min(cd - 20, w * sd / sw);
        if (lm) {  // a library model at its real size, made smaller only if the shelf cannot hold it
          const k = Math.min(1, room / lm.mm[1], cw / 2 / lm.mm[0], (cd - 20) / lm.mm[2]);
          [w, h, d] = lm.mm.map(v => v * k);
        }
        const fx = Number.isFinite(it.xFrac) ? clamp(it.xFrac, 0, 1) : (its.length > 1 ? 0.12 + 0.76 * i / (its.length - 1) : 0.5);
        const cx = clamp(x0 + fx * cw, x0 + w / 2, x1 - w / 2);
        // depth from where its foot stands in the photo: lower in the shelf strip is nearer the front (approximate)
        const z = Number.isFinite(it.yFrac) ? z0 + 10 + clamp((it.yFrac - 0.4) / 0.6, 0, 1) * Math.max(0, cd - d - 20)
          : clamp(z0 + cd / 2 + 40 - d / 2, z0, z1 - d);  // a little forward
        parts.push({kind: "item", level: lid, pid: it.pid, shape, ...(lm ? {model: lm.key} : {}), label: `${it.label || it.appearance}${it.count > 1 ? " ×" + it.count : ""}`,
                    box: [cx - w / 2, base, z, w, h, d]});
      });
    }
  }
  return {cabinet: {w: W, h: H, d: D}, parts};
}

/** Where the camera starts: a three-quarter view from the front right, far enough that the cabinet's bounding sphere
 * fits both the vertical and the horizontal field of view at this aspect (width / height). */
export function cameraFor({w, h, d}, aspect, fov = 35, at = null) {
  const vf = fov * Math.PI / 180, hf = 2 * Math.atan(Math.tan(vf / 2) * aspect);
  const radius = Math.hypot(w, h, d) / 2, dist = radius / Math.sin(Math.min(vf, hf) / 2) * 1.02;
  const dir = [0.42, 0.18, 1], n = Math.hypot(...dir), target = at || [0, h / 2, 0];
  return {fov, target, position: dir.map((v, i) => target[i] + v / n * dist)};
}

/** What changed on one shelf between two drawings: things there before and after (by pid) that moved, things that
 * arrived, and things that left. Only that shelf, and only rows with a pid, so nothing elsewhere is shown as changed. */
export function changeOf(beforeParts, afterParts, level) {
  const on = ps => new Map(ps.filter(p => p.kind === "item" && p.level === level && p.pid).map(p => [p.pid, p]));
  const a = on(beforeParts), b = on(afterParts);
  const moved = [], added = [], gone = [];
  for (const [pid, p] of b) {
    const q = a.get(pid);
    if (!q) added.push(pid);
    else if (q.box.some((v, i) => Math.abs(v - p.box[i]) > 1)) moved.push({pid, from: q.box, to: p.box});
  }
  for (const [pid, q] of a) if (!b.has(pid)) gone.push(q);
  return {moved, added, gone};
}

/** The first ray hit whose object and every parent are shown: a faded-out thing never takes a tap. */
export function firstShown(hits) {
  return hits.find(h => { if (!h.object.isMesh) return false; for (let o = h.object; o; o = o.parent) if (!o.visible) return false; return true; });
}

/** The box around one level: its plate or drawer and everything standing on it, up to the level above. For framing
 * the camera on the shelf that just changed. Returns {at: centre, w, h, d} or null. */
export function levelBox(parts, level) {
  const own = parts.filter(p => p.level === level);
  if (!own.length) return null;
  const lo = [0, 1, 2].map(i => Math.min(...own.map(p => p.box[i])));
  const hi = [0, 1, 2].map(i => Math.max(...own.map(p => p.box[i] + p.box[i + 3])));
  const [w, h, d] = [0, 1, 2].map(i => hi[i] - lo[i]);
  return {at: [0, 1, 2].map(i => (lo[i] + hi[i]) / 2), w, h: Math.max(h, 120), d};
}

/** Fade a drawn thing to f (0..1): each material keeps its own opacity as the base, so see-through parts of a model stay
 * see-through. Works on any tree of {material, children}. */
export function setFade(root, f) {
  const walk = o => {
    for (const m of [o.material].flat()) if (m) {
      m.userData.base ??= m.opacity;
      m.opacity = m.userData.base * f; m.transparent = m.opacity < 1 || m.userData.base < 1;
    }
    for (const c of o.children || []) walk(c);
  };
  walk(root);
}
