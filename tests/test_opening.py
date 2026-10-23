import base64
import json

import cv2
import numpy as np
import pytest

from service import handler as h
from tests.synth import shelf
from verifier import opening as op

W, H = 1200, 1600


def opening_photo(quad=((200, 250), (1000, 300), (980, 1350), (220, 1400)), lines=(0.3, 0.55, 0.8)):
    """A dark kitchen with a bright, slightly tilted fridge opening and shelf edges inside it."""
    img = np.full((H, W, 3), 60, np.uint8)
    q = np.array(quad, np.float32)
    inner = np.full((900, 700, 3), 225, np.uint8)
    for y in lines:
        cv2.line(inner, (20, int(y * 900)), (680, int(y * 900)), (90, 90, 90), 6)
    m = cv2.getPerspectiveTransform(np.float32([[0, 0], [699, 0], [699, 899], [0, 899]]), q)
    warped = cv2.warpPerspective(inner, m, (W, H))
    mask = cv2.warpPerspective(np.full((900, 700), 255, np.uint8), m, (W, H))
    img[mask > 0] = warped[mask > 0]
    return img, q


GOOD = [[100, 100], [1100, 120], [1080, 1500], [120, 1480]]


def test_order_sorts_corners_clockwise_from_top_left():
    assert op.order([GOOD[2], GOOD[0], GOOD[3], GOOD[1]]).tolist() == GOOD


@pytest.mark.parametrize("quad,reason", [
    ([[0, 0], [1, 1]], "not_four_points"),
    ([[100, 100], [1100, 120], [1080, float("nan")], [120, 1480]], "not_finite"),
    ([[-5, 100], [1100, 120], [1080, 1500], [120, 1480]], "outside_photo"),
    ([[1100, 120], [100, 100], [1080, 1500], [120, 1480]], "not_ordered"),
    ([[100, 100], [1100, 120], [600, 300], [120, 1480]], "not_ordered"),
    ([[500, 500], [700, 500], [700, 700], [500, 700]], "too_small"),
    ([[100, 100], [500, 100], [1100, 900], [700, 900]], "too_slanted"),
    ([[100, 100], [1100, 100], [1100, 1500], [100, 1500]], None),
])
def test_validate_says_why(quad, reason):
    assert op.validate(quad, W, H) == reason


def test_strong_foreshortening_is_refused():
    assert op.validate([[100, 600], [1100, 100], [1100, 1500], [100, 1000]], W, H) == "too_foreshortened"


def test_warp_maps_the_corners_to_the_frame_and_keeps_the_model_size():
    img, q = opening_photo()
    w = op.warp(img, q)
    assert max(w.image.shape[:2]) == op.OUT_LONG
    got = cv2.perspectiveTransform(q.reshape(1, 4, 2).astype(np.float64), w.matrix)[0]
    oh, ow = w.image.shape[:2]
    assert np.allclose(got, [[0, 0], [ow - 1, 0], [ow - 1, oh - 1], [0, oh - 1]], atol=1e-6)


def test_warp_refuses_an_invalid_quad():
    with pytest.raises(ValueError, match="too_small"):
        op.warp(np.zeros((H, W, 3), np.uint8), [[500, 500], [700, 500], [700, 700], [500, 700]])


def test_snap_targets_find_the_shelf_edges_of_a_straightened_opening():
    img, q = opening_photo()
    t = op.snap_targets(op.warp(img, q).image)
    for y in (0.3, 0.55, 0.8):
        assert any(abs(y - s) <= 0.02 for s in t), (y, t)


def test_no_snap_targets_on_a_blank_wall():
    assert op.snap_targets(np.full((900, 700, 3), 200, np.uint8)) == []


def test_propose_suggests_the_bright_opening():
    img, q = opening_photo()
    p = op.propose(img)
    assert p is not None and np.abs(p - q).max() < 0.03 * np.hypot(W, H)


def test_propose_may_outline_a_box_front_that_is_not_an_opening():
    """A numerically valid rectangle is only a suggestion (plan v4 R3, R2-1): nothing here proves it is an opening."""
    img = np.full((H, W, 3), 60, np.uint8)
    cv2.rectangle(img, (250, 300), (950, 1300), (200, 170, 120), -1)  # a cardboard box front
    p = op.propose(img)
    assert p is None or op.validate(p, W, H) is None  # may be offered, and is still never accepted by the engine


