"""The zoom pass, off versus on, from one set of runs and a person's annotations.

    uv run python tools/eval_zoom.py RUN_DIR

"Off" is the full reading filed as it came; "on" is the same run with the zoom pass (one run gives both arms, so
the model's randomness is held equal). Counts are over the labelled items a person marked; items marked "unsure"
are reported and left out of the rates. Only items the model proposed are judged: an item it never listed is
outside this measure (stated in the report as a limit).
"""

import json
import sys
from collections import Counter
from pathlib import Path


def main(run: Path):
    ann = json.loads((run / "annotations.json").read_text())
    rows, cost_off, cost_on, ms_off, ms_on, scans = [], 0.0, 0.0, [], [], 0
    for f in sorted(run.glob("*.json")):
        if f.name == "annotations.json":
            continue
        r = json.loads(f.read_text())
        scans += 1
        t = {s["step"]: s for s in r["trace"]}
        read_cost = t.get("propose", {}).get("cost", 0)
        extra = sum(x["cost"] for x in r.get("ask_log", []) + r.get("judge_log", []))
        cost_off += read_cost
        cost_on += read_cost + extra
        ms_off.append(t.get("planes", {}).get("ms", 0))
        ms_on.append(t.get("decide", {}).get("ms", 0))
        obs = {(o["item_id"], o["field"]): o for o in (r.get("zoom") or {}).get("observations", [])}
        for it in (r.get("proposal") or {}).get("items", []):
            o = obs.get((it.get("id"), "label"))
            key = f"{f.stem}|{it.get('id')}|label"
            if key in ann:
                rows.append({"truth": ann[key], "outcome": o["outcome"] if o else "not_re_read",
                             "called": bool(o and not o["note"])})
    c = Counter((x["truth"], x["outcome"]) for x in rows)
    judged = [x for x in rows if x["truth"] != "unsure"]
    first_wrong = [x for x in judged if x["truth"] in ("close-up", "neither")]
    first_right = [x for x in judged if x["truth"] in ("first", "both")]
    caught = [x for x in first_wrong if x["outcome"] in ("conflict",)]
    false_alarm = [x for x in first_right if x["outcome"] == "conflict"]
    print(f"scans {scans}; labelled readings annotated {len(rows)} (unsure {len(rows) - len(judged)})")
    print(f"first reading wrong: {len(first_wrong)} of {len(judged)}")
    print(f"  OFF: filed silently {len(first_wrong)}")
    print(f"  ON : turned into a question {len(caught)}; still silent {len(first_wrong) - len(caught)} "
          f"(of which never re-read {sum(1 for x in first_wrong if x['outcome'] == 'not_re_read')})")
    print(f"false alarms (first was right, ON asked anyway): {len(false_alarm)} of {len(first_right)}")
    print(f"cost per scan: OFF ${cost_off / max(scans, 1):.3f}  ON ${cost_on / max(scans, 1):.3f}")
    ms_off.sort(), ms_on.sort()
    if scans:
        print(f"median seconds to a result: OFF {ms_off[scans // 2] / 1000:.1f}  ON {ms_on[scans // 2] / 1000:.1f}")
    print("detail (truth, outcome):", dict(sorted(c.items())))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
