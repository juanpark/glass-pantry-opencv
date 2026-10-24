"""Record the front page's looping example: one before/after pair of a shelf and this engine's answer for it.

    uv run python tools/make_change_sample.py BEFORE.jpg AFTER.jpg SCAN.json

SCAN.json is a recorded shelf reading of BEFORE (the live engine's result). OpenCV only: no model call. Writes
web/samples/change/{before.jpg, after.jpg, change.json}; the photos are the engine's reduced copies (long edge 1568).
Only a pair the owner has approved for publishing goes here.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from verifier import frames, rescan  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "web" / "samples" / "change"


def main(before: Path, after: Path, scan: Path):
    old, new = frames.canonical(before.read_bytes()), frames.canonical(after.read_bytes())
    items = [{"id": it["id"], "box": it["box"]} for it in (json.loads(scan.read_text())["proposal"] or {}).get("items", [])
             if isinstance(it.get("box"), list) and len(it["box"]) == 4]
    res = rescan.run(old.jpeg, items, new.jpeg, None, max_reads=0)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "before.jpg").write_bytes(old.jpeg)
    (OUT / "after.jpg").write_bytes(new.jpeg)
    (OUT / "change.json").write_text(json.dumps({"res": res, "items": [{"pid": i["id"], "box": i["box"]} for i in items]},
                                                default=str) + "\n")
    print(res["action"], [(o["id"], o["outcome"]) for o in res["items"]])


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:4]))
