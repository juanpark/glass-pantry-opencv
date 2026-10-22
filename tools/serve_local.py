"""Serve the page and the handler on localhost for a visual check.

    uv run python tools/serve_local.py [--live] [--sample RESULT.json PHOTO.jpg] [--port 8765]

Without --live, /scan answers from the sample (labelled RECORDED). With --live it calls the model with the key in
.env.local and counts nothing (local only). The sample photo is read from disk and never written anywhere.
"""

import argparse
import base64
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from service import handler as h  # noqa: E402
from tools.run_dev import load_env  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--live", action="store_true")
ap.add_argument("--sample", nargs=2)
ap.add_argument("--port", type=int, default=8765)
a = ap.parse_args()
load_env()
sample = None
if a.sample:
    res = json.loads(Path(a.sample[0]).read_text())
    res["photo"] = "data:image/jpeg;base64," + base64.b64encode(Path(a.sample[1]).read_bytes()).decode()
    sample = res


class S(BaseHTTPRequestHandler):
    def _go(self, method):
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n) if n else b""
        if method == "GET" and self.path == "/sample":
            r = {"statusCode": 200 if sample else 404, "headers": {"content-type": "application/json"},
                 "body": json.dumps({**sample, "mode": "RECORDED"} if sample else {"error": "no_sample"}, ensure_ascii=False)}
        else:
            ev = {"rawPath": self.path, "requestContext": {"http": {"method": method}},
                  "headers": {"content-type": self.headers.get("content-type", "")},
                  "body": base64.b64encode(body).decode(), "isBase64Encoded": True}
            import os
            r = h.handler(ev, is_enabled=lambda: a.live, admitter=lambda: True,
                          key=lambda: os.environ["ANTHROPIC_API_KEY"])
        self.send_response(r["statusCode"])
        for k, v in r["headers"].items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(r["body"].encode())

    def do_GET(self):
        self._go("GET")

    def do_POST(self):
        self._go("POST")


HTTPServer(("127.0.0.1", a.port), S).serve_forever()
