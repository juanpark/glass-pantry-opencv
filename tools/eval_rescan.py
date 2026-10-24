"""Rescan diff on real before/after pairs: both matching methods, scored against the owner's notes.

    uv run python tools/eval_rescan.py PAIRS.json OUT_DIR [--methods learned,sift]

PAIRS.json: [{"name", "before", "after", "scan", "removed": [item ids], "added": [[x0,y0,x1,y1] in after-photo
canonical px]}]. Paths are relative to the file. "scan" is a recorded result of the live engine on the before photo
(its proposal's item boxes are the old boxes, no hand edits); when it does not exist yet, one Claude scan is made
and saved there (needs ANTHROPIC_API_KEY). Writes OUT_DIR/results.json, a table on stdout, and per pair and method
an overlay of the after photo: green no visible change, red possible change, magenta moved, grey cannot
compare, blue new.
Photos and outputs stay local.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from verifier import change, frames  # noqa: E402

COLOUR = {change.SAME: (60, 200, 60), change.CHANGED: (0, 0, 255), change.CANNOT: (160, 160, 160),
          change.MOVED: (255, 0, 255)}


def old_items(scan_path: Path, before_jpeg: bytes) -> list[dict]:
    if not scan_path.exists():
        from tools.run_dev import load_env
        from verifier import claude, scan
        load_env()
        res = scan.run(before_jpeg, claude.ClaudeProposer())
        scan_path.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    res = json.loads(scan_path.read_text())
    return [{"id": it["id"], "name": it.get("label") or it.get("appearance"), "box": it["box"]}
            for it in (res.get("proposal") or {}).get("items", [])
            if isinstance(it.get("box"), list) and len(it["box"]) == 4]


def overlaps(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def score(p: dict, r: dict, regions: list, al) -> dict:
    by = {o["id"]: o["outcome"] for o in r["items"]}
    asked = [o["box_now"] for o in r["items"] if o["outcome"] == change.CHANGED and o.get("box_now")]
    removed = p.get("removed", [])
    added = p.get("added", [])
    stayed = [i for i in by if i not in removed]
    return {
        "aligned": al.ok,
        "removed_flagged": sum(by.get(i) in (change.CHANGED, change.CANNOT, change.MOVED) for i in removed),
        "removed": len(removed),
        "false_flags": sum(by[i] in (change.CHANGED, change.MOVED) for i in stayed),
        # an added thing is found when a new region or a changed item's spot (both are read) covers it
        "added_found": sum(any(overlaps(a, g) for g in regions + asked) for a in added),
        "added": len(added),
        "false_new": sum(not any(overlaps(g, a) for a in added) for g in regions),
        "rereads_saved": sum(v == change.SAME for v in by.values()),
        "items": len(by),
    }


def draw(img, r, regions):
    out = img.copy()
    for o in r["items"]:
        if o.get("box_now"):
            x0, y0, x1, y1 = o["box_now"]
            cv2.rectangle(out, (x0, y0), (x1, y1), COLOUR[o["outcome"]], 3)
            cv2.putText(out, str(o["id"]), (x0 + 3, y0 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOUR[o["outcome"]], 2)
    for x0, y0, x1, y1 in regions:
        cv2.rectangle(out, (x0, y0), (x1, y1), (255, 140, 0), 3)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pairs")
    ap.add_argument("out")
    ap.add_argument("--methods", default="learned,sift")
    a = ap.parse_args()
    base = Path(a.pairs).resolve().parent
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in json.loads(Path(a.pairs).read_text()):
        fb = frames.canonical((base / p["before"]).read_bytes())
        fa = frames.canonical((base / p["after"]).read_bytes())
        items = old_items(base / p["scan"], (base / p["before"]).read_bytes())
        for m in a.methods.split(","):
            t = time.perf_counter()
            al = change.align(fb.image, fa.image, method=m)
            r = change.compare(fb.image, items, fa.image, al)
            regions = change.new_regions(fb.image, items, fa.image, al)
            ms = round((time.perf_counter() - t) * 1000)
            s = score(p, r, regions, al)
            rows.append({"pair": p["name"], "method": m, "ms": ms, "alignment": al.to_dict(), **s,
                         "outcomes": {o["id"]: o["outcome"] for o in r["items"]}, "regions": regions})
            cv2.imwrite(str(out / f"{p['name']}__{m}.jpg"), draw(fa.image, r, regions), [cv2.IMWRITE_JPEG_QUALITY, 85])
            print(f"{p['name']:<10} {m:<8} aligned={s['aligned']!s:<5} inl={al.inliers:<4} ov={al.overlap:<5} "
                  f"removed {s['removed_flagged']}/{s['removed']}  false={s['false_flags']}  "
                  f"added {s['added_found']}/{s['added']}  false_new={s['false_new']}  "
                  f"saved {s['rereads_saved']}/{s['items']}  {ms} ms")
    (out / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
