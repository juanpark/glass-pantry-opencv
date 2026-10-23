import hashlib
import json
from pathlib import Path

LAYOUTS = Path(__file__).resolve().parent.parent / "web" / "layouts" / "layouts.json"
# Exported from the Glass Pantry app at commit 6913119 (assets/catalogue/fronts.json sha256 169575b9...) by
# tools/export_layouts_test.dart, which also checks parity with the app's filing destinations. Re-export, never edit.
SHA256 = "38600ae194c9ddbeb25bc490c97a7694522761de35d821ee198018d5fd780006"


def test_the_layout_manifest_is_the_exported_one():
    assert hashlib.sha256(LAYOUTS.read_bytes()).hexdigest() == SHA256


def test_every_holder_id_is_unique_and_namespaced():
    for row in json.loads(LAYOUTS.read_text(encoding="utf-8")):
        ids = [c["id"] for c in row["compartments"]] + [l["id"] for c in row["compartments"] for l in c["levels"]] \
            + [p["id"] for p in row["panels"]] + [q["id"] for p in row["panels"] for q in p["pockets"]]
        assert len(ids) == len(set(ids)), row["key"]
        for p in row["panels"]:
            assert all(q["id"].startswith(p["id"] + "/") for q in p["pockets"])


def test_juans_model_is_offered():
    keys = {r["key"] for r in json.loads(LAYOUTS.read_text(encoding="utf-8"))}
    assert "model:samsung-rb38j-bottom" in keys and {"template:standard", "template:sideBySide"} <= keys


def test_the_page_can_fetch_the_layouts():
    from service import handler as h
    r = h.handler({"rawPath": "/layouts.json", "requestContext": {"http": {"method": "GET"}}})
    assert r["statusCode"] == 200 and r["body"].encode() == LAYOUTS.read_bytes()


def test_the_fridge_page_is_served():
    from service import handler as h
    r = h.handler({"rawPath": "/fridge", "requestContext": {"http": {"method": "GET"}}})
    assert r["statusCode"] == 200 and "Glass Pantry Fridge" in r["body"]


def test_boxes_are_normalized_fractions_not_millimetres():
    for row in json.loads(LAYOUTS.read_text(encoding="utf-8")):
        for c in row["compartments"]:
            assert "box_mm" not in c and len(c["box"]) == 6 and all(0 <= v <= 1 for v in c["box"]), row["key"]
