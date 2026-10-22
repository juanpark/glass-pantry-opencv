"""Mark which label readings were right, one item at a time, from the full-resolution photo.

    uv run python tools/annotate.py RUN_DIR PHOTO_DIR [--port 8766]

RUN_DIR holds run_dev.py results (*.json); PHOTO_DIR the original photos they came from. Opens a local page
(127.0.0.1 only) that shows each labelled item cut from the original, the first reading, and the close-up reading
if there was one. Each answer is saved at once to RUN_DIR/annotations.json. The person annotating sees both
readings but not which one the engine trusted.
"""

import argparse
import base64
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from verifier import frames  # noqa: E402

CHOICES = {"label": ["first", "close-up", "both", "neither", "unsure"], "quantity": ["first", "close-up", "both", "neither", "unsure"]}


def items_to_annotate(run: Path):
    """One entry per (result, item) with a first label, plus every re-read count."""
    out = []
    for f in sorted(run.glob("*.json")):
        if f.name == "annotations.json":
            continue
        r = json.loads(f.read_text())
        prop = r.get("proposal") or {}
        obs = {(o["item_id"], o["field"]): o for o in (r.get("zoom") or {}).get("observations", [])}
        photo = f.name.split("__")[0]
        for it in prop.get("items", []):
            iid = it.get("id")
            for field in ("label", "quantity"):
                o = obs.get((iid, field))
                if field == "label" and it.get("label") is None and not o:
                    continue
                if field == "quantity" and not o:
                    continue
                out.append({"key": f"{f.stem}|{iid}|{field}", "photo": photo, "run": f.stem, "id": iid, "field": field,
                            "box": it.get("box"), "appearance": it.get("appearance"), "first": it.get(field),
                            "closeup": o["crop"] if o else None, "note": o["note"] if o else "not re-read"})
    return out


def thumb(photo_dir: Path, photo: str, box, cache={}):
    if photo not in cache:
        f = frames.canonical((photo_dir / f"{photo}.jpg").read_bytes())
        cache.clear()
        cache[photo] = f
    f = cache[photo]
    x0, y0, x1, y1 = f.to_original(box)
    pad = 0.25 * max(x1 - x0, y1 - y0)
    h, w = f.original.shape[:2]
    c = f.original[int(max(0, y0 - pad)):int(min(h, y1 + pad)), int(max(0, x0 - pad)):int(min(w, x1 + pad))]
    s = min(1.0, 900 / max(c.shape[:2]))
    if s < 1:
        c = cv2.resize(c, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return "data:image/jpeg;base64," + base64.b64encode(cv2.imencode(".jpg", c)[1].tobytes()).decode()


PAGE = """<!doctype html><meta charset=utf-8><title>Annotate readings</title>
<style>body{font:15px system-ui,"Apple SD Gothic Neo",sans-serif;margin:24px;max-width:960px}img{max-width:100%;max-height:60vh;border:1px solid #ccc}
.r{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}button{font:inherit;padding:8px 14px;border-radius:6px;border:1px solid #999;background:#fff;cursor:pointer}
button.on{background:#1f6f5c;color:#fff}.muted{color:#666}b{font-size:1.1em}</style>
<p class=muted id=pos></p><img id=img><p>Item <span id=id></span> · <span id=app class=muted></span></p>
<p>Field: <b id=field></b></p><p>First reading: <b id=first></b></p><p>Close-up reading: <b id=close></b> <span id=note class=muted></span></p>
<p class=muted>Which reading matches what is really printed (label) or really there (count)?</p>
<div class=r id=choices></div><div class=r><button id=prev>Back</button><button id=next>Next</button></div>
<script>
let items=[],ann={},i=0;
async function load(){items=await (await fetch('items')).json();ann=await (await fetch('ann')).json();i=items.findIndex(x=>!ann[x.key]);if(i<0)i=0;show()}
async function show(){const it=items[i];pos.textContent=`${i+1} / ${items.length} · ${Object.keys(ann).length} done`;
img.src='thumb?i='+i;id.textContent=it.id;app.textContent=it.appearance||'';field.textContent=it.field;
first.textContent=it.first??'(none)';close.textContent=it.closeup??'(none)';note.textContent=it.note||'';
choices.innerHTML='';for(const c of ["first","close-up","both","neither","unsure"]){const b=document.createElement('button');b.textContent=c;
if(ann[it.key]===c)b.className='on';b.onclick=async()=>{ann[it.key]=c;await fetch('ann',{method:'POST',body:JSON.stringify({key:it.key,v:c})});if(i<items.length-1)i++;show()};choices.append(b)}}
prev.onclick=()=>{if(i>0)i--;show()};next.onclick=()=>{if(i<items.length-1)i++;show()};load();
</script>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("photos")
    ap.add_argument("--port", type=int, default=8766)
    a = ap.parse_args()
    run, photos = Path(a.run), Path(a.photos)
    items = items_to_annotate(run)
    af = run / "annotations.json"
    ann = json.loads(af.read_text()) if af.exists() else {}
    print(f"{len(items)} readings to annotate; http://127.0.0.1:{a.port}/")

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def _send(self, body, ctype="application/json"):
            b = body.encode() if isinstance(body, str) else body
            self.send_response(200)
            self.send_header("content-type", ctype)
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path == "/":
                return self._send(PAGE, "text/html; charset=utf-8")
            if self.path == "/items":
                return self._send(json.dumps(items, ensure_ascii=False))
            if self.path == "/ann":
                return self._send(json.dumps(ann, ensure_ascii=False))
            if self.path.startswith("/thumb?i="):
                it = items[int(self.path.split("=")[1])]
                url = thumb(photos, it["photo"], it["box"])
                return self._send(base64.b64decode(url.split(",", 1)[1]), "image/jpeg")
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            d = json.loads(self.rfile.read(int(self.headers["content-length"])))
            ann[d["key"]] = d["v"]
            af.write_text(json.dumps(ann, ensure_ascii=False, indent=1))
            self._send("{}")

    HTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
