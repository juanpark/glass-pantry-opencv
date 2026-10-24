"""What changed? (experimental, on the page via POST /rescan): did anything change on this shelf since the last
confirmed photo?

Two handheld photos of one shelf never line up pixel for pixel, so a pixel difference would flag everything.
Instead: align the new photo onto the old one and fit a robust homography (USAC_MAGSAC), check the alignment is
trustworthy, then judge each previously confirmed item from its own matched points (a local RANSAC fit inside its
box; gradient correlation, ZNCC of Sobel magnitude, when it has too few points), which tolerates the lighting
changing between shots.

Two ways to match points, compared on the same pairs: "learned" = OpenCV 5's ALIKED keypoints + LightGlueMatcher,
both ONNX models run in the new DNN engine (fetched by tools/fetch_models.py); "sift" = SIFT + Lowe's ratio test.
Everything after the matching is the same for both.

Four outcomes per item: cannot compare / possible change / moved / no visible change. For the photo the best it can
say is "compared items unchanged": only the old items' boxes are checked. `new_regions` looks at the rest of the
photo for something new: cells of new keypoints that matched nothing, outside where the old items now stand, dropped
when a gradient template search finds the same patch nearby in the old photo.
A failed or doubtful alignment, or an item partly out of view, is "cannot compare", never "no visible change". A homography models a plane; items stand at
different depths, so parallax is expected and the thresholds are deliberately loose.
"""

import os
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import cv2
import numpy as np

CANNOT, CHANGED, SAME = "cannot_compare", "possible_change", "no_visible_change"
OLD_ITEMS_SAME = "compared_items_unchanged"  # photo-level: only the old items' boxes were checked, nothing else
MIN_COVERAGE = 0.9  # share of an old item's projected box that must be visible in the new photo
MIN_INLIERS = 40
MIN_INLIER_RATIO = 0.25
MIN_OVERLAP = 0.6  # share of the old photo that lands inside the new one
SAME_ZNCC = 0.55
CHANGED_ZNCC = 0.30
LONG = 1024  # alignment works on a reduced copy
MOVED = "moved"
# Per item, from the matches themselves (a handheld move shifts things at different depths differently, so one
# photo-wide warp cannot judge every item; the item's own matched points can).
MIN_KP = 8  # old keypoints inside a box below this: too plain to judge by matches, gradient correlation decides
MIN_LOCAL = 6  # matched points agreeing on one local move (RANSAC, similarity) to call the item present
SUPPORT = 0.3  # ... and at least this share of the box's own old keypoints
LOCAL_TOL = 0.02  # RANSAC tolerance, share of the photo's long side
MOVED_BY = 0.5  # present, but this many box sizes away from where the shelf-wide fit puts it: moved
GRID = 24  # new_regions: cells across the photo's long side
NEW_UNMATCHED = 3  # a cell is "new" with at least this many unmatched new keypoints ...
NEW_RATIO = 2.0  # ... and this many times more unmatched than matched ones
MIN_NEW_CELLS = 3  # touching cells a region needs
SEARCH = 0.08  # a candidate is looked for in the old photo this far (share of the long side) around where it maps
SEEN_BEFORE = 0.6  # ... and is not new when it is found there at least this well (normalised correlation)
MODELS = Path(os.environ.get("GP_MODELS", Path(__file__).resolve().parent.parent / "models"))


@dataclass(frozen=True)
class Alignment:
    ok: bool
    H: list | None  # old photo px -> new photo px (full size)
    inliers: int
    ratio: float
    overlap: float
    why: str = ""
    method: str = ""
    # The evidence the per-item step uses (full-size px); not serialised. pts_*: every keypoint; m_*: matched pairs.
    pts_old: np.ndarray | None = field(default=None, repr=False, compare=False)
    pts_new: np.ndarray | None = field(default=None, repr=False, compare=False)
    m_old: np.ndarray | None = field(default=None, repr=False, compare=False)
    m_new: np.ndarray | None = field(default=None, repr=False, compare=False)
    inlier: np.ndarray | None = field(default=None, repr=False, compare=False)  # which matched pairs H kept

    def pairs(self, n: int) -> list[list[int]]:
        """Up to n matched pairs the alignment kept, spread evenly, as [x_old, y_old, x_new, y_new] (full px)."""
        if self.inlier is None:
            return []
        idx = np.flatnonzero(self.inlier)
        idx = idx[np.linspace(0, len(idx) - 1, min(n, len(idx))).round().astype(int)] if len(idx) else idx
        return [[round(float(v)) for v in (*self.m_old[i], *self.m_new[i])] for i in idx]

    def to_dict(self):
        return {k: getattr(self, k) for k in ("ok", "H", "inliers", "ratio", "overlap", "why", "method")}


