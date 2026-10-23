"""The engine on AWS Lambda behind a Function URL: one page, one sample, one scan route.

Guards, all on the server (the page cannot switch any of them off):
- the owner's switch: Parameter Store /glass-pantry-opencv/enabled must say "on", or live scans are refused;
- a shared daily cap: one atomic DynamoDB counter per UTC day, checked before any model call;
- size limits on the upload; the zoom pass's crop budget is fixed in the engine.
Nothing about a photo is logged: no image, no crop, no label, no model text. Logs carry codes and numbers only.
"""

import base64
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 5_500_000  # Function URL requests stop at 6 MB, base64 included
DAILY_SCANS = int(os.environ.get("DAILY_SCANS", "40"))
TABLE = os.environ.get("TABLE", "glass-pantry-opencv-calls")
KEY_PARAM = os.environ.get("KEY_PARAM", "/glass-pantry-opencv/anthropic-api-key")
ENABLED_PARAM = os.environ.get("ENABLED_PARAM", "/glass-pantry-opencv/enabled")
ENGINE = os.environ.get("ENGINE_SHA", "dev")

_cache: dict = {}


def _ssm():
    if "ssm" not in _cache:
        import boto3
        _cache["ssm"] = boto3.client("ssm")
    return _cache["ssm"]


def enabled() -> bool:
    hit = _cache.get("enabled")
    if hit and time.time() - hit[1] < 30:  # the switch takes effect within 30 s
        return hit[0]
    try:
        v = _ssm().get_parameter(Name=ENABLED_PARAM)["Parameter"]["Value"].strip().lower() == "on"
    except Exception:
        v = False  # cannot read the switch: treat as off
    _cache["enabled"] = (v, time.time())
    return v


def api_key() -> str:
    if "key" not in _cache:
        _cache["key"] = _ssm().get_parameter(Name=KEY_PARAM, WithDecryption=True)["Parameter"]["Value"].strip()
    return _cache["key"]


def admit(table=None, now=None) -> bool:
    """Take one scan from today's shared allowance, atomically. False when the day's allowance is used up."""
    import boto3
    from botocore.exceptions import ClientError
    t = table or boto3.resource("dynamodb").Table(TABLE)
    now = now or time.time()
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    try:
        t.update_item(
            Key={"day": day},
            UpdateExpression="ADD scans :one SET expires = :exp",
            ConditionExpression="attribute_not_exists(scans) OR scans < :cap",
            ExpressionAttributeValues={":one": 1, ":cap": DAILY_SCANS, ":exp": int(now) + 8 * 86400})
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _resp(status, body, ctype="application/json"):
    if ctype == "application/json":
        body = json.dumps(body, ensure_ascii=False, default=str)
    return {"statusCode": status, "headers": {"content-type": ctype, "cache-control": "no-store",
                                              "x-content-type-options": "nosniff"}, "body": body}


def _log(**kv):
    print(json.dumps({"engine": ENGINE, **kv}))  # codes and numbers only


def _photo(event) -> bytes | None:
    body = event.get("body") or ""
    raw = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode("latin-1")
    ctype = (event.get("headers") or {}).get("content-type", "")
    if ctype.startswith("application/json"):
        try:
            raw = base64.b64decode(json.loads(raw)["photo"])
        except Exception:
            return None
    return raw


def scan_photo(jpeg: bytes, key: str, deadline: float | None = None) -> dict:
    """At most 1 full read + 4 close-ups + 4 label judgements = 9 model calls per admitted scan, all inside the
    request's time budget: no model request outlives the Lambda, and re-reads not started in time stay unresolved."""
    from verifier import claude, scan, zoom
    asker, judge = claude.ClaudeAsker(key, deadline), claude.LabelJudge(key, deadline)
    res = scan.run(jpeg, claude.ClaudeProposer(key, deadline), zoomer=zoom.Zoomer(asker, judge=judge, deadline=deadline))
    res["mode"] = "LIVE"
    res["model_calls"] = (1 if res["proposal"] else 0) + len(asker.log) + len(judge.log)
    res["cost_usd"] = round(sum(s.get("cost", 0) for s in res["trace"] if s["step"] == "propose")
                            + sum(x["cost"] for x in asker.log + judge.log), 4)
    return res


STRAIGHTEN_RESERVE = 2.0  # seconds kept to encode and return the answer
STRAIGHTEN_MIN = 1.5  # a stage does not start with less than this left