# --- the route ---------------------------------------------------------------------------------------------------

def ev(body: dict):
    raw = json.dumps(body).encode()
    return {"rawPath": "/straighten", "requestContext": {"http": {"method": "POST"}},
            "headers": {"content-type": "application/json"}, "body": base64.b64encode(raw).decode(),
            "isBase64Encoded": True}


def jpeg(img):
    return base64.b64encode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()).decode()


def call(e, **kw):
    kw.setdefault("is_enabled", lambda: True)
    kw.setdefault("admitter", lambda: pytest.fail("straightening is never counted"))
    kw.setdefault("key", lambda: pytest.fail("straightening needs no model key"))
    kw.setdefault("scanner", lambda *a, **k: pytest.fail("straightening never calls the model"))
    r = h.handler(e, **kw)
    return r["statusCode"], json.loads(r["body"])


def test_route_suggests_corners_and_never_accepts_them():
    img, q = opening_photo()
    s, b = call(ev({"photo": jpeg(img)}))
    assert s == 200 and b["status"] == "suggested" and b["suggestion"] in ("contour", "margin")
    assert len(b["corners"]) == 4 and "accepted" not in json.dumps(b)
    assert b["size"] == [1176, 1568] and len(b["source"]) == 16 and "image" not in b  # the canonical frame


def test_route_falls_back_to_the_inner_margin_and_says_so():
    s, b = call(ev({"photo": jpeg(np.full((H, W, 3), 128, np.uint8))}))
    assert s == 200 and b["suggestion"] == "margin" and b["status"] == "suggested"


def canonical_corners(img, q):
    """The suggestion call gives the canonical frame's size and source; corners are sent in that frame."""
    _, sug = call(ev({"photo": jpeg(img)}))
    k = sug["size"][0] / img.shape[1]
    return (q * k).tolist(), sug["source"], k


def test_route_straightens_the_persons_corners():
    img, q = opening_photo()
    corners, source, k = canonical_corners(img, q)
    s, b = call(ev({"photo": jpeg(img), "corners": corners, "source": source}))
    assert s == 200 and b["status"] == "straightened"
    got = cv2.perspectiveTransform(np.array([corners], np.float64), np.array(b["matrix"]))[0]
    ow, oh = b["image_size"]
    assert np.allclose(got, [[0, 0], [ow - 1, 0], [ow - 1, oh - 1], [0, oh - 1]], atol=1e-6)
    m = np.array(b["matrix"])
    assert m.shape == (3, 3)
    out = cv2.imdecode(np.frombuffer(base64.b64decode(b["image"]), np.uint8), cv2.IMREAD_COLOR)
    assert max(out.shape[:2]) == op.OUT_LONG and out.shape[:2] == tuple(b["image_size"][::-1])
    assert all(0 <= y <= 1 for y in b["targets"])


def test_route_refuses_bad_corners_with_the_reason_and_no_image():
    img, _ = opening_photo()
    _, source, _ = canonical_corners(img, np.zeros((4, 2)))
    s, b = call(ev({"photo": jpeg(img), "corners": [[500, 500], [700, 500], [700, 700], [500, 700]], "source": source}))
    assert s == 422 and b["error"] == "cannot_straighten" and b["reason"] == "too_small" and "image" not in b


@pytest.mark.parametrize("source", ["0" * 16, None, "missing", 5])
def test_route_refuses_corners_not_bound_to_this_photo(source, monkeypatch):
    img, q = opening_photo()
    corners, _, _ = canonical_corners(img, q)
    monkeypatch.setattr(op, "warp", lambda *a, **k: pytest.fail("no warp for unbound corners"))
    body = {"photo": jpeg(img), "corners": corners}
    if source != "missing":
        body["source"] = source
    s, b = call(ev(body))
    assert s == 409 and b["error"] == "source_mismatch" and "image" not in b


def test_corners_for_a_replaced_photo_are_refused(monkeypatch):
    img, q = opening_photo()
    corners, source, _ = canonical_corners(img, q)
    other, _ = opening_photo(lines=(0.4,))
    monkeypatch.setattr(op, "warp", lambda *a, **k: pytest.fail("no warp"))
    s, b = call(ev({"photo": jpeg(other), "corners": corners, "source": source}))
    assert s == 409


