import base64
import json

import pytest

from service import handler as h


def ev(method, path, body=b"", ctype="image/jpeg"):
    return {"rawPath": path, "requestContext": {"http": {"method": method}}, "headers": {"content-type": ctype},
            "body": base64.b64encode(body).decode(), "isBase64Encoded": True}


def call(e, **kw):
    kw.setdefault("is_enabled", lambda: True)
    kw.setdefault("admitter", lambda: True)
    kw.setdefault("key", lambda: "k")
    kw.setdefault("scanner", lambda j, k, **_: {"action": "file", "why": [], "trace": [], "proposal": {}, "model_calls": 1})
    r = h.handler(e, **kw)
    return r["statusCode"], (json.loads(r["body"]) if r["headers"]["content-type"] == "application/json" else r["body"])


def test_switched_off_refuses_before_reading_or_counting():
    spent = []
    s, b = call(ev("POST", "/scan", b"x"), is_enabled=lambda: False, admitter=lambda: spent.append(1) or True,
                scanner=lambda j, k, **_: pytest.fail("no scan when off"))
    assert s == 503 and b["error"] == "paused" and spent == []


def test_daily_limit_stops_before_the_model():
    s, b = call(ev("POST", "/scan", real_jpeg()), admitter=lambda: False, scanner=lambda j, k, **_: pytest.fail("no scan"))
    assert s == 429 and b["error"] == "daily_limit"


def test_too_large_is_refused_before_counting():
    s, _ = call(ev("POST", "/scan", b"x" * (h.MAX_BYTES + 10)), admitter=lambda: pytest.fail("not counted"))
    assert s in (400, 413)


def test_a_model_failure_returns_no_model_text(capsys):
    def boom(j, k, **_):
        raise RuntimeError("secret model text 서울우유")
    s, b = call(ev("POST", "/scan", real_jpeg()), scanner=boom)
    assert s == 502 and "서울우유" not in json.dumps(b) and "서울우유" not in capsys.readouterr().out


def test_logs_carry_no_labels(capsys):
    res = {"action": "ask", "why": ["label_conflict:i1"], "trace": [], "model_calls": 2, "cost_usd": 0.1,
           "proposal": {"items": [{"label": "서울우유"}]}}
    s, _ = call(ev("POST", "/scan", real_jpeg()), scanner=lambda j, k, **_: res)
    out = capsys.readouterr().out
    assert s == 200 and "서울우유" not in out and "label_conflict" not in out


def test_json_upload_is_accepted():
    got = []
    body = json.dumps({"photo": base64.b64encode(real_jpeg()).decode()}).encode()
    call(ev("POST", "/scan", body, "application/json"), scanner=lambda j, k, **_: got.append(j) or
         {"action": "file", "why": [], "trace": [], "proposal": {}})
    assert got == [real_jpeg()]


class FakeTable:
    def __init__(self):
        self.n = {}

    def update_item(self, Key, ConditionExpression, ExpressionAttributeValues, **kw):
        from botocore.exceptions import ClientError
        cur = self.n.get(Key["day"])
        if cur is not None and cur >= ExpressionAttributeValues[":cap"]:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")
        self.n[Key["day"]] = (cur or 0) + 1


def test_admission_is_a_shared_daily_cap(monkeypatch):
    monkeypatch.setattr(h, "DAILY_SCANS", 3)
    t = FakeTable()
    day1 = [h.admit(t, now=1_800_000_000) for _ in range(5)]
    assert day1 == [True, True, True, False, False]
    assert h.admit(t, now=1_800_000_000 + 86400)  # a new day starts fresh


def test_an_unreadable_counter_fails_closed():
    def broken():
        raise RuntimeError("table missing")
    s, b = call(ev("POST", "/scan", real_jpeg()), admitter=broken, scanner=lambda j, k, **_: pytest.fail("no scan uncounted"))
    assert s == 503 and b["error"] == "limit_unavailable"


def real_jpeg():
    from tests.synth import shelf
    import cv2
    return cv2.imencode(".jpg", shelf())[1].tobytes()


def test_not_a_photo_is_refused_before_counting_with_the_real_scanner():
    s, b = call(ev("POST", "/scan", b"x"), scanner=h.scan_photo, admitter=lambda: pytest.fail("not counted"))
    assert s == 400 and b["error"] == "bad_photo"


def test_switched_off_with_the_real_scanner_is_503():
    s, b = call(ev("POST", "/scan", b"x"), is_enabled=lambda: False, scanner=h.scan_photo)
    assert s == 503 and b["error"] == "paused"


