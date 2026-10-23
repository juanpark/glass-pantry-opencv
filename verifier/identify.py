"""Which fridge is this? (plan v4 slice 4, IDEAS I-69.) The model only reads a photo of the fridge or its rating
sticker; plain code below matches that reading to Glass Pantry's catalogue, so the model never picks a row.

Order: the exact model code → a sibling code of the same brand → the generic layout of the same kind, then library
models of that kind (same brand first). Nothing readable suggests nothing. The person always confirms.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KINDS = ("bottom_freezer", "top_freezer", "side_by_side", "four_door", "one_door", "kimchi_stand", "kimchi_chest")
KIND_EN = {"bottom_freezer": "fridge on top, freezer below", "top_freezer": "freezer on top, fridge below",
           "side_by_side": "side-by-side doors", "four_door": "four doors", "one_door": "a single door",
           "kimchi_stand": "a standing kimchi fridge", "kimchi_chest": "a chest (lid) kimchi fridge"}
BRANDS = {"삼성": "samsung", "samsung": "samsung", "lg": "lg", "엘지": "lg", "위니아": "winia", "winia": "winia",
          "딤채": "winia", "dimchae": "winia"}
SUFFIXES = {"EF", "EU"}  # market suffixes after a slash that do not change the model (RB38J7215SA/EF); others are kept
FAMILY = 7  # characters of shared code prefix that make a sibling (RB38J72… ~ RB38J72…); RB3… is not enough

PROMPT = """This photo shows a refrigerator, a kimchi refrigerator, or the rating sticker / label of one.
Reply with exactly one JSON object and nothing else:
{"model_code": "...", "brand": "...", "kind": "...", "evidence": "..."}

- model_code: the model number exactly as printed (on a rating sticker, a badge or a label), or null if none is
  readable. Never guess one from the look of the appliance.
- brand: the maker as printed or as shown by its logo, or null.
- kind: one of bottom_freezer (fridge on top, freezer drawers below), top_freezer (freezer door on top),
  side_by_side (two tall doors), four_door (fridge doors on top, two freezer doors below), one_door, kimchi_stand
  (standing kimchi fridge with drawers), kimchi_chest (lid on top), or unknown. From a sticker alone, use what it
  states (for example 상냉장 하냉동 = bottom_freezer) or unknown.
- evidence: under 20 words, what you read or saw."""


def load_rows() -> list[dict]:
    return json.loads((ROOT / "web" / "layouts" / "layouts.json").read_text(encoding="utf-8"))


def row(rows, key):
    return next((r for r in rows if r["key"] == key), None)


def kind_of(r: dict) -> str:
    """The catalogue row's kind, from its compartments' kinds and boxes (box = x, y, z, w, h, d; y up)."""
    comps = r["compartments"]
    kinds = {c["kind"] for c in comps}
    if "well" in kinds:
        return "kimchi_chest"
    if "drawerBin" in kinds:
        return "kimchi_stand"
    if len(comps) == 1:
        return "one_door"
    by = {c["kind"]: c["box"] for c in comps}
    cold, frz = by.get("cold"), by.get("freezer")
    if cold and frz:
        if abs(cold[1] - frz[1]) < 1e-6:
            return "side_by_side"
        if frz[1] > cold[1]:
            return "top_freezer"
        return "four_door" if "convertible" in kinds else "bottom_freezer"
    return "unknown"


def norm_code(s) -> str | None:
    if not isinstance(s, str):
        return None
    s = re.sub(r"[\s\-_.]", "", s).upper()
    base, _, suffix = s.partition("/")
    s = base if suffix in SUFFIXES else s
    return s or None


def code_of(r: dict) -> str | None:
    m = re.search(r"\(([^)]+)\)\s*$", r.get("model") or "")
    return norm_code(m.group(1)) if m else None


def brand_of(s) -> str | None:
    return BRANDS.get(s.strip().lower()) if isinstance(s, str) and s.strip() else None


BRAND_EN = {"samsung": "Samsung", "lg": "LG", "winia": "Winia"}


def _name(r):
    """ "Samsung RB38J7200S4": brand and code, the way the picker shows them."""
    return f'{BRAND_EN.get(brand_of(r.get("brand")), r.get("brand") or "")} {code_of(r) or r["key"]}'.strip()


def suggest(reading: dict, rows: list[dict]) -> list[dict]:
    """Ranked suggestions, each {key, match: exact|family|kind, reason}. Empty when nothing usable was read."""
    code, brand, kind = norm_code(reading.get("model_code")), brand_of(reading.get("brand")), reading.get("kind")
    out, seen = [], set()

    def add(r, match, reason):
        if r["key"] not in seen:
            seen.add(r["key"])
            out.append({"key": r["key"], "match": match, "reason": reason})

    models = [r for r in rows if not r["key"].startswith("template:")]
    if code:
        # a maker we know that differs from the row's means a misread code or a mislabelled sticker: never "exact"
        models_ok = [r for r in models if not (brand and brand_of(r.get("brand")) and brand_of(r.get("brand")) != brand)]
        for r in models_ok:
            if code_of(r) == code:
                add(r, "exact", f"The model number {code} matches {_name(r)}.")
        for r in models_ok:
            c = code_of(r)
            if c and brand and brand_of(r.get("brand")) == brand and len(_prefix(c, code)) >= FAMILY:
                add(r, "family", f"{code} is not in the list, but {c} is the same family ({_prefix(c, code)}…).")
    seen_kind = kind in KINDS
    if not seen_kind and out:  # a sticker gave the code but not the kind: the matched row's kind
        kind = kind_of(row(rows, out[0]["key"]))
    if kind not in KINDS:
        return out
    if not seen_kind:
        why = f"{_name(row(rows, out[0]['key']))} has {KIND_EN[kind]}."
    else:
        why = f"It looks like {KIND_EN[kind]}" + (f" and {code} is not in the list." if code and not out else ".")
    for r in rows:
        if r["key"].startswith("template:") and kind_of(r) == kind:
            add(r, "kind", why + " This is the generic layout of that kind; trace fits it to your fridge.")
    same = sorted((r for r in models if kind_of(r) == kind), key=lambda r: brand_of(r.get("brand")) != brand)
    for r in same:
        add(r, "kind", why + f" {_name(r)} is a library fridge of that kind.")
    return out


def _prefix(a, b):
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return a[:n]


def read_answer(text: str, stop: str) -> dict | None:
    """The model's reading, or None when it was cut off, refused, or not one JSON object. Fields of the wrong type
    are dropped, never coerced."""
    if stop != "end_turn":
        return None
    t = (text or "").strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", t, re.S)  # one object in a code fence is still one object
    try:
        v = json.loads(fence.group(1) if fence else t)
    except ValueError:
        return None  # prose around it, a second object, trailing text: not one object
    if not isinstance(v, dict):
        return None
    s = lambda k: v.get(k).strip() if isinstance(v.get(k), str) and v.get(k).strip() else None
    kind = v.get("kind") if v.get("kind") in KINDS else "unknown"
    return {"model_code": s("model_code"), "brand": s("brand"), "kind": kind, "evidence": (s("evidence") or "")[:200]}
