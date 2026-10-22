"""Experiment (not in the live service): did anything change on this shelf since the last confirmed photo?

Two handheld photos of one shelf never line up pixel for pixel, so a pixel difference would flag everything.
Instead: align the new photo onto the old one with SIFT features and a robust homography (USAC_MAGSAC), check the
alignment is trustworthy, then compare each previously confirmed item's box by gradient correlation (ZNCC of
Sobel magnitude), which tolerates the lighting changing between shots.

Three outcomes per item: cannot compare / possible change / no visible change. For the photo the best it can say is
"compared items unchanged": only the old items' boxes are checked, so a new thing elsewhere is not looked for.
A failed or doubtful alignment, or an item partly out of view, is "cannot compare", never "no visible change". A homography models a plane; items stand at
different depths, so parallax is expected and the thresholds are deliberately loose.
"""

from dataclasses import dataclass, asdict

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


@dataclass(frozen=True)
class Alignment:
    ok: bool
    H: list | None  # old photo px -> new photo px (full size)
    inliers: int
    ratio: float
    overlap: float
    why: str = ""

    def to_dict(self):
        return asdict(self)


def _grey_small(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    s = min(1.0, LONG / max(g.shape))
    return (cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else g), s


def align(old: np.ndarray, new: np.ndarray) -> Alignment:
    a, sa = _grey_small(old)
    b, sb = _grey_small(new)
    sift = cv2.SIFT_create(nfeatures=4000)
    ka, da = sift.detectAndCompute(a, None)
    kb, db = sift.detectAndCompute(b, None)
    if da is None or db is None or len(ka) < MIN_INLIERS or len(kb) < MIN_INLIERS:
        return Alignment(False, None, 0, 0.0, 0.0, "too_few_features")
    pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(da, db, k=2)
    good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < MIN_INLIERS:
        return Alignment(False, None, len(good), 0.0, 0.0, "too_few_matches")
    pa = np.float32([ka[m.queryIdx].pt for m in good]) / sa
    pb = np.float32([kb[m.trainIdx].pt for m in good]) / sb
    H, mask = cv2.findHomography(pa, pb, cv2.USAC_MAGSAC, 4.0 / sb, maxIters=5000, confidence=0.999)
    if H is None:
        return Alignment(False, None, 0, 0.0, 0.0, "no_homography")
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
    return Alignment(bool(ok), H.tolist(), inl, round(ratio, 3), round(min(overlap, 1.0), 3), why)


def _grad(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    g = cv2.GaussianBlur(g, (3, 3), 0).astype(np.float32)
    return cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))


def _zncc(a, b) -> float:
    a, b = a - a.mean(), b - b.mean()
    d = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / d) if d > 1e-6 else 0.0


def compare(old: np.ndarray, old_items: list[dict], new: np.ndarray, al: Alignment) -> dict:
    """Per confirmed item (boxes in old-photo px): where it should be now, and whether it still looks the same."""
    if not al.ok:
        return {"outcome": CANNOT, "why": al.why, "items": [{"id": it.get("id"), "outcome": CANNOT} for it in old_items]}
    H = np.array(al.H)
    warped = cv2.warpPerspective(old, H, (new.shape[1], new.shape[0]))
    valid = cv2.warpPerspective(np.ones(old.shape[:2], np.uint8), H, (new.shape[1], new.shape[0]))
    ga, gb = _grad(warped), _grad(new)
    out = []
    for it in old_items:
        x0, y0, x1, y1 = it["box"]
        pts = cv2.perspectiveTransform(np.float32([[[x0, y0]], [[x1, y0]], [[x1, y1]], [[x0, y1]]]), H).reshape(-1, 2)
        area = float(abs(cv2.contourArea(pts)))
        seen = np.zeros(new.shape[:2], np.uint8)
        cv2.fillConvexPoly(seen, pts.astype(np.int32), 1)
        coverage = float((seen & valid).sum()) / area if area > 0 else 0.0  # of the WHOLE projected box
        bx0, by0 = np.floor(pts.min(0)).astype(int)
        bx1, by1 = np.ceil(pts.max(0)).astype(int)
        bx0, by0 = max(bx0, 0), max(by0, 0)
        bx1, by1 = min(bx1, new.shape[1]), min(by1, new.shape[0])
        if coverage < MIN_COVERAGE or bx1 - bx0 < 8 or by1 - by0 < 8:
            out.append({"id": it.get("id"), "outcome": CANNOT, "box_now": None, "why": "partly_out_of_view",
                        "coverage": round(coverage, 3)})
            continue
        z = _zncc(ga[by0:by1, bx0:bx1], gb[by0:by1, bx0:bx1])
        verdict = SAME if z >= SAME_ZNCC else CHANGED if z <= CHANGED_ZNCC else CANNOT
        out.append({"id": it.get("id"), "outcome": verdict, "zncc": round(z, 3), "box_now": [int(bx0), int(by0), int(bx1), int(by1)]})
    kinds = {o["outcome"] for o in out}
    overall = CHANGED if CHANGED in kinds else (CANNOT if CANNOT in kinds or not out else OLD_ITEMS_SAME)
    return {"outcome": overall, "alignment": al.to_dict(), "items": out}
