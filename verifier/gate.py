"""Photo gate: is this photo worth sending to a vision model at all?

Measures are taken at a fixed long edge, because Laplacian variance depends on resolution. Thresholds sit
just outside the range of 12 good shelf photos (Glass Pantry bake-off, 2026-10-01): good photos measured
lapvar 119-1,321, anisotropy 0.44-0.98, mean 148-175, clipped-white 0.2-2.1%. They were set on those same
photos, so they are a starting point, not a validated gate.
"""

from dataclasses import dataclass, asdict

import cv2
import numpy as np

LONG = 1568

BLURRY_LAPVAR = 95.0  # Laplacian variance below this: out of focus
SHAKE_ANISO = 0.26  # weaker / stronger gradient direction below this: smeared one way (hand shake)
DARK_MEAN = 89.0  # mean grey level below this: too dark to read labels
BLOWN_PCT = 8.4  # share of pixels at white above this: glare or overexposed


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: list[str]  # empty when passed; codes: blurry, shake, dark, blown
    lapvar: float
    aniso: float
    mean: float
    clip_hi_pct: float

    def to_dict(self) -> dict:
        return asdict(self)


def grey_at_long_edge(img: np.ndarray, long: int = LONG) -> np.ndarray:
    g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    s = long / max(g.shape)
    if s != 1:
        g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return g


def check(img: np.ndarray) -> GateResult:
    g = grey_at_long_edge(img)
    lapvar = float(cv2.Laplacian(g, cv2.CV_64F).var())
    gx, gy = cv2.Sobel(g, cv2.CV_64F, 1, 0), cv2.Sobel(g, cv2.CV_64F, 0, 1)
    ex, ey = float(np.mean(gx * gx)), float(np.mean(gy * gy))
    aniso = min(ex, ey) / max(ex, ey) if max(ex, ey) > 0 else 0.0
    mean = float(g.mean())
    clip_hi = float((g >= 250).mean() * 100)
    reasons = []
    if lapvar < BLURRY_LAPVAR:
        reasons.append("blurry")
    if aniso < SHAKE_ANISO:
        reasons.append("shake")
    if mean < DARK_MEAN:
        reasons.append("dark")
    if clip_hi > BLOWN_PCT:
        reasons.append("blown")
    return GateResult(not reasons, reasons, lapvar, aniso, mean, clip_hi)
