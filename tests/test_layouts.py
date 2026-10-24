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


def test_the_twin_module_is_served_as_javascript():
    from service import handler as h
    r = h.handler({"rawPath": "/twin.js", "requestContext": {"http": {"method": "GET"}}})
    assert r["statusCode"] == 200 and r["headers"]["content-type"].startswith("text/javascript") and "export function commit" in r["body"]


def test_the_front_door_leads_to_the_fridge_and_the_shelf_check():
    from service import handler as h
    get = lambda p: h.handler({"rawPath": p, "requestContext": {"http": {"method": "GET"}}})
    home, shelf = get("/"), get("/shelf")
    assert home["statusCode"] == 200 and 'href="fridge"' in home["body"] and 'href="shelf"' in home["body"]
    assert shelf["statusCode"] == 200 and "Glass Pantry Shelf Check" in shelf["body"]


def test_the_fridge_page_links_the_shelf_check_and_home():
    from service import handler as h
    body = h.handler({"rawPath": "/fridge", "requestContext": {"http": {"method": "GET"}}})["body"]
    assert '<a href="shelf">Or check a single shelf photo</a>' in body
    assert '<a href="./" class="muted" style="font-size:.88rem">← Glass Pantry</a>' in body