def _grey_small(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    s = min(1.0, LONG / max(g.shape))
    return (cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else g), s


@cache
def _learned():
    det = cv2.ALIKED.create(str(MODELS / "aliked-n16rot-top1k-640.onnx"))
    return det, cv2.LightGlueMatcher.create(str(MODELS / "aliked_lightglue.onnx"))


def _match_learned(a, b):
    det, lg = _learned()
    ka, da = det.detectAndCompute(a, None)
    kb, db = det.detectAndCompute(b, None)
    if da is None or db is None or len(ka) < MIN_INLIERS or len(kb) < MIN_INLIERS:
        return ka, kb, None
    lg.setPairInfo(np.float32([k.pt for k in ka]), np.float32([k.pt for k in kb]),
                   (a.shape[1], a.shape[0]), (b.shape[1], b.shape[0]))
    return ka, kb, list(lg.match(da, db))


def _match_sift(a, b):
    sift = cv2.SIFT_create(nfeatures=4000)
    ka, da = sift.detectAndCompute(a, None)
    kb, db = sift.detectAndCompute(b, None)
    if da is None or db is None or len(ka) < MIN_INLIERS or len(kb) < MIN_INLIERS:
        return ka, kb, None
    pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(da, db, k=2)
    return ka, kb, [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.75 * n.distance]


TURNS = (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE, cv2.ROTATE_180)


def _unturn(pts, turn, w, h):
    """Points found on the new photo turned by `turn` -> the same points on the photo as given (w x h)."""
    x, y = pts[:, 0], pts[:, 1]
    if turn == cv2.ROTATE_90_CLOCKWISE:  # (x, y) was turned to (h-1-y, x)
        return np.stack([y, h - 1 - x], 1)
    if turn == cv2.ROTATE_90_COUNTERCLOCKWISE:  # (x, y) was turned to (y, w-1-x)
        return np.stack([w - 1 - y, x], 1)
    if turn == cv2.ROTATE_180:
        return np.stack([w - 1 - x, h - 1 - y], 1)
    return pts


def align(old: np.ndarray, new: np.ndarray, method: str = "learned") -> Alignment:
    """The phone may be held the other way round for the second photo (portrait vs landscape). LightGlue does not
    match across a quarter turn, so when the photo as given does not align, the three turns are tried in order and
    the first that aligns is kept; otherwise the best failure is reported."""
    best = None
    for turn in TURNS:
        al = _align_once(old, new, method, turn)
        if al.ok:
            return al
        if best is None or al.inliers > best.inliers:
            best = al
    return best


def _align_once(old, new, method, turn) -> Alignment:
    a, sa = _grey_small(old)
    b0, sb = _grey_small(new)
    b = b0 if turn is None else cv2.rotate(b0, turn)
    ka, kb, good = (_match_learned if method == "learned" else _match_sift)(a, b)
    if good is None:
        return Alignment(False, None, 0, 0.0, 0.0, "too_few_features", method)
    if len(good) < MIN_INLIERS:
        return Alignment(False, None, len(good), 0.0, 0.0, "too_few_matches", method)
    pa = np.float32([ka[m.queryIdx].pt for m in good]) / sa
    bw, bh = b0.shape[1], b0.shape[0]
    pb = _unturn(np.float32([kb[m.trainIdx].pt for m in good]), turn, bw, bh) / sb
    H, mask = cv2.findHomography(pa, pb, cv2.USAC_MAGSAC, 4.0 / sb, maxIters=5000, confidence=0.999)
    if H is None:
        return Alignment(False, None, 0, 0.0, 0.0, "no_homography", method)
    inl = int(mask.sum())
    ratio = inl / len(good)
    h, w = old.shape[:2]
    nh, nw = new.shape[:2]
    # Overlap in the old photo's frame: the share of the old photo that the new one also shows.
    back = cv2.perspectiveTransform(np.float32([[[0, 0]], [[nw, 0]], [[nw, nh]], [[0, nh]]]), np.linalg.inv(H))
    poly = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(poly, back.reshape(-1, 2).astype(np.int32), 1)
    overlap = float(poly.sum()) / (w * h)
    ok = inl >= MIN_INLIERS and ratio >= MIN_INLIER_RATIO and overlap >= MIN_OVERLAP and np.isfinite(H).all()
    why = "" if ok else ("few_inliers" if inl < MIN_INLIERS or ratio < MIN_INLIER_RATIO else "small_overlap")
    return Alignment(bool(ok), H.tolist(), inl, round(ratio, 3), round(min(overlap, 1.0), 3), why, method,
                     np.float32([k.pt for k in ka]) / sa,
                     _unturn(np.float32([k.pt for k in kb]), turn, bw, bh) / sb, pa, pb, mask.ravel().astype(bool))


def _grad(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    g = cv2.GaussianBlur(g, (3, 3), 0).astype(np.float32)
    return cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))


