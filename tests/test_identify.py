"""Slice 4 (I-69): the fridge from a photo of it or its model sticker. The model reads; plain code matches."""

import json

import pytest

from service import handler as h
from tests.test_service import call, ev, real_jpeg
from verifier import identify as I

ROWS = I.load_rows()


def test_every_catalogue_row_has_a_kind_from_its_geometry():
    kinds = {r["key"]: I.kind_of(r) for r in ROWS}
    assert kinds == {
        "model:samsung-bespoke-4door": "four_door", "model:lg-dios-4door": "four_door",
        "model:samsung-sidebyside": "side_by_side", "model:lg-dios-sidebyside": "side_by_side",
        "template:sideBySide": "side_by_side", "template:standard": "bottom_freezer",
        "template:freezerTop": "top_freezer", "model:samsung-2door": "top_freezer",
        "model:samsung-rb38j-bottom": "bottom_freezer", "model:lg-2door": "top_freezer",
        "model:samsung-1door-small": "one_door", "model:samsung-kimchi-plus-stand": "kimchi_stand",
        "template:kimchi": "kimchi_stand", "model:lg-kimchi-toktok-stand": "kimchi_stand",
        "template:kimchiChest": "kimchi_chest", "model:winia-dimchae-chest": "kimchi_chest"}


def test_codes_are_compared_as_printed_codes():
    assert I.norm_code(" rb38j7200s4 ") == "RB38J7200S4"
    assert I.norm_code("RB38J7200S4/EF") == "RB38J7200S4"
    assert I.norm_code("RB-38J 7200 S4") == "RB38J7200S4"
    assert I.norm_code("") is None and I.norm_code(None) is None and I.norm_code(42) is None


def test_an_exact_code_picks_that_model_first():
    s = I.suggest({"model_code": "RB38J7200S4", "brand": "SAMSUNG", "kind": "bottom_freezer"}, ROWS)
    assert s[0]["key"] == "model:samsung-rb38j-bottom" and s[0]["match"] == "exact"
    assert s[0]["reason"] == "The model number RB38J7200S4 matches Samsung RB38J7200S4."
    s = I.suggest({"model_code": "RB38J7200S4", "brand": "Samsung", "kind": "unknown"}, ROWS)  # a sticker: no look
    assert s[1]["key"] == "template:standard" and s[1]["reason"].startswith("Samsung RB38J7200S4 has fridge on top")
    assert "looks like" not in " ".join(x["reason"] for x in s)


def test_a_sibling_code_of_the_same_brand_is_offered_as_the_same_family():
    s = I.suggest({"model_code": "RB38J7215SA", "brand": "삼성", "kind": "bottom_freezer"}, ROWS)
    assert s[0]["key"] == "model:samsung-rb38j-bottom" and s[0]["match"] == "family"
    assert any(x["key"] == "template:standard" for x in s)  # the generic of its kind is still offered


def test_a_short_shared_prefix_or_another_brand_is_not_a_family():
    s = I.suggest({"model_code": "RB33J3000SA", "brand": "Samsung", "kind": "bottom_freezer"}, ROWS)
    assert all(x["match"] != "family" for x in s)
    s = I.suggest({"model_code": "RB38J7215SA", "brand": "LG", "kind": "bottom_freezer"}, ROWS)
    assert all(x["match"] != "family" for x in s)


def test_an_unknown_code_falls_back_to_the_generic_of_its_kind_then_same_brand_models():
    s = I.suggest({"model_code": "XYZ123", "brand": "LG", "kind": "top_freezer"}, ROWS)
    assert s[0]["key"] == "template:freezerTop" and s[0]["match"] == "kind"
    rest = [x["key"] for x in s[1:]]
    assert rest.index("model:lg-2door") < rest.index("model:samsung-2door")
    assert all(I.kind_of(I.row(ROWS, x["key"])) == "top_freezer" for x in s)


def test_a_kind_without_a_generic_offers_its_library_models():
    s = I.suggest({"model_code": None, "brand": None, "kind": "four_door"}, ROWS)
    assert {x["key"] for x in s} == {"model:samsung-bespoke-4door", "model:lg-dios-4door"}


