"""Turn one recorded run into the page's "recorded example": the result plus the canonical photo it was read from.

    uv run python tools/make_sample.py RESULT.json PHOTO.jpg OUT.json

Only for a photo its owner has cleared for publication. The photo is embedded at the canonical 1568 px size,
the same image the engine checked, so the overlays line up.
"""

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from verifier import frames  # noqa: E402

res = json.loads(Path(sys.argv[1]).read_text())
f = frames.canonical(Path(sys.argv[2]).read_bytes())
keep = {k: res[k] for k in ("action", "why", "proposal", "zoom", "trace")}
keep["photo"] = "data:image/jpeg;base64," + base64.b64encode(f.jpeg).decode()
keep["recorded"] = {"engine": "see trace", "note": "Recorded with the live engine; replayed without any model call."}
Path(sys.argv[3]).write_text(json.dumps(keep, ensure_ascii=False))
print(f"wrote {sys.argv[3]} ({len(json.dumps(keep)) // 1024} KB)")
