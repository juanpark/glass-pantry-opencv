import cv2

from tests.synth import shelf
from tests.test_change import ITEMS, add_object, reshoot
from verifier import rescan
from verifier.scan import Proposal


def _jpeg(img):
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()


class Fake:
    def __init__(self, items=None):
        self.calls, self.items = [], items or [{"id": "n1", "label": "new jar", "box": [10, 10, 60, 60]}]

    def propose(self, jpeg):
        self.calls.append(jpeg)
        return Proposal(shelf_lines=[], items=[dict(i) for i in self.items], model="fake")


def test_nothing_changed_files_without_a_model_call():
    old = shelf(seed=3)
    new, _ = reshoot(old)
    f = Fake()
    r = rescan.run(_jpeg(old), ITEMS, _jpeg(new), f)
    assert r["action"] == "file" and r["why"] == [] and f.calls == [], r
    assert {o["id"]: o["outcome"] for o in r["items"]} == {"a": "no_visible_change", "b": "no_visible_change"}
    assert [s["step"] for s in r["trace"]][:3] == ["frames", "gate", "align"]


def test_something_new_is_read_from_its_crop_only_and_mapped_back():
    old = shelf(seed=3)
    new, _ = reshoot(old)
    add_object(new, 1150, 140, 1400, 260)
    f = Fake()
    r = rescan.run(_jpeg(old), ITEMS, _jpeg(new), f)
    assert len(f.calls) == 1 and r["action"] == "ask" and "new:1" in r["why"], r
    crop = cv2.imdecode(__import__("numpy").frombuffer(f.calls[0], "uint8"), cv2.IMREAD_COLOR)
    assert crop.shape[0] < new.shape[0] / 2 and crop.shape[1] < new.shape[1] / 2  # a crop, not the photo
    (n,) = r["new"]
    x0, y0, x1, y1 = n["items"][0]["box"]
    rx0, ry0, rx1, ry1 = n["rect"]
    assert rx0 <= x0 < x1 <= rx1 and ry0 <= y0 < y1 <= ry1  # crop px mapped back into the new photo
    assert n["items"][0]["id"] == "new1.n1"


def test_a_changed_item_is_a_question_never_a_deletion():
    import numpy as np
    old = shelf(seed=3)
    new, M = reshoot(old)
    pts = cv2.transform(np.float32([[[900, 760]], [[1060, 980]]]), M[:2]).reshape(-1, 2).astype(int)
    (x0, y0), (x1, y1) = pts.min(0), pts.max(0)
    new[y0:y1, x0:x1] = cv2.convertScaleAbs(shelf(seed=99)[y0:y1, x0:x1], alpha=1.12, beta=5)
    f = Fake()
    r = rescan.run(_jpeg(old), ITEMS, _jpeg(new), f)
    assert r["action"] == "ask" and "changed:b" in r["why"] and f.calls == [], r
    assert {o["id"] for o in r["items"]} == {"a", "b"}  # every old item is still reported


def test_cannot_align_means_a_full_read_and_no_crop_calls():
    f = Fake()
    r = rescan.run(_jpeg(shelf(seed=3)), ITEMS, _jpeg(shelf(seed=11)), f)
    assert r["action"] == "full_read" and f.calls == [], r


def test_a_blurry_new_photo_is_sent_back_before_aligning():
    old = shelf(seed=3)
    f = Fake()
    r = rescan.run(_jpeg(old), ITEMS, _jpeg(cv2.GaussianBlur(old, (31, 31), 12)), f)
    assert r["action"] == "retake" and f.calls == [] and "align" not in [s["step"] for s in r["trace"]]


def test_unreadable_old_photo_means_full_read():
    f = Fake()
    r = rescan.run(b"not a photo", ITEMS, _jpeg(shelf(seed=3)), f)
    assert r["action"] == "full_read" and r["why"] == ["old_photo:unreadable"] and f.calls == []


def test_regions_beyond_the_cap_are_not_read_but_reported():
    old = shelf(seed=3)
    new, _ = reshoot(old)
    for i, x in enumerate((100, 500, 900, 1300)):
        add_object(new, x, 980, x + 200, 1130, seed=40 + i)
    f = Fake()
    r = rescan.run(_jpeg(old), [], _jpeg(new), f, max_reads=2)
    assert len(f.calls) == 2 and len(r["new"]) >= 3 and any(n["items"] is None for n in r["new"]), r


def test_a_refused_model_call_leaves_regions_unread_and_still_asks():
    old = shelf(seed=3)
    new, _ = reshoot(old)
    add_object(new, 1150, 140, 1400, 260)

    class Refusing:
        def propose(self, jpeg):
            raise rescan.NotAdmitted("daily_limit")

    r = rescan.run(_jpeg(old), ITEMS, _jpeg(new), Refusing())
    assert r["action"] == "ask" and r["new"][0]["items"] is None and r["new"][0]["unread"] == "daily_limit", r
