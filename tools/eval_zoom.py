"""Label-conflict diagnostic: how often the zoom pass flags a wrong first reading, from one set of runs and a
person's annotations. Not an end-to-end inventory measure: neither arm files anything without a person's
confirmation, and only labels of proposed items are judged.

    uv run python tools/eval_zoom.py RUN_DIR

"Without zoom" is the first reading as the model gave it; "with zoom" is the same run's flags (one run gives both,
so the model's randomness is held equal). Coverage is reported against every eligible labelled reading; an
unannotated set is marked PARTIAL. Items marked "unsure" are reported and left out of the rates. Items the model
never listed are outside this measure.
"""

import json
import sys
from collections import Counter
from pathlib import Path


def eligible_keys(run: Path) -> list[str]:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.annotate import items_to_annotate
    return [x["key"] for x in items_to_annotate(run) if x["field"] == "label"]


def main(run: Path):
    ann = json.loads((run / "annotations.json").read_text())
    valid = {"first", "close-up", "both", "neither", "unsure"}
    bad = [k for k, v in ann.items() if v not in valid]
    if bad:
        sys.exit(f"invalid annotation values for {len(bad)} keys, e.g. {bad[:3]}")
    eligible = eligible_keys(run)
    missing = [k for k in eligible if k not in ann]
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
        # The decision without the zoom pass: the same reasons minus the ones the zoom pass added.
        base_asks = [w for w in r["why"] if not w.startswith(("label_conflict:", "count_conflict:"))]
        obs = {(o["item_id"], o["field"]): o for o in (r.get("zoom") or {}).get("observations", [])}
        for it in (r.get("proposal") or {}).get("items", []):
            o = obs.get((it.get("id"), "label"))
            key = f"{f.stem}|{it.get('id')}|label"
            if key in ann:
                rows.append({"truth": ann[key], "outcome": o["outcome"] if o else "not_re_read",
                             "scan_already_asked": bool(base_asks)})
    judged = [x for x in rows if x["truth"] != "unsure"]
    first_wrong = [x for x in judged if x["truth"] in ("close-up", "neither")]
    first_right = [x for x in judged if x["truth"] in ("first", "both")]
    flagged = [x for x in first_wrong if x["outcome"] == "conflict"]
    print(f"scans {scans}")
    print(f"coverage: eligible labelled readings {len(eligible)}, annotated {len(eligible) - len(missing)}, "
          f"unannotated {len(missing)}, unsure {len(rows) - len(judged)}, scored {len(judged)}")
    if missing:
        print("PARTIAL: some readings are not annotated; this is not a complete result and decides nothing.")
    print(f"wrong first readings: {len(first_wrong)} of {len(judged)} scored")
    print(f"  flagged by the zoom pass (label conflict): {len(flagged)} "
          f"(in scans that asked nothing else: {sum(1 for x in flagged if not x['scan_already_asked'])})")
    print(f"  not flagged: {len(first_wrong) - len(flagged)} "
          f"(never re-read: {sum(1 for x in first_wrong if x['outcome'] == 'not_re_read')})")
    print(f"false flags (first reading right, zoom flagged it): "
          f"{sum(1 for x in first_right if x['outcome'] == 'conflict')} of {len(first_right)}")
    print(f"model cost per scan: without zoom ${cost_off / max(scans, 1):.3f}  with zoom ${cost_on / max(scans, 1):.3f}")
    ms_off.sort(), ms_on.sort()
    if scans:
        print(f"median seconds to a result: without zoom {ms_off[scans // 2] / 1000:.1f}  with zoom {ms_on[scans // 2] / 1000:.1f}")
    print("detail (truth, outcome):", dict(sorted(Counter((x['truth'], x['outcome']) for x in rows).items())))
    print("Not measured here: items the model never listed, counts, and the person's final corrected list.")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
