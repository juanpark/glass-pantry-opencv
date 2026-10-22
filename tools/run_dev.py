"""Run the engine on photos with the real model and save everything for review.

    uv run python tools/run_dev.py OUT_DIR PHOTO.jpg [PHOTO.jpg ...] [--zoom] [--runs N]

Writes, per photo and run: the full result JSON, every crop the zoom pass sent, and an overlay picture (shelf
lines, item boxes, re-read boxes). Needs ANTHROPIC_API_KEY (read from .env.local if present). Photos and outputs
stay wherever OUT_DIR is; nothing is uploaded except to the model API.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from verifier import claude, frames, scan, zoom  # noqa: E402


def load_env():
    p = Path(__file__).resolve().parent.parent / ".env.local"
    if p.exists() and "ANTHROPIC_API_KEY" not in os.environ:
        for line in p.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "ANTHROPIC_API_KEY":
                os.environ["ANTHROPIC_API_KEY"] = v.strip()


def overlay(f, result) -> "cv2.Mat":
    img = f.image.copy()
    h, w = img.shape[:2]
    for c in (s for s in result["trace"] if s["step"] == "planes"):
        for chk in c["checks"]:
            y = int((chk["snapped_y"] if chk["confirmed"] else chk["proposed_y"]) * h)
            cv2.line(img, (0, y), (w, y), (60, 200, 60) if chk["confirmed"] else (0, 140, 255), 3)
    for it in (result["proposal"] or {}).get("items", []):
        b = it.get("box")
        if isinstance(b, list) and len(b) == 4:
            cv2.rectangle(img, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (255, 200, 0), 2)
            cv2.putText(img, str(it.get("id")), (int(b[0]) + 2, int(b[1]) + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1)
    colour = {"same": (60, 200, 60), "conflict": (0, 0, 255), "provisional": (0, 200, 255), "unresolved": (160, 160, 160)}
    z = result.get("zoom") or {}
    worst = {}
    for o in z.get("observations", []):
        rank = ["same", "unresolved", "provisional", "conflict"].index(o["outcome"])
        worst[o["item_id"]] = max(worst.get(o["item_id"], 0), rank)
    for p in z.get("plans", []):
        x0, y0, x1, y1 = (int(v) for v in p["rect"])
        cv2.rectangle(img, (x0, y0), (x1, y1), colour[["same", "unresolved", "provisional", "conflict"][worst.get(p["item_id"], 1)]], 4)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("photos", nargs="+")
    ap.add_argument("--zoom", action="store_true")
    ap.add_argument("--runs", type=int, default=1)
    a = ap.parse_args()
    load_env()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    total = 0.0
    for photo in a.photos:
        raw = Path(photo).read_bytes()
        f = frames.canonical(raw)
        for r in range(1, a.runs + 1):
            stem = f"{Path(photo).stem}__r{r}{'__zoom' if a.zoom else ''}"
            asker = claude.ClaudeAsker()

            class SavingAsker:
                n = 0

                def ask(self, crop, fields, target):
                    SavingAsker.n += 1
                    (out / f"{stem}__crop{SavingAsker.n}.jpg").write_bytes(crop)
                    return asker.ask(crop, fields, target)

            try:
                res = scan.run(raw, claude.ClaudeProposer(), zoomer=zoom.Zoomer(SavingAsker()) if a.zoom else None)
            except claude.ModelError as e:
                print(f"{stem}: model error {e}")
                continue
            res["ask_log"] = asker.log
            cost = sum(s.get("cost", 0) for s in res["trace"] if s["step"] == "propose") + sum(x["cost"] for x in asker.log)
            total += cost
            (out / f"{stem}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
            cv2.imwrite(str(out / f"{stem}__overlay.jpg"), overlay(f, res), [cv2.IMWRITE_JPEG_QUALITY, 85])
            outs = [(o["item_id"], o["field"], o["outcome"]) for o in (res.get("zoom") or {}).get("observations", [])]
            print(f"{stem}: {res['action']} why={res['why']} items={len((res['proposal'] or {}).get('items', []))} "
                  f"zoom={outs} cost=${cost:.3f}")
    print(f"total ${total:.3f}")


if __name__ == "__main__":
    main()
