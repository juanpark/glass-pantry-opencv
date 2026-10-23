"""Straighten a compartment photo to a front view of its opening, with OpenCV suggestions a person confirms.

Plan v4 R3 (step 3). OpenCV *suggests* four opening corners and shelf-edge snap targets; it never accepts an
opening or moves a line by itself. A numerically valid quadrilateral only says the warp is well-posed, not that
it is the opening: the person confirms the corners. Positions are schematic (0-1 of the warped view), never mm.
"""

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .planes import BIN, SNAP_MIN, WINDOW, row_profile, segments
from .gate import grey_at_long_edge

MIN_AREA = 0.15  # quad area / photo area
ANGLE = (55.0, 125.0)  # every interior angle, degrees
MAX_SIDE_RATIO = 2.5  # opposite sides
OUT_LONG = 1568  # warped image long edge, the model's frame size
MARGIN = 0.08  # inner-margin fallback, fraction of each side
PROPOSE_LONG = 800  # contour search scale


def order(pts) -> np.ndarray:
    """Top-left, top-right, bottom-right, bottom-left."""
    p = np.asarray(pts, dtype=np.float64).reshape(4, 2)
    s, d = p.sum(1), p[:, 1] - p[:, 0]
    return np.array([p[np.argmin(s)], p[np.argmin(d)], p[np.argmax(s)], p[np.argmax(d)]])


def validate(quad, w: int, h: int) -> str | None:
    """None when the quad is usable for a warp; otherwise the reason. Says nothing about what it outlines."""
    try:
        q = np.asarray(quad, dtype=np.float64).reshape(4, 2)
    except (ValueError, TypeError):
        return "not_four_points"
    except OverflowError:
        return "not_finite"
    if not np.isfinite(q).all():
        return "not_finite"
    if (q[:, 0] < 0).any() or (q[:, 0] > w).any() or (q[:, 1] < 0).any() or (q[:, 1] > h).any():
        return "outside_photo"
    if len({(round(x, 3), round(y, 3)) for x, y in q}) < 4:
        return "repeated_corner"
    if not np.allclose(order(q), q):
        return "not_ordered"
    cross = []
    for i in range(4):
        a, b, c = q[i], q[(i + 1) % 4], q[(i + 2) % 4]
        cross.append((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]))
    if not (all(x > 0 for x in cross) or all(x < 0 for x in cross)):
        return "not_convex"
    if cv2.contourArea(q.astype(np.float32)) < MIN_AREA * w * h:
        return "too_small"
    for i in range(4):
        u, v = q[i - 1] - q[i], q[(i + 1) % 4] - q[i]
        ang = math.degrees(math.acos(np.clip(u @ v / (np.linalg.norm(u) * np.linalg.norm(v)), -1, 1)))
        if not ANGLE[0] <= ang <= ANGLE[1]:
            return "too_slanted"
    side = [np.linalg.norm(q[(i + 1) % 4] - q[i]) for i in range(4)]
    if max(side[0], side[2]) / min(side[0], side[2]) > MAX_SIDE_RATIO or \
            max(side[1], side[3]) / min(side[1], side[3]) > MAX_SIDE_RATIO:
        return "too_foreshortened"
    return None


def fallback(w: int, h: int) -> np.ndarray:
    m, n = MARGIN * w, MARGIN * h
    return np.array([[m, n], [w - m, n], [w - m, h - n], [m, h - n]])


def propose(img: np.ndarray, alive=None) -> np.ndarray | None:
    """A suggested opening quad in img pixels, or None. Largest convex 4-point contour that validates. `alive()`
    returning False (the request's time is up) stops the search with no suggestion."""
    h, w = img.shape[:2]
    g = grey_at_long_edge(img, PROPOSE_LONG)
    s = w / g.shape[1]
    e = cv2.dilate(cv2.Canny(cv2.GaussianBlur(g, (5, 5), 0), 40, 120), np.ones((3, 3), np.uint8))
    best, best_area = None, 0.0
    for c in cv2.findContours(e, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[0]:
        if alive is not None and not alive():
            return None
        hull = cv2.convexHull(c)
        a = cv2.contourArea(hull)
        if a < MIN_AREA * g.shape[0] * g.shape[1] or a <= best_area:
            continue
        ap = cv2.approxPolyDP(hull, 0.03 * cv2.arcLength(hull, True), True)
        if len(ap) != 4:
            continue
        q = order(ap.reshape(4, 2) * s)
        if validate(q, w, h) is None:
            best, best_area = q, a
    return best


def out_size(q: np.ndarray) -> tuple[int, int]:
    wt = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
    ht = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
    k = OUT_LONG / max(wt, ht)
    return max(1, round(wt * k)), max(1, round(ht * k))


@dataclass(frozen=True)
class Warp:
    image: np.ndarray
    matrix: np.ndarray  # source pixels -> warped pixels, 3x3


def warp(img: np.ndarray, quad) -> Warp:
    q = np.asarray(quad, dtype=np.float64).reshape(4, 2)
    reason = validate(q, img.shape[1], img.shape[0])
    if reason:
        raise ValueError(reason)
    ow, oh = out_size(q)
    dst = np.array([[0, 0], [ow - 1, 0], [ow - 1, oh - 1], [0, oh - 1]], dtype=np.float64)
    m = cv2.getPerspectiveTransform(q.astype(np.float32), dst.astype(np.float32))
    return Warp(cv2.warpPerspective(img, m, (ow, oh), flags=cv2.INTER_AREA), m)


def snap_targets(img: np.ndarray) -> list[float]:
    """Rows (0-1 of the height) with real near-horizontal edge evidence: local maxima >= SNAP_MIN, one per WINDOW."""
    g = grey_at_long_edge(img)
    prof = row_profile(segments(g), g.shape[1], g.shape[0])
    out: list[float] = []
    for i in np.argsort(-prof):
        if prof[i] < SNAP_MIN:
            break
        y = round(float(i) * BIN, 4)
        if all(abs(y - o) > WINDOW for o in out):
            out.append(y)
    return sorted(out)
