"""The vision model behind the loop: Claude over the Messages API, with no SDK (urllib only).

Settings are the Glass Pantry app's: model claude-opus-5-5, effort low, max 8192 output tokens. The image block
asks the API to refuse rather than silently resize an oversized image, since a resize would shift every
coordinate the model returns.
"""

import base64
import json
import os
import time
import urllib.error
import urllib.request

from . import prompt
from .scan import Proposal

URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-opus-5-5"
EFFORT = "low"
PRICE = {"claude-opus-5-5": (4.0, 20.0)}  # USD per million input / output tokens (platform.claude.com pricing, 10/2026)
TIMEOUT = 120


class ModelError(Exception):
    pass


def call(content: list, key: str | None = None, model: str = MODEL, max_tokens: int = 8192) -> dict:
    key = key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ModelError("no API key")
    body = {"model": model, "max_tokens": max_tokens, "output_config": {"effort": EFFORT},
            "messages": [{"role": "user", "content": content}]}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.load(r)
            rid = r.headers.get("request-id")
    except urllib.error.HTTPError as e:  # one attempt only: a retry is a new, separately budgeted call
        raise ModelError(f"http {e.code}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise ModelError(type(e).__name__) from None
    u = d.get("usage", {})
    pin, pout = PRICE.get(model, (0.0, 0.0))
    text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
    return {"text": text, "stop": d.get("stop_reason"), "request_id": rid,
            "ms": round((time.time() - t0) * 1000), "in": u.get("input_tokens", 0), "out": u.get("output_tokens", 0),
            "cost": round(u.get("input_tokens", 0) / 1e6 * pin + u.get("output_tokens", 0) / 1e6 * pout, 5)}


def image_block(jpeg: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(jpeg).decode()},
            "transformations": {"oversized_image": "error"}}


def parse_array(text: str) -> list | None:
    """The app's answer is a JSON array of objects. Returns the complete objects, or None if there is no array.

    A truncated answer keeps every object that closed; the half-written last one is dropped, never guessed.
    """
    start = text.find("[")
    if start < 0:
        return None
    dec, i, out = json.JSONDecoder(), start + 1, []
    while i < len(text):
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1
        if i >= len(text) or text[i] == "]":
            break
        try:
            v, i = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            break
        out.append(v)
    return out


def parse_object(text: str) -> dict | None:
    start = text.find("{")
    if start < 0:
        return None
    try:
        v, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        return None
    return v if isinstance(v, dict) else None


def split(elements: list, h: int) -> tuple[list[float], list[dict]]:
    """Shelf lines (front-edge y / height, one per shelf_edge) and the items, from the app's element stream."""
    lines, items = [], []
    for e in elements:
        if not isinstance(e, dict):
            continue
        if "shelf_edge" in e:
            f = e.get("front")
            if isinstance(f, list) and len(f) == 3 and all(isinstance(v, (int, float)) for v in f) and h:
                lines.append(round(f[1] / h, 4))
        elif "id" in e:
            items.append(e)
    return lines, items


class ClaudeProposer:
    def __init__(self, key: str | None = None):
        self.key = key

    def propose(self, jpeg: bytes) -> Proposal:
        from .frames import decode
        img = decode(jpeg)
        h, w = img.shape[:2]
        r = call([image_block(jpeg), {"type": "text", "text": prompt.contents(w, h)}], self.key)
        elements = parse_array(r["text"]) or []
        lines, items = split(elements, h)
        raw = {k: r[k] for k in ("request_id", "ms", "in", "out", "cost", "stop")}
        raw["prompt"] = prompt.VERSION
        return Proposal(shelf_lines=lines, items=items, model=MODEL, raw=raw)


class ClaudeAsker:
    """The zoom pass's narrow re-read. Returns the parsed answer, or None for a refusal or malformed reply."""

    def __init__(self, key: str | None = None):
        self.key, self.log = key, []

    def ask(self, crop_jpeg: bytes, fields, target) -> dict | None:
        from .zoom import ASK_PROMPT
        cw, ch, x0, y0, x1, y1 = target
        text = ASK_PROMPT.format(cw=cw, ch=ch, x0=x0, y0=y0, x1=x1, y1=y1)
        r = call([image_block(crop_jpeg), {"type": "text", "text": text}], self.key, max_tokens=400)
        self.log.append({k: r[k] for k in ("request_id", "ms", "in", "out", "cost", "stop")})
        return parse_object(r["text"])