def test_nothing_readable_suggests_nothing():
    assert I.suggest({"model_code": None, "brand": None, "kind": "unknown"}, ROWS) == []
    assert I.suggest({"kind": "spaceship"}, ROWS) == []
    assert I.suggest({}, ROWS) == []


def test_the_answer_is_believed_only_when_complete_and_one_object():
    assert I.read_answer('{"model_code": "RB38J7200S4", "brand": "SAMSUNG", "kind": "bottom_freezer"}', "end_turn")["kind"] == "bottom_freezer"
    assert I.read_answer('{"model_code": "RB38J7200S4", "kind": "bottom_freezer"}', "max_tokens") is None
    assert I.read_answer("I cannot tell.", "end_turn") is None
    assert I.read_answer('{"kind": 3}', "end_turn") == {"model_code": None, "brand": None, "kind": "unknown", "evidence": ""}


# ---- the route ----

def ident(e, **kw):
    kw.setdefault("identifier", lambda j, k, **_: {"reading": {"kind": "unknown"}, "suggestions": [], "cost_usd": 0.01})
    return call(e, **kw)


def test_identify_has_the_scan_guards_in_the_same_order():
    spent = []
    s, b = ident(ev("POST", "/identify", b"x"), is_enabled=lambda: False, admitter=lambda: spent.append(1) or True)
    assert s == 503 and b["error"] == "paused" and spent == []
    s, _ = ident(ev("POST", "/identify", b"x" * (h.MAX_BYTES + 10)), admitter=lambda: pytest.fail("not counted"))
    assert s in (400, 413)
    s, b = ident(ev("POST", "/identify", b"not a photo"), admitter=lambda: pytest.fail("not counted"))
    assert s == 400 and b["error"] == "bad_photo"
    s, b = ident(ev("POST", "/identify", real_jpeg()), admitter=lambda: False,
                 identifier=lambda j, k, **_: pytest.fail("no model call"))
    assert s == 429 and b["error"] == "daily_limit"

    def broken():
        raise RuntimeError("table")
    s, b = ident(ev("POST", "/identify", real_jpeg()), admitter=broken, identifier=lambda j, k, **_: pytest.fail("no call"))
    assert s == 503 and b["error"] == "limit_unavailable"


def test_identify_counts_once_and_returns_the_suggestions_without_model_text_in_logs(capsys):
    spent = []
    res = {"reading": {"model_code": "RB38J7200S4", "brand": "삼성", "kind": "bottom_freezer", "evidence": "sticker"},
           "suggestions": [{"key": "model:samsung-rb38j-bottom", "match": "exact", "reason": "r"}], "cost_usd": 0.02}
    s, b = ident(ev("POST", "/identify", real_jpeg()), admitter=lambda: spent.append(1) or True,
                 identifier=lambda j, k, **_: res)
    out = capsys.readouterr().out
    assert s == 200 and spent == [1] and b["suggestions"][0]["key"] == "model:samsung-rb38j-bottom"
    assert "RB38J7200S4" not in out and "삼성" not in out and "sticker" not in out


def test_an_identify_model_failure_is_502_with_nothing_echoed(capsys):
    def boom(j, k, **_):
        raise RuntimeError("secret RB38J7200S4")
    s, b = ident(ev("POST", "/identify", real_jpeg()), identifier=boom)
    assert s == 502 and "RB38J" not in json.dumps(b) and "RB38J" not in capsys.readouterr().out


def test_identify_photo_turns_a_cut_off_answer_into_no_reading(monkeypatch):
    from verifier import claude
    monkeypatch.setattr(claude, "call", lambda *a, **k: {"text": '{"model_code": "RB38', "stop": "max_tokens",
                                                         "cost": 0.01, "request_id": "r", "ms": 1, "in": 1, "out": 1})
    res = h.identify_photo(real_jpeg(), "k")
    assert res["reading"] is None and res["suggestions"] == []


def test_the_page_offers_a_photo_pick_that_selects_but_never_switches():
    from pathlib import Path
    page = (Path(__file__).resolve().parent.parent / "web" / "fridge.html").read_text(encoding="utf-8")
    assert 'id="identifyPick"' in page and '"identifyPick"' in page[page.index("function gate()"):]
    i = page.index('$("#identifyPick")')
    body = page[i:page.index("\n});", i)]
    assert 'fetch("identify"' in body and "switchTo(" not in body and "replaceModel(" not in body