def test_the_lambda_time_budget_reaches_the_scanner():
    got = {}

    class Ctx:
        def get_remaining_time_in_millis(self):
            return 60_000

    def sc(j, k, deadline=None):
        got["d"] = deadline
        return {"action": "file", "why": [], "trace": [], "proposal": {}}
    import time
    t = time.monotonic()
    h.handler(ev("POST", "/scan", real_jpeg()), Ctx(), scanner=sc, is_enabled=lambda: True,
              admitter=lambda: True, key=lambda: "k")
    assert 55 < got["d"] - t <= 60.5


def test_a_photo_too_big_to_decode_is_refused_before_counting():
    import struct
    import zlib

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 40000, 40000, 8, 2, 0, 0, 0)) + chunk(b"IEND", b"")
    s, b = call(ev("POST", "/scan", png), scanner=lambda j, k, **_: pytest.fail("no scan"),
                admitter=lambda: pytest.fail("not counted"))
    assert s == 400 and b["error"] == "bad_photo"


# /rescan: OpenCV first; an admission only when a crop must be read


def _rescan_body(old, new, items):
    import cv2
    enc = lambda im: base64.b64encode(cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()).decode()
    return json.dumps({"old": enc(old), "photo": enc(new), "items": items}).encode()


def _pair(add=False):
    import cv2
    from tests.synth import shelf
    from tests.test_change import reshoot
    old = shelf(seed=3)
    new, _ = reshoot(old)
    if add:
        cv2.rectangle(new, (1150, 140), (1400, 260), (20, 200, 240), -1)
    return old, new


ITEMS = [{"id": "a", "box": [300, 420, 460, 640]}, {"id": "b", "box": [900, 760, 1060, 980]}]


def test_rescan_switched_off_does_nothing():
    s, b = call(ev("POST", "/rescan", b"{}", "application/json"), is_enabled=lambda: False,
                rescanner=lambda *a, **k: pytest.fail("no rescan when off"))
    assert s == 503 and b["error"] == "paused"


@pytest.mark.parametrize("items", [None, "x", [{"id": "a"}], [{"id": "a", "box": [1, 2, 0, 5]}],
                                   [{"id": "", "box": [0, 0, 5, 5]}], [{"id": "a", "box": [0, 0, float("inf"), 5]}]])
def test_rescan_refuses_malformed_items_before_any_work(items):
    old, new = _pair()
    body = _rescan_body(old, new, items).replace(b"Infinity", b"1e999")
    s, _ = call(ev("POST", "/rescan", body, "application/json"), rescanner=lambda *a, **k: pytest.fail("not run"))
    assert s == 400


def test_rescan_with_nothing_changed_spends_no_admission_and_no_model_call():
    old, new = _pair()
    s, b = call(ev("POST", "/rescan", _rescan_body(old, new, ITEMS), "application/json"),
                admitter=lambda: pytest.fail("nothing to read, nothing counted"))
    assert s == 200 and b["action"] == "file" and b["model_calls"] == 0 and b["counted"] is False, b


def test_rescan_counts_once_and_reads_only_the_new_region(monkeypatch, capsys):
    from verifier import claude
    from verifier.scan import Proposal
    sent = []

    def fake(self, jpeg):
        sent.append(jpeg)
        return Proposal([], [{"id": "i1", "label": "서울우유", "box": [5, 5, 50, 50]}], "m", {"cost": 0.01})

    monkeypatch.setattr(claude.ClaudeProposer, "propose", fake)
    spent = []
    old, new = _pair(add=True)
    s, b = call(ev("POST", "/rescan", _rescan_body(old, new, ITEMS), "application/json"),
                admitter=lambda: spent.append(1) or True)
    assert s == 200 and b["action"] == "ask" and len(spent) == 1 and len(sent) == 1 and b["model_calls"] == 1, b
    assert "서울우유" not in capsys.readouterr().out


def test_rescan_at_the_daily_limit_still_answers_with_the_region_unread(monkeypatch):
    from verifier import claude
    monkeypatch.setattr(claude.ClaudeProposer, "propose", lambda self, j: pytest.fail("no call over the limit"))
    old, new = _pair(add=True)
    s, b = call(ev("POST", "/rescan", _rescan_body(old, new, ITEMS), "application/json"), admitter=lambda: False)
    assert s == 200 and b["action"] == "ask" and b["new"][0]["unread"] == "daily_limit" and b["counted"] is False, b
