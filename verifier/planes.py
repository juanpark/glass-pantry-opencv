"""Shelf planes: does the photo show a real horizontal edge where the model says a shelf is?

Canny + probabilistic Hough keep near-horizontal segments and sum their length per image row (bins of 0.5%
of the height, lightly smoothed). A proposed shelf line is confirmed when that profile reaches SNAP_MIN
within +-WINDOW of it; it then snaps to the strongest row there. With no such evidence, the proposal is
unconfirmed and the agent asks the person.

Bake-off on one wide shot with 7 recorded model runs: snapping kept the mean error at 0.0024 of the
height and moved 1 of 21 shelves onto a shelf rim instead of the surface. Classical lines alone also
report 4-15 lines that are not shelves, which is why this only checks proposals and never invents them.
"""

import math
from dataclasses import dataclass, asdict

import cv2
import numpy as np

from .gate import grey_at_long_edge

MAX_DEG = 12  # a segment steeper than this is not a shelf edge
BIN = 0.005  # profile bin, fraction of image height
WINDOW = 0.02  # search +-2% of the height around a proposed line
SNAP_MIN = 0.10  # summed segment length / image width needed as evidence


@dataclass(frozen=True)
class PlaneCheck:
    proposed_y: float  # fraction of image height, 0 = top
    confirmed: bool
    snapped_y: float | None
    strength: float  # strongest profile value in the window

    def to_dict(self) -> dict:
        return asdict(self)


def segments(g: np.ndarray) -> np.ndarray:
    e = cv2.Canny(g, 50, 150)
    lines = cv2.HoughLinesP(e, 1, np.pi / 180, 80, minLineLength=int(0.08 * g.shape[1]), maxLineGap=12)
    return np.zeros((0, 4)) if lines is None else lines.reshape(-1, 4)  # OpenCV 5: N x 4; 4.x: N x 1 x 4


def row_profile(segs: np.ndarray, w: int, h: int) -> np.ndarray:
    prof = np.zeros(int(1 / BIN) + 1)
    for x1, y1, x2, y2 in segs:
        dx, dy = x2 - x1, y2 - y1
        if np.degrees(np.arctan2(abs(dy), abs(dx) + 1e-9)) > MAX_DEG:
            continue
        prof[min(len(prof) - 1, int(((y1 + y2) / 2) / h / BIN))] += np.hypot(dx, dy) / w
    return np.convolve(prof, [0.25, 0.5, 0.25], mode="same")


def profile_of(img: np.ndarray) -> np.ndarray:
    g = grey_at_long_edge(img)
    h, w = g.shape
    return row_profile(segments(g), w, h)


def check(img: np.ndarray, proposed: list[float]) -> list[PlaneCheck]:
    prof = profile_of(img)
    out = []
    for y in proposed:
        if not (math.isfinite(y) and 0.0 <= y <= 1.0):  # outside the photo: nothing here can confirm it
            out.append(PlaneCheck(y, False, None, 0.0))
            continue
        i0, i1 = max(0, int((y - WINDOW) / BIN)), min(len(prof), int((y + WINDOW) / BIN) + 1)
        win = prof[i0:i1]
        best = float(win.max()) if len(win) else 0.0
        if best >= SNAP_MIN:
            out.append(PlaneCheck(y, True, round((i0 + int(np.argmax(win))) * BIN, 4), best))
        else:
            out.append(PlaneCheck(y, False, None, best))
    return out