@pytest.mark.parametrize("corners", [[[10 ** 400, 1], [2, 3], [4, 5], [6, 7]], [[1, 2, 3], [4, 5, 6]], "abc", [[None, 1]] * 4])
def test_malformed_corners_are_refused_cleanly(corners, capsys):
    img, q = opening_photo()
    _, source, _ = canonical_corners(img, q)
    s, b = call(ev({"photo": jpeg(img), "corners": corners, "source": source}))
    assert s == 422 and b["error"] == "cannot_straighten" and "image" not in b
    assert "400" not in capsys.readouterr().out.replace('"ms"', "")


class Ctx:
    def __init__(self, ms):
        self.ms = ms

    def get_remaining_time_in_millis(self):
        return self.ms


def test_no_time_left_refuses_before_any_work(monkeypatch):
    img, q = opening_photo()
    monkeypatch.setattr(op, "propose", lambda *a, **k: pytest.fail("no contour search without time"))
    r = h.handler(ev({"photo": jpeg(img)}), Ctx(500), is_enabled=lambda: True)
    assert r["statusCode"] == 503 and json.loads(r["body"])["error"] == "out_of_time"


def test_time_running_out_before_the_warp_stops_there(monkeypatch):
    img, q = opening_photo()
    corners, source, _ = canonical_corners(img, q)
    t = iter([0.0, 0.0, 100.0, 100.0, 100.0])
    monkeypatch.setattr(h.time, "monotonic", lambda: next(t, 100.0))
    monkeypatch.setattr(op, "warp", lambda *a, **k: pytest.fail("no warp after the budget"))
    r = h.handler(ev({"photo": jpeg(img), "corners": corners, "source": source}), Ctx(10_000), is_enabled=lambda: True)
    assert r["statusCode"] == 503 and json.loads(r["body"])["error"] == "out_of_time"


def test_route_is_switched_off_with_the_owner_switch():
    img, _ = opening_photo()
    s, b = call(ev({"photo": jpeg(img)}), is_enabled=lambda: False)
    assert s == 503 and b["error"] == "paused"


def test_route_refuses_what_is_not_a_photo():
    s, b = call(ev({"photo": base64.b64encode(b"not a jpeg").decode()}))
    assert s == 400 and b["error"] == "bad_photo"


def test_route_logs_no_coordinates(capsys):
    img, q = opening_photo()
    corners, source, _ = canonical_corners(img, q)
    capsys.readouterr()
    call(ev({"photo": jpeg(img), "corners": corners, "source": source}))
    out = capsys.readouterr().out
    assert "straighten" in out and str(int(q[0][0])) not in out.replace('"ms"', "")


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_time_running_out_inside_the_warp_publishes_nothing(monkeypatch):
    img, q = opening_photo()
    corners, source, _ = canonical_corners(img, q)
    clock = Clock()
    monkeypatch.setattr(h.time, "monotonic", clock)
    real = op.warp

    def slow_warp(*a, **k):
        clock.t = 9.0
        return real(*a, **k)
    monkeypatch.setattr(op, "warp", slow_warp)
    monkeypatch.setattr(op, "snap_targets", lambda *a, **k: pytest.fail("no targets after the budget"))
    r = h.handler(ev({"photo": jpeg(img), "corners": corners, "source": source}), Ctx(10_000), is_enabled=lambda: True)
    assert r["statusCode"] == 503 and json.loads(r["body"])["error"] == "out_of_time" and "image" not in r["body"]


def test_time_running_out_inside_the_contour_search_publishes_nothing(monkeypatch):
    img, _ = opening_photo()
    clock = Clock()
    monkeypatch.setattr(h.time, "monotonic", clock)
    real = op.propose

    def slow_propose(im, alive=None):
        clock.t = 9.0
        return real(im, alive)
    monkeypatch.setattr(op, "propose", slow_propose)
    r = h.handler(ev({"photo": jpeg(img)}), Ctx(10_000), is_enabled=lambda: True)
    assert r["statusCode"] == 503 and json.loads(r["body"])["error"] == "out_of_time"


def test_the_contour_search_stops_when_told():
    img, _ = opening_photo()
    assert op.propose(img, alive=lambda: False) is None
