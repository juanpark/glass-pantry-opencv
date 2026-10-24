// "What changed?" made visible: the last photo above the new one, OpenCV's matched points joined by lines, then each
// thing boxed by what OpenCV found. Drawing only; the decision is the engine's (verifier/rescan.py).

export const COLOUR = {no_visible_change: "#2e8b57", possible_change: "#d98200", moved: "#9b59b6", cannot_compare: "#8a948e"};
const NEW = "#2f6fb3", GAP = 14;

/** Both photos at the same width, the old one on top. Sizes are [w, h] in each photo's own pixels. */
export function layout(oldSize, newSize, width) {
  const ko = width / oldSize[0], kn = width / newSize[0], ho = Math.round(oldSize[1] * ko);
  return {width, height: ho + GAP + Math.round(newSize[1] * kn), old: {k: ko, y: 0, h: ho}, now: {k: kn, y: ho + GAP}};
}

/** One plain sentence of what OpenCV did, from the engine's answer. */
export function summary(res) {
  const items = res.items || [], n = o => items.filter(i => i.outcome === o).length;
  const al = (res.trace || []).find(s => s.step === "align") || {}, end = (res.trace || []).at(-1) || {};
  const parts = [[n("no_visible_change"), "still there"], [n("moved"), "moved"], [n("possible_change"), "not seen where it was"],
                 [n("cannot_compare"), "could not be checked"]].filter(([c]) => c).map(([c, t]) => `${c} ${t}`);
  const spots = (res.new || []).filter(s => s.kind === "new").length;
  const secs = Number.isFinite(end.ms) ? ` in ${(end.ms / 1000).toFixed(1)} s` : "";
  if (!al.ok) return "OpenCV could not line these two photos up, so it compared nothing.";
  return `OpenCV matched ${al.inliers} points between the photos and checked ${items.length} thing(s)${secs}, with no AI: `
    + `${parts.join(", ") || "nothing to compare"}` + (spots ? `; ${spots} spot(s) look new.` : ".");
}

const ease = t => 1 - (1 - Math.min(1, Math.max(0, t))) ** 3;

/** Draw the comparison at progress t (0..1): lines grow first, then the boxes. */
export function draw(cv, oldImg, newImg, res, oldItems, t) {
  const fr = (res.trace || []).find(s => s.step === "frames"), al = (res.trace || []).find(s => s.step === "align") || {};
  const newSize = fr ? fr.size : [newImg.naturalWidth, newImg.naturalHeight];
  const L = layout([oldImg.naturalWidth, oldImg.naturalHeight], newSize, cv.width);
  if (cv.height !== L.height) cv.height = L.height;
  const x = cv.getContext("2d"), lw = Math.max(2, cv.width / 400);
  x.clearRect(0, 0, cv.width, cv.height);
  x.drawImage(oldImg, 0, 0, cv.width, L.old.h);
  x.drawImage(newImg, 0, L.now.y, cv.width, newSize[1] * L.now.k);
  const box = (b, k, y0, colour, dash) => {
    x.setLineDash(dash ? [lw * 3, lw * 2] : []); x.strokeStyle = colour; x.lineWidth = lw * 1.6;
    x.strokeRect(b[0] * k, y0 + b[1] * k, (b[2] - b[0]) * k, (b[3] - b[1]) * k);
  };
  // the lines: each one joins a point to the same point in the other photo; they grow in from left to right
  const pairs = [...(al.pairs || [])].sort((a, b) => a[0] - b[0]), grow = ease(t / 0.6);
  x.setLineDash([]);
  const dim = t >= 0.6 ? 1 - 0.55 * ease((t - 0.6) / 0.4) : 1;  // the lines step back once the boxes come in
  pairs.forEach(([xo, yo, xn, yn], i) => {
    const local = Math.min(1, Math.max(0, grow * pairs.length - i));
    if (!local) return;
    const ax = xo * L.old.k, ay = yo * L.old.k, bx = xn * L.now.k, by = L.now.y + yn * L.now.k;
    const hue = Math.round(360 * i / pairs.length), ex = ax + (bx - ax) * local, ey = ay + (by - ay) * local;
    x.globalAlpha = dim; x.lineWidth = lw * 1.1; x.strokeStyle = `hsl(${hue} 85% 55%)`; x.fillStyle = x.strokeStyle;
    x.beginPath(); x.moveTo(ax, ay); x.lineTo(ex, ey); x.stroke();
    x.beginPath(); x.arc(ax, ay, lw * 1.8, 0, 7); x.fill();
    if (local >= 1) { x.beginPath(); x.arc(bx, by, lw * 1.8, 0, 7); x.fill(); }
  });
  x.globalAlpha = 1;
  if (t < 0.6) return;
  x.globalAlpha = ease((t - 0.6) / 0.4);
  const was = new Map((oldItems || []).map(i => [i.pid, i.box]));
  for (const o of res.items || []) {
    const c = COLOUR[o.outcome] || "#888";
    if (was.has(o.id)) box(was.get(o.id), L.old.k, 0, c, false);
    if (o.box_now) box(o.box_now, L.now.k, L.now.y, c, o.outcome === "possible_change");  // dashed: not seen there
  }
  for (const s of res.new || []) if (s.kind === "new") box(s.rect, L.now.k, L.now.y, NEW, true);  // changed spots are the amber boxes
  x.globalAlpha = 1; x.setLineDash([]);
}
