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
