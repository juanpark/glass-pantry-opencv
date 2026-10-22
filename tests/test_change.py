import cv2
import numpy as np

from tests.synth import shelf
from verifier import change


def rng_shelf(seed=3):
    return shelf(shelves=(0.3, 0.6), seed=seed)


def reshoot(img, dx=40, dy=-25, rot=2.0, scale=1.03, light=1.12):
    """The same shelf photographed again: a small handheld move and brighter light."""
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), rot, scale)
    M[:, 2] += (dx, dy)
    out = cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REFLECT)
    return cv2.convertScaleAbs(out, alpha=light, beta=5), np.vstack([M, [0, 0, 1]])


ITEMS = [{"id": "a", "box": [300, 420, 460, 640]}, {"id": "b", "box": [900, 760, 1060, 980]}]


def test_an_unchanged_reshoot_is_no_visible_change():
    old = rng_shelf()
    new, _ = reshoot(old)
    al = change.align(old, new)
    assert al.ok, al
    r = change.compare(old, ITEMS, new, al)
    assert r["outcome"] == change.OLD_ITEMS_SAME and all(o["outcome"] == change.SAME for o in r["items"]), r


def test_a_removed_item_is_a_possible_change():
    old = rng_shelf()
    new, M = reshoot(old)
    # remove item b in the new photo: paint the back wall's texture over where it now stands
    pts = cv2.transform(np.float32([[[900, 760]], [[1060, 980]]]), M[:2]).reshape(-1, 2).astype(int)
    (x0, y0), (x1, y1) = pts.min(0), pts.max(0)
    wall = rng_shelf(seed=99)
    new[y0:y1, x0:x1] = cv2.convertScaleAbs(wall[y0:y1, x0:x1], alpha=1.12, beta=5)
    r = change.compare(old, ITEMS, new, change.align(old, new))
    by = {o["id"]: o["outcome"] for o in r["items"]}
    assert by["b"] == change.CHANGED and by["a"] == change.SAME and r["outcome"] == change.CHANGED, r


def test_a_different_shelf_cannot_be_compared_never_unchanged():
    old, other = rng_shelf(seed=3), rng_shelf(seed=11)
    al = change.align(old, other)
    r = change.compare(old, ITEMS, other, al)
    assert r["outcome"] == change.CANNOT and all(o["outcome"] == change.CANNOT for o in r["items"])


def test_an_item_outside_the_new_view_cannot_be_compared():
    old = rng_shelf()
    new, _ = reshoot(old, dx=-500, dy=0, rot=0, scale=1.0)
    al = change.align(old, new)
    r = change.compare(old, [{"id": "edge", "box": [40, 420, 200, 640]}], new, al)
    assert r["items"][0]["outcome"] == change.CANNOT


def test_an_item_half_out_of_view_cannot_be_compared():
    old = rng_shelf()
    new, _ = reshoot(old, dx=-500, dy=0, rot=0, scale=1.0)
    r = change.compare(old, [{"id": "half", "box": [400, 420, 600, 640]}], new, change.align(old, new))
    assert r["items"][0]["outcome"] == change.CANNOT, r


def test_the_same_view_at_half_resolution_aligns_with_full_overlap():
    old = rng_shelf()
    new = cv2.resize(old, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    al = change.align(old, new)
    assert al.ok and al.overlap > 0.95, al


def test_something_new_outside_the_old_boxes_is_not_called_no_change():
    old = rng_shelf()
    new, _ = reshoot(old)
    cv2.rectangle(new, (1150, 140), (1400, 260), (20, 200, 240), -1)
    al = change.align(old, new)
    assert al.ok
    r = change.compare(old, [{"id": "a", "box": [300, 420, 460, 640]}], new, al)
    assert r["outcome"] == change.OLD_ITEMS_SAME  # only the compared item is vouched for, never the whole shelf