def straighten(event, is_enabled, context=None) -> dict:
    """Step 3 of plan v4: OpenCV only, no model call, not counted. Without corners it *suggests* four (never
    accepts them); with the person's corners it straightens the opening plane and offers snap targets. Corners are
    in the canonical frame's pixels and must carry the `source` of that frame."""
    t0 = time.time()
    deadline = (time.monotonic() + context.get_remaining_time_in_millis() / 1000 - STRAIGHTEN_RESERVE
                if context else None)

    def out_of_time() -> bool:
        return deadline is not None and deadline - time.monotonic() < STRAIGHTEN_MIN

    if out_of_time():
        _log(route="straighten", result="out_of_time")
        return _resp(503, {"error": "out_of_time", "message": "The engine ran out of time. Please try again."})
    if not is_enabled():
        _log(route="straighten", result="paused")
        return _resp(503, {"error": "paused", "message": "The live page is switched off. Try the recorded sample."})
    if len(event.get("body") or "") > MAX_BYTES * 4 // 3 + 1024:
        return _resp(413, {"error": "too_large"})
    try:
        raw = event.get("body") or ""
        req = json.loads(base64.b64decode(raw) if event.get("isBase64Encoded") else raw)
        jpeg = base64.b64decode(req["photo"])
    except Exception:
        return _resp(400, {"error": "bad_photo"})
    from verifier import frames, opening
    import hashlib
    f = frames.canonical(jpeg) if len(jpeg) <= MAX_BYTES else None
    if f is None:
        return _resp(400, {"error": "bad_photo", "message": "That file is not a photo this page can read."})
    w, h = f.size
    source = hashlib.sha256(f.jpeg).hexdigest()[:16]
    corners = req.get("corners") if isinstance(req, dict) else None
    if corners is None:
        if out_of_time():
            _log(route="straighten", result="out_of_time")
            return _resp(503, {"error": "out_of_time", "message": "The engine ran out of time. Please try again."})
        q = opening.propose(f.image)
        kind = "contour" if q is not None else "margin"
        q = q if q is not None else opening.fallback(w, h)
        _log(route="straighten", result="suggested", kind=kind, ms=round((time.time() - t0) * 1000))
        return _resp(200, {"status": "suggested", "suggestion": kind, "corners": [[round(x, 1), round(y, 1)] for x, y in q],
                           "size": [w, h], "source": source})
    if req.get("source") != source:  # corners without their photo's binding are never applied
        _log(route="straighten", result="source_mismatch")
        return _resp(409, {"error": "source_mismatch", "message": "These corners belong to another photo."})
    reason = opening.validate(corners, w, h)
    if reason:
        _log(route="straighten", result="refused", reason=reason)
        return _resp(422, {"error": "cannot_straighten", "reason": reason,
                           "message": "Can't straighten with these corners. Move them, or trace on the photo instead."})
    if out_of_time():
        _log(route="straighten", result="out_of_time")
        return _resp(503, {"error": "out_of_time", "message": "The engine ran out of time. Please try again."})
    import cv2
    wp = opening.warp(f.image, corners)
    ok, buf = cv2.imencode(".jpg", wp.image, [cv2.IMWRITE_JPEG_QUALITY, 88])
    _log(route="straighten", result="straightened", ms=round((time.time() - t0) * 1000))
    return _resp(200, {"status": "straightened", "image": base64.b64encode(buf.tobytes()).decode(),
                       "image_size": [wp.image.shape[1], wp.image.shape[0]], "matrix": wp.matrix.tolist(),
                       "targets": opening.snap_targets(wp.image), "size": [w, h], "source": source})


def handler(event, context=None, *, scanner=scan_photo, admitter=admit, is_enabled=enabled, key=api_key):
    http = (event.get("requestContext") or {}).get("http") or {}
    method, path = http.get("method", "GET"), event.get("rawPath", "/")
    if method == "GET" and path == "/":
        return _resp(200, (ROOT / "web" / "index.html").read_text(encoding="utf-8"), "text/html; charset=utf-8")
    if method == "GET" and path == "/health":
        from verifier import prompt
        return _resp(200, {"ok": True, "live": is_enabled(), "engine": ENGINE, "prompt": prompt.VERSION,
                           "daily_scans": DAILY_SCANS})
    if method == "GET" and path == "/sample":
        p = ROOT / "web" / "samples" / "sample.json"
        if not p.exists():
            return _resp(404, {"error": "no_sample"})
        return _resp(200, {**json.loads(p.read_text(encoding="utf-8")), "mode": "RECORDED"})
    if method == "POST" and path == "/scan":
        t0 = time.time()
        if not is_enabled():
            _log(route="scan", result="paused")
            return _resp(503, {"error": "paused", "message": "Live scans are switched off. Try the recorded sample."})
        if len(event.get("body") or "") > MAX_BYTES * 4 // 3 + 1024:
            return _resp(413, {"error": "too_large", "message": "Photo too large; the page shrinks photos before sending."})
        jpeg = _photo(event)
        if not jpeg or len(jpeg) > MAX_BYTES:
            return _resp(400, {"error": "bad_photo"})
        from verifier.frames import decode
        if decode(jpeg) is None:  # not a photo: refused before it uses any of today's allowance
            return _resp(400, {"error": "bad_photo", "message": "That file is not a photo this page can read."})
        try:
            ok = admitter()
        except Exception as e:  # the counter cannot be read: fail closed, never scan uncounted
            _log(route="scan", result="admission_error", kind=type(e).__name__)
            return _resp(503, {"error": "limit_unavailable", "message": "Live scans are unavailable right now."})
        if not ok:
            _log(route="scan", result="daily_limit")
            return _resp(429, {"error": "daily_limit", "message": "Today's live scans are used up. Try the recorded sample."})
        deadline = time.monotonic() + context.get_remaining_time_in_millis() / 1000 if context else None
        try:
            res = scanner(jpeg, key(), deadline=deadline)
        except Exception as e:  # never echo model text or photo data
            _log(route="scan", result="error", kind=type(e).__name__, ms=round((time.time() - t0) * 1000))
            return _resp(502, {"error": "model_unavailable"})
        _log(route="scan", result=res["action"], why=len(res["why"]), calls=res.get("model_calls"),
             cost=res.get("cost_usd"), ms=round((time.time() - t0) * 1000))
        return _resp(200, res)
    if method == "GET" and path == "/fridge":
        return _resp(200, (ROOT / "web" / "fridge.html").read_text(encoding="utf-8"), "text/html; charset=utf-8")
    if method == "GET" and path == "/layouts.json":
        return _resp(200, (ROOT / "web" / "layouts" / "layouts.json").read_text(encoding="utf-8"),
                     "application/json; charset=utf-8")
    if method == "POST" and path == "/straighten":
        try:
            return straighten(event, is_enabled, context)
        except Exception as e:  # a malformed request never becomes an invocation failure, and nothing is echoed
            _log(route="straighten", result="error", kind=type(e).__name__)
            return _resp(400, {"error": "bad_request"})
    return _resp(404, {"error": "not_found"})
