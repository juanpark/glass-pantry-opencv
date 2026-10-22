"""One canonical image per request, and the way back to the original's pixels.

The gate, the model and the shelf-line check all work on the same canonical bytes, so a check can never pass a
different photo from the one that is read. Large photos are reduced to a 1568 px long edge (more pixels cost the
model more image tokens and add no reading accuracy at this size); the original is kept so a crop can be cut from
it at full detail, with its rectangle recorded in both frames.
"""

from dataclasses import dataclass

import cv2
import numpy as np

LONG = 1568
QUALITY = 92


@dataclass(frozen=True)
class Frames:
    jpeg: bytes  # canonical: what the gate checks and the model reads
    image: np.ndarray  # canonical, decoded
    original: np.ndarray
    scale: float  # canonical px per original px (1.0 when unchanged)

    @property
    def size(self) -> tuple[int, int]:
        return self.image.shape[1], self.image.shape[0]

    @property
    def original_size(self) -> tuple[int, int]:
        return self.original.shape[1], self.original.shape[0]

    def to_original(self, rect):
        return tuple(round(v / self.scale, 1) for v in rect)


def decode(b: bytes) -> np.ndarray | None:
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR) if b else None


def canonical(original_jpeg: bytes) -> Frames | None:
    orig = decode(original_jpeg)
    if orig is None:
        return None
    s = LONG / max(orig.shape[:2])
    stored = cv2.imdecode(np.frombuffer(original_jpeg, np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    if s >= 1 and stored is not None and np.array_equal(stored, orig):
        return Frames(original_jpeg, orig, orig, 1.0)
    # Larger than the canonical size, or turned by an EXIF orientation tag (a reader might honour it or not, and
    # every coordinate would move): encode the upright pixels once, so OpenCV and the model see the same image.
    s = min(s, 1.0)
    img = orig if s == 1.0 else cv2.resize(orig, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, QUALITY])[1].tobytes()
    return Frames(jpeg, decode(jpeg), orig, s)
