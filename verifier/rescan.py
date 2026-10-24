"""A rescan of one shelf: OpenCV decides what, if anything, the model is asked.

    frames -> gate -> align new onto the last confirmed photo (OpenCV 5 ALIKED + LightGlue, USAC_MAGSAC)
           -> per old item: no visible change / possible change / cannot compare
           -> something-new regions -> the model reads only the crops of changed spots and new regions -> decision

Actions:
    retake     the new photo failed the gate (no model call)
    full_read  the photos cannot be compared (unreadable old photo, or no trustworthy alignment): the page falls
               back to an ordinary scan; nothing here is filed
    file       every old item shows no visible change and nothing new: the old readings stand (no model call)
    ask        something changed, is unclear or is new: a person answers; a changed item is a question, never a deletion

Old item boxes are in the old photo's pixels; everything returned is in the new canonical photo's pixels.
"""

import hashlib
import time

import cv2

from . import change, decide, frames as frames_mod, gate

MAX_READS = 3  # crops sent to the model per rescan; regions beyond it are reported unread
PAD = 0.15  # crop margin around a region, as a share of its larger side
QUALITY = 92


class NotAdmitted(Exception):
    """Raised by a proposer that may not make a model call (switched off, or today's allowance used up)."""


def _crop(img, rect):
    x0, y0, x1, y1 = rect
    p = round(PAD * max(x1 - x0, y1 - y0))
    h, w = img.shape[:2]
    x0, y0, x1, y1 = max(x0 - p, 0), max(y0 - p, 0), min(x1 + p, w), min(y1 + p, h)
    return [x0, y0, x1, y1], cv2.imencode(".jpg", img[y0:y1, x0:x1], [cv2.IMWRITE_JPEG_QUALITY, QUALITY])[1].tobytes()


def run(old_jpeg: bytes, old_items: list[dict], new_jpeg: bytes, proposer, max_reads: int = MAX_READS) -> dict:
    trace: list[dict] = []
    t0 = time.perf_counter()

    def step(name, **data):
        trace.append({"step": name, "ms": round((time.perf_counter() - t0) * 1000, 1), **data})

    def done(action, why, items=(), new=()):
        step("decide", action=action, why=why)
        return {"action": action, "why": why, "items": list(items), "new": list(new), "trace": trace}

    f = frames_mod.canonical(new_jpeg)
    if f is None:
        return done(decide.RETAKE, ["photo:unreadable"])
    step("frames", size=list(f.size), source=hashlib.sha256(f.jpeg).hexdigest()[:16])
    g = gate.check(f.image)
    step("gate", **g.to_dict())
    early = decide.after_gate(g)
    if early:
        return done(early.action, early.why)
    old = frames_mod.decode(old_jpeg)
    if old is None:
        return done("full_read", ["old_photo:unreadable"])

    al = change.align(old, f.image)
    step("align", **al.to_dict() | {"H": None})
    cmp = change.compare(old, old_items, f.image, al)
    if not al.ok:
        return done("full_read", [f"align:{al.why}"], cmp["items"])
    step("compare", outcomes=[(o["id"], o["outcome"]) for o in cmp["items"]])
    regions = change.new_regions(old, old_items, f.image, al, cmp["items"])
    step("new_regions", regions=regions)

    # What to read: where an old item looks changed (it may be gone, or something else stands there now), then
    # each new region. Unchanged and moved items keep their reading and are not read again.
    spots = [o["box_now"] for o in cmp["items"] if o["outcome"] == change.CHANGED and o.get("box_now")] + regions
    new = []
    for i, r in enumerate(spots, 1):
        if i > max_reads:
            new.append({"region": i, "rect": r, "items": None})  # over the cap: shown, not read
            continue
        rect, crop = _crop(f.image, r)
        try:
            p = proposer.propose(crop)
        except NotAdmitted as e:  # no model call allowed: this and later regions are shown unread
            new += [{"region": j, "rect": rr, "items": None, "unread": str(e)} for j, rr in enumerate(spots[i - 1:], i)]
            step("read_region", region=i, refused=str(e))
            break
        items = []
        for it in p.items:
            b = it.get("box")
            if isinstance(b, list) and len(b) == 4:
                it = {**it, "box": [b[0] + rect[0], b[1] + rect[1], b[2] + rect[0], b[3] + rect[1]]}
            items.append({**it, "id": f"new{i}.{it.get('id')}"})
        new.append({"region": i, "rect": rect, "items": items, "raw": p.raw})
        step("read_region", region=i, rect=rect, items=len(items), **{k: p.raw.get(k) for k in ("request_id", "cost")})

    why = [f"changed:{o['id']}" for o in cmp["items"] if o["outcome"] == change.CHANGED]
    why += [f"unclear:{o['id']}" for o in cmp["items"] if o["outcome"] == change.CANNOT]
    why += [f"new:{n['region']}" for n in new[len(spots) - len(regions):]]
    return done(decide.ASK if why else decide.FILE, why, cmp["items"], new)