def _zncc(a, b) -> float:
    a, b = a - a.mean(), b - b.mean()
    d = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / d) if d > 1e-6 else 0.0


def _inside(pts, box):
    x0, y0, x1, y1 = box
    return (pts[:, 0] >= x0) & (pts[:, 0] <= x1) & (pts[:, 1] >= y0) & (pts[:, 1] <= y1)


def _project(box, H):
    x0, y0, x1, y1 = box
    return cv2.perspectiveTransform(np.float32([[[x0, y0]], [[x1, y0]], [[x1, y1]], [[x0, y1]]]), H).reshape(-1, 2)


def _clip(pts, w, h):
    bx0, by0 = np.floor(pts.min(0)).astype(int)
    bx1, by1 = np.ceil(pts.max(0)).astype(int)
    return [int(max(bx0, 0)), int(max(by0, 0)), int(min(bx1, w)), int(min(by1, h))]


def compare(old: np.ndarray, old_items: list[dict], new: np.ndarray, al: Alignment) -> dict:
    """Per confirmed item (boxes in old-photo px): present where the shelf-wide fit puts it (no visible change),
    present elsewhere (moved), not found (possible change), or cannot compare. Presence is decided by the item's
    own matched points agreeing on one local move; a plain box with too few keypoints falls back to gradient
    correlation after the shelf-wide warp."""
    if not al.ok:
        return {"outcome": CANNOT, "why": al.why, "items": [{"id": it.get("id"), "outcome": CANNOT} for it in old_items]}
    H = np.array(al.H)
    nh, nw = new.shape[:2]
    valid = cv2.warpPerspective(np.ones(old.shape[:2], np.uint8), H, (nw, nh))
    ga = gb = None
    tol = LOCAL_TOL * max(nw, nh)
    area_of = lambda b: (b[2] - b[0]) * (b[3] - b[1])
    out = []
    for it in old_items:
        # A point belongs to the smallest box that holds it: boxes overlap (a jar in front of a bag), and a big box
        # must not be kept "present" by the points of the smaller things inside or in front of it.
        smaller = [o["box"] for o in old_items if o is not it and area_of(o["box"]) < area_of(it["box"])]

        def own(pts, box=it["box"], smaller=smaller):
            m = _inside(pts, box)
            for sb in smaller:
                m &= ~_inside(pts, sb)
            return m

        box = it["box"]
        pts = _project(box, H)
        area = float(abs(cv2.contourArea(pts)))
        seen = np.zeros((nh, nw), np.uint8)
        cv2.fillConvexPoly(seen, pts.astype(np.int32), 1)
        coverage = float((seen & valid).sum()) / area if area > 0 else 0.0  # of the WHOLE projected box
        b = _clip(pts, nw, nh)
        if coverage < MIN_COVERAGE or b[2] - b[0] < 8 or b[3] - b[1] < 8:
            out.append({"id": it.get("id"), "outcome": CANNOT, "box_now": None, "why": "partly_out_of_view",
                        "coverage": round(coverage, 3)})
            continue
        n_kp = int(own(al.pts_old).sum()) if al.pts_old is not None else 0
        if n_kp < MIN_KP:
            if ga is None:
                ga, gb = _grad(cv2.warpPerspective(old, H, (nw, nh))), _grad(new)
            z = _zncc(ga[b[1]:b[3], b[0]:b[2]], gb[b[1]:b[3], b[0]:b[2]])
            verdict = SAME if z >= SAME_ZNCC else CHANGED if z <= CHANGED_ZNCC else CANNOT
            out.append({"id": it.get("id"), "outcome": verdict, "by": "gradient", "zncc": round(z, 3), "box_now": b})
            continue
        sel = own(al.m_old)
        local, M = 0, None
        if sel.sum() >= 3:
            M, inl = cv2.estimateAffinePartial2D(al.m_old[sel], al.m_new[sel], method=cv2.RANSAC,
                                                 ransacReprojThreshold=tol)
            local = int(inl.sum()) if M is not None else 0
        rec = {"id": it.get("id"), "by": "matches", "keypoints": n_kp, "agreeing": local}
        if local < MIN_LOCAL or local < SUPPORT * n_kp:
            out.append({**rec, "outcome": CHANGED, "box_now": b})
            continue
        x0, y0, x1, y1 = box
        moved = cv2.transform(np.float32([[[x0, y0]], [[x1, y0]], [[x1, y1]], [[x0, y1]]]), M).reshape(-1, 2)
        # where the item's own points put it must be in view too, not only where the shelf-wide fit puts it
        here = np.zeros((nh, nw), np.uint8)
        cv2.fillConvexPoly(here, moved.astype(np.int32), 1)
        m_area = float(abs(cv2.contourArea(moved)))
        m_cov = float((here & valid).sum()) / m_area if m_area > 0 else 0.0
        mb = _clip(moved, nw, nh)
        if m_cov < MIN_COVERAGE or mb[2] - mb[0] < 8 or mb[3] - mb[1] < 8:
            out.append({**rec, "outcome": CANNOT, "box_now": None, "why": "partly_out_of_view",
                        "coverage": round(m_cov, 3)})
            continue
        size = max(x1 - x0, y1 - y0) * float(np.sqrt(abs(np.linalg.det(M[:, :2]))))
        off = float(np.linalg.norm(moved.mean(0) - pts.mean(0)))
        if off > MOVED_BY * size:
            out.append({**rec, "outcome": MOVED, "box_now": mb, "box_expected": b})
        else:
            out.append({**rec, "outcome": SAME, "box_now": mb})  # the accepted footprint, from the item's own fit
    kinds = {o["outcome"] for o in out}
    overall = (CHANGED if kinds & {CHANGED, MOVED} else
               (CANNOT if CANNOT in kinds or not out else OLD_ITEMS_SAME))
    return {"outcome": overall, "alignment": al.to_dict(), "items": out}


