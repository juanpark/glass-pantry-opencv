"""Hand truth for step 3 (plan v4 R3, R2-3), recorded BEFORE any engine output on these photos is looked at.

    uv run python tools/annotate_trace.py PHOTO_DIR OUT.json COMP_MAP.json [--port 8767]

For each compartment photo: (a) are all four corners of the opening visible? if yes, click them (top-left, top-right,
bottom-right, bottom-left); (b) on the photo straightened with YOUR corners, click every visible shelf or drawer edge
(lines missing from the catalogue template included); (c) mark each template level visible / hidden. Coordinates are
the canonical 1568 px frame's pixels, the frame the engine uses. Local only; nothing leaves this machine.
"""

import argparse
import base64
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from verifier import frames, opening  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("photos")
ap.add_argument("out")
ap.add_argument("comps", help='JSON {"IMG_8711": {"comp": "cold"}, ...} (notes.json "compartments")')
ap.add_argument("--port", type=int, default=8767)
ap.add_argument("--model", default="model:samsung-rb38j-bottom")
a = ap.parse_args()

notes = json.loads(Path(a.comps).read_text())
comps = notes.get("compartments", notes)
row = next(r for r in json.loads((ROOT / "web/layouts/layouts.json").read_text()) if r["key"] == a.model)
levels = {c["id"]: [f'{l["kind"]} {sum(m["kind"] == l["kind"] for m in c["levels"][:i + 1])}' for i, l in enumerate(c["levels"])]
          for c in row["compartments"]}  # "shelf 1, shelf 2, shelf 3, drawer 1, drawer 2", top to bottom
out = Path(a.out)
truth = json.loads(out.read_text()) if out.exists() else {}
canon = {}
for name in comps:
    f = frames.canonical((Path(a.photos) / f"{name}.jpg").read_bytes())
    canon[name] = f

PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Trace truth</title>
<style>body{font:15px system-ui;margin:16px;max-width:1000px}canvas{max-width:100%;border:1px solid #ccc;cursor:crosshair}
button{font:600 14px system-ui;padding:8px 12px;margin:4px}.q{margin:10px 0}.done{color:#2e8b57}</style>
<h2 id=title></h2><p id=step></p><div class=q id=ctl></div><canvas id=cv></canvas><p id=msg></p>
<script>
let S, i = 0, cur = {};
const $ = s => document.querySelector(s);
async function boot(){ S = await (await fetch('state')).json(); show(); }
function show(){
  const n = S.names[i]; cur = S.truth[n] ? JSON.parse(JSON.stringify(S.truth[n])) : {};
  $('#title').textContent = `${i + 1} / ${S.names.length}: ${n} (${S.comps[n].comp}, ${S.comps[n].case || ''})` + (S.truth[n] ? ' ✓ saved' : '');
  askEligible(n);
}
function img(src, cb){ const im = new Image(); im.onload = () => cb(im); im.src = src; }
function nav(){ return `<button onclick="go(-1)">← Back</button><button onclick="go(1)">Skip →</button>`; }
window.go = d => { i = Math.max(0, Math.min(S.names.length - 1, i + d)); show(); };
function askEligible(n){
  $('#step').textContent = 'Step 1: can you see all FOUR corners of the opening in this photo?';
  $('#ctl').innerHTML = `<button id=y>Yes, all four</button><button id=no>No</button>` + nav();
  img('photo/' + n, im => draw(im, []));
  $('#y').onclick = () => corners(n);
  $('#no').onclick = () => { cur = {eligible:false}; levelsVis(n, null); };
}
function draw(im, pts, lines){
  const cv = $('#cv'), c = cv.getContext('2d'); cv.width = im.naturalWidth; cv.height = im.naturalHeight; c.drawImage(im, 0, 0);
  c.fillStyle = '#e33'; c.strokeStyle = '#e33'; c.lineWidth = 4;
  pts.forEach(([x, y], k) => { c.beginPath(); c.arc(x, y, 12, 0, 7); c.fill(); c.font = '28px system-ui'; c.fillText(k + 1, x + 14, y - 14); });
  (lines || []).forEach(y => { c.beginPath(); c.moveTo(0, y * cv.height); c.lineTo(cv.width, y * cv.height); c.stroke(); });
}
function at(e){ const cv = $('#cv'), r = cv.getBoundingClientRect(); return [(e.clientX - r.left) * cv.width / r.width, (e.clientY - r.top) * cv.height / r.height]; }
function corners(n){
  const names = ['top-left', 'top-right', 'bottom-right', 'bottom-left'];
  const pts = [];
  $('#step').textContent = 'Step 2: click the corner of the opening: ' + names[0];
  $('#ctl').innerHTML = `<button id=undo>Undo last</button>` + nav();
  img('photo/' + n, im => {
    draw(im, pts);
    $('#undo').onclick = () => { pts.pop(); draw(im, pts); $('#step').textContent = 'Step 2: click the corner of the opening: ' + names[pts.length]; };
    $('#cv').onclick = async e => {
      if(pts.length >= 4) return;
      pts.push(at(e).map(v => Math.round(v * 10) / 10)); draw(im, pts);
      if(pts.length < 4){ $('#step').textContent = 'Step 2: click the corner of the opening: ' + names[pts.length]; return; }
      const r = await (await fetch('warp', {method:'POST', body:JSON.stringify({name:n, corners:pts})})).json();
      if(r.error){ $('#msg').textContent = 'Those corners cannot be straightened (' + r.error + '). Undo and try again, or Back and answer No.'; return; }
      cur = {eligible:true, corners:pts}; lines(n, r.image);
    };
  });
}
function lines(n, warped){
  const ys = [];
  $('#step').textContent = 'Step 3: click once on EVERY shelf or drawer edge you can see (the line between two spaces). Then Next.';
  $('#ctl').innerHTML = `<button id=undo>Undo last</button><button id=nx>Next</button>` + nav();
  img('data:image/jpeg;base64,' + warped, im => {
    draw(im, [], ys);
    $('#cv').onclick = e => { const [, y] = at(e); ys.push(Math.round(y / $('#cv').height * 1000) / 1000); draw(im, [], ys); };
    $('#undo').onclick = () => { ys.pop(); draw(im, [], ys); };
    $('#nx').onclick = () => { cur.lines = [...ys].sort((p, q) => p - q); levelsVis(n, im); };
  });
}
function levelsVis(n){
  const lv = S.levels[S.comps[n].comp] || [];
  $('#step').textContent = 'Step 4: for each space the catalogue expects (top to bottom), can you see it in the photo?';
  $('#ctl').innerHTML = lv.map((l, k) => `<div>${l}: <label><input type=radio name=l${k} value=visible checked> visible</label> <label><input type=radio name=l${k} value=hidden> hidden</label></div>`).join('')
    + `<button id=save>Save and next</button>` + nav();
  $('#cv').onclick = null;
  $('#save').onclick = async () => {
    cur.levels = lv.map((l, k) => ({level:l, seen:document.querySelector(`input[name=l${k}]:checked`).value}));
    await fetch('save', {method:'POST', body:JSON.stringify({name:n, truth:cur})});
    S.truth[n] = cur; $('#msg').textContent = 'Saved ' + n;
    if(i < S.names.length - 1){ i++; show(); } else $('#step').innerHTML = '<b class=done>All done. Tell Claude "trace truth done".</b>';
  };
}
boot();
</script>"""


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)).encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if self.path == "/state":
            return self._send(200, {"names": list(comps), "comps": comps, "levels": levels, "truth": truth})
        if self.path.startswith("/photo/"):
            return self._send(200, canon[self.path[7:]].jpeg, "image/jpeg")
        self._send(404, {"error": "not_found"})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["content-length"])))
        f = canon[req["name"]]
        if self.path == "/warp":
            # The truth is not held to the engine's thresholds: any four distinct points in click order are warped.
            q = np.array(req["corners"], np.float32)
            if len(q) != 4 or len({tuple(p) for p in q.tolist()}) < 4:
                return self._send(200, {"error": "need four different corners"})
            ow, oh = opening.out_size(q.astype(np.float64))
            m = cv2.getPerspectiveTransform(q, np.float32([[0, 0], [ow - 1, 0], [ow - 1, oh - 1], [0, oh - 1]]))
            img = cv2.warpPerspective(f.image, m, (ow, oh))
            return self._send(200, {"image": base64.b64encode(cv2.imencode(".jpg", img)[1].tobytes()).decode()})
        if self.path == "/save":
            truth[req["name"]] = {**req["truth"], "size": list(f.size)}
            out.write_text(json.dumps(truth, ensure_ascii=False, indent=1))
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not_found"})

    def log_message(self, *args):
        pass


print(f"http://127.0.0.1:{a.port}/  ({len(comps)} photos) -> {out}")
HTTPServer(("127.0.0.1", a.port), H).serve_forever()
