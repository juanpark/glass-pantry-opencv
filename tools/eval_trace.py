"""Score step 3's OpenCV suggestions against the hand truth (plan v4 R3, R2-3; thresholds frozen 10/23).

    uv run python tools/eval_trace.py PHOTO_DIR TRUTH.json

Eligible photos (all four opening corners visible): was a corner proposal offered, and how far is its worst corner
from the person's (fraction of the image diagonal; good <= 0.03)? On the photo straightened with the PERSON's
corners: snap-target recall (a true edge with a target within 0.02 of the height) and spurious targets per photo.
Ineligible photos: how often a proposal is offered anyway (a nuisance count; nothing is accepted without the tap).
"""

import json
import sys
from pathlib import Path
from statistics import median

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from verifier import frames, opening  # noqa: E402

GOOD, HIT = 0.03, 0.02
GATE = {"offered": 0.6, "median_err": 0.03, "recall": 0.6, "spurious": 2}

photos, truth = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text())
el, inel, errs, rec_hits, rec_all, spur = [], [], [], 0, 0, []
for name, t in truth.items():
    f = frames.canonical((photos / f"{name}.jpg").read_bytes())
    assert list(f.size) == t["size"], name
    p = opening.propose(f.image)
    if not t["eligible"]:
        inel.append((name, p is not None))
        print(f"{name}: ineligible; proposal {'offered' if p is not None else 'not offered'}")
        continue
    q = np.array(t["corners"], float)
    err = None if p is None else float(np.max(np.linalg.norm(p - q, axis=1)) / np.hypot(*f.size))
    w = opening.warp(f.image, q) if opening.validate(q, *f.size) is None else None
    if w is None:  # the person's corners fail the engine's own checks: straighten them without the checks
        import cv2
        ow, oh = opening.out_size(q)
        m = cv2.getPerspectiveTransform(q.astype(np.float32), np.float32([[0, 0], [ow - 1, 0], [ow - 1, oh - 1], [0, oh - 1]]))
        img = cv2.warpPerspective(f.image, m, (ow, oh))
    else:
        img = w.image
    tg = opening.snap_targets(img)
    hits = sum(any(abs(y - s) <= HIT for s in tg) for y in t["lines"])
    sp = sum(not any(abs(s - y) <= HIT for y in t["lines"]) for s in tg)
    el.append(name); errs.append(err); rec_hits += hits; rec_all += len(t["lines"]); spur.append(sp)
    print(f"{name}: proposal {'none' if err is None else f'worst corner {err:.3f}'}; "
          f"edges {hits}/{len(t['lines'])} found, {sp} spurious (targets {tg})")

offered = sum(e is not None for e in errs) / len(errs) if errs else 0
med = median(e for e in errs if e is not None) if any(e is not None for e in errs) else None
recall = rec_hits / rec_all if rec_all else 0
print(f"\neligible {len(el)}, ineligible {len(inel)}")
print(f"corner proposal: offered {offered:.0%} of eligible; median worst-corner error "
      f"{'n/a' if med is None else f'{med:.3f}'}; within {GOOD}: {sum(e is not None and e <= GOOD for e in errs)}/{len(errs)}")
print(f"proposal offered on ineligible photos: {sum(o for _, o in inel)}/{len(inel)} (suggestion only)")
print(f"snap targets: recall {recall:.0%} ({rec_hits}/{rec_all}); spurious per photo {spur}")
keep_corners = offered >= GATE["offered"] and med is not None and med <= GATE["median_err"]
keep_snap = recall >= GATE["recall"] and max(spur or [0]) <= GATE["spurious"]
print(f"\nGATE (frozen): corner proposal {'KEEP' if keep_corners else 'SWITCH OFF'}; snap targets {'KEEP' if keep_snap else 'SWITCH OFF'}")
print(f"small sample: {len(el)} eligible photos from one kitchen; read as a direction, not a rate")