def new_regions(old: np.ndarray, old_items: list[dict], new: np.ndarray, al: Alignment,
                found: list[dict] | None = None) -> list[list[int]]:
    """Boxes (new-photo px) where something may have been added: grid cells full of new-photo keypoints that
    matched nothing in the old photo, inside the part both photos show, outside the boxes of old items (found
    there, or already asked about as a possible change; `found`: compare()'s items). Touching cells join.
    No alignment, no regions."""
    if not al.ok or al.pts_new is None:
        return []
    nh, nw = new.shape[:2]
    H = np.array(al.H)
    valid = cv2.warpPerspective(np.ones(old.shape[:2], np.uint8), H, (nw, nh))
    taken = np.zeros((nh, nw), np.uint8)
    for o in found if found is not None else compare(old, old_items, new, al)["items"]:
        if o["outcome"] in (SAME, MOVED, CHANGED) and o.get("box_now"):  # found, or already a question
            x0, y0, x1, y1 = o["box_now"]
            taken[y0:y1, x0:x1] = 1
    matched = {(round(float(x), 1), round(float(y), 1)) for x, y in al.m_new}
    is_m = np.array([(round(float(x), 1), round(float(y), 1)) in matched for x, y in al.pts_new], bool)
    cell = max(nw, nh) / GRID
    rows, cols = int(np.ceil(nh / cell)), int(np.ceil(nw / cell))
    um, mm = np.zeros((rows, cols)), np.zeros((rows, cols))
    for (x, y), m in zip(al.pts_new, is_m):
        xi, yi = int(np.clip(x, 0, nw - 1)), int(np.clip(y, 0, nh - 1))
        if not valid[yi, xi] or taken[yi, xi]:
            continue
        (mm if m else um)[int(y // cell), int(x // cell)] += 1
    flag = ((um >= NEW_UNMATCHED) & (um >= NEW_RATIO * mm)).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(flag, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < MIN_NEW_CELLS:
            continue
        box = [int(x * cell), int(y * cell), int(min((x + w) * cell, nw)), int(min((y + h) * cell, nh))]
        if not _seen_before(old, new, H, box):
            out.append(box)
    return out


def _seen_before(old, new, H, box) -> bool:
    """Was this part of the new photo already in the old one, a little shifted? Things at another depth than the
    shelf-wide fit (a ceiling, a shelf edge, glare) move by parallax and lose their matches, but they are still
    there. Template search on gradients around where the region maps back into the old photo."""
    s = min(1.0, LONG / max(new.shape[:2]))
    x0, y0, x1, y1 = box
    back = cv2.perspectiveTransform(np.float32([[[x0, y0]], [[x1, y0]], [[x1, y1]], [[x0, y1]]]), np.linalg.inv(H))
    bx0, by0 = back.reshape(-1, 2).min(0)
    bx1, by1 = back.reshape(-1, 2).max(0)
    pad = SEARCH * max(old.shape[:2])
    h, w = old.shape[:2]
    sx0, sy0 = int(max(bx0 - pad, 0)), int(max(by0 - pad, 0))
    sx1, sy1 = int(min(bx1 + pad, w)), int(min(by1 + pad, h))
    tmpl = _grad(cv2.resize(new[y0:y1, x0:x1], None, fx=s, fy=s, interpolation=cv2.INTER_AREA))
    area = _grad(cv2.resize(old[sy0:sy1, sx0:sx1], None, fx=s, fy=s, interpolation=cv2.INTER_AREA))
    if area.shape[0] < tmpl.shape[0] or area.shape[1] < tmpl.shape[1]:
        return False
    return float(cv2.matchTemplate(area, tmpl, cv2.TM_CCOEFF_NORMED).max()) >= SEEN_BEFORE
