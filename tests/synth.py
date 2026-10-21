"""Generated shelf-like images with known truth. No photos of anyone's kitchen."""

import cv2
import numpy as np


def shelf(shelves=(0.3, 0.6), h=1176, w=1568, seed=0) -> np.ndarray:
    """A textured back wall with items (rectangles) and bright horizontal shelf edges at known heights."""
    rng = np.random.default_rng(seed)
    img = (rng.normal(160, 18, (h, w, 3))).clip(0, 255).astype(np.uint8)
    img = cv2.GaussianBlur(img, (3, 3), 0)
    for _ in range(36):  # items: vertical-ish boxes, so the photo has edges in both directions
        x, y = int(rng.integers(0, w - 120)), int(rng.integers(0, h - 200))
        c = tuple(int(v) for v in rng.integers(60, 230, 3))
        cv2.rectangle(img, (x, y), (x + int(rng.integers(60, 160)), y + int(rng.integers(90, 220))), c, -1)
        cv2.rectangle(img, (x, y), (x + 40, y + 40), (30, 30, 30), 3)
    for s in shelves:
        y = int(s * h)
        cv2.rectangle(img, (0, y - 3), (w, y + 3), (215, 215, 215), -1)
        cv2.line(img, (0, y + 4), (w, y + 4), (90, 90, 90), 2)
    return img


def shake(img, k=25):
    ker = np.zeros((k, k), np.float32)
    ker[k // 2, :] = 1 / k
    return cv2.filter2D(img, -1, ker)
