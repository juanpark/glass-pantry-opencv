import hashlib

import cv2
import numpy as np
import pytest

from tests.synth import shelf
from verifier import decide, frames, prompt, scan, zoom
from verifier.scan import Proposal


def jpeg(img, q=92) -> bytes:
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1].tobytes()


# ---- C5: the frozen prompt ----

def test_prompt_is_the_frozen_export_with_the_frame_filled_in():
    p = prompt.contents(1568, 1176)
    assert hashlib.sha256(prompt.TEMPLATE.encode()).hexdigest() == prompt.SHA256
    assert "가로 1568px × 세로 1176px" in p and "{W}" not in p and "{H}" not in p
    assert '"label"' in p and "shelf_edge" in p and '"box"' in p  # the context the zoom pass relies on


# ---- C3: frames ----

def test_a_small_photo_keeps_its_exact_bytes():
    raw = jpeg(shelf(h=900, w=1200))
    f = frames.canonical(raw)
    assert f.jpeg == raw and f.scale == 1.0


def test_a_large_photo_is_resized_once_and_boxes_map_back():
    raw = jpeg(shelf(h=3024, w=4032))
    f = frames.canonical(raw)
    assert max(f.size) == 1568 and f.original_size == (4032, 3024)
    assert f.to_original((100, 50, 200, 150)) == pytest.approx((257.1, 128.6, 514.3, 385.7), abs=0.2)
    assert cv2.imdecode(np.frombuffer(f.jpeg, np.uint8), cv2.IMREAD_COLOR).shape[:2] == (1176, 1568)


# ---- C1: selection ----

def item(i, box, label=None, quantity=1, **kw):
    return {"id": i, "box": list(box), "label": label, "quantity": quantity, "appearance": "x", **kw}


def test_selection_respects_the_budget_and_picks_only_label_and_count():
    img = shelf()
    items = [item(f"i{n}", (100 + 60 * n, 300, 140 + 60 * n, 360), label="서울우유") for n in range(8)]
    plans, skipped = zoom.select(img, img, 1.0, items, budget=4)
    assert len(plans) == 4
    assert all(p.fields <= {"label", "quantity"} for p in plans)


def test_a_big_box_with_one_thing_is_not_re_read():
    img = shelf()
    plans, _ = zoom.select(img, img, 1.0, [item("i1", (100, 100, 900, 900), label="x")], budget=4)
    assert plans == []


def test_a_count_group_cut_by_the_photo_edge_is_unresolved_without_a_call():
    img = shelf()
    plans, skipped = zoom.select(img, img, 1.0, [item("i1", (0, 300, 120, 400), quantity=6)], budget=4)
    assert plans == [] and skipped == [("i1", "quantity", "unresolved:truncated")]


def test_a_blurry_box_is_not_read_for_text():
    img = shelf()
    img[300:360, 100:140] = cv2.GaussianBlur(img[300:360, 100:140], (31, 31), 0)
    img[300:360, 100:140] = int(img[300:360, 100:140].mean())  # no detail left at all
    plans, skipped = zoom.select(img, img, 1.0, [item("i1", (100, 300, 140, 360), label="x")], budget=4)
    assert plans == [] and skipped == [("i1", "label", "unresolved:blurry")]


# ---- C1: reconcile ----

@pytest.mark.parametrize("full, crop, outcome", [
    ({"label": "서울우유"}, {"label": "서울우유", "label_readable": True}, "same"),
    ({"label": None}, {"label": "매일우유", "label_readable": True}, "provisional"),
    ({"label": "서울우유"}, {"label": "매일우유", "label_readable": True}, "conflict"),
    ({"label": "서울우유"}, {"label": None, "label_readable": False}, "unresolved"),
    ({"label": "서울우유"}, None, "unresolved"),  # failed or malformed call
])
def test_label_reconcile_table(full, crop, outcome):
    (o,) = zoom.reconcile(item("i1", (0, 0, 1, 1), **full), {"label"}, crop, confirmed={})
    assert o.outcome == outcome
    assert o.full == full["label"]  # both readings are kept
    assert o.effective == (full["label"] if outcome != "provisional" else None)  # nothing silently wins


@pytest.mark.parametrize("full_q, crop, outcome", [
    (6, {"count": 6, "count_complete": True}, "same"),
    (6, {"count": 4, "count_complete": True}, "conflict"),
    (6, {"count": 0, "count_complete": False}, "unresolved"),  # an incomplete look is never zero
    (6, {"count": None, "count_complete": True}, "unresolved"),
])
def test_count_reconcile_table(full_q, crop, outcome):
    (o,) = zoom.reconcile(item("i1", (0, 0, 1, 1), quantity=full_q), {"quantity"}, crop, confirmed={})
    assert o.outcome == outcome and o.effective == full_q


def test_a_person_confirmed_value_is_never_overwritten():
    it = item("i1", (0, 0, 1, 1), label="서울우유")
    (o,) = zoom.reconcile(it, {"label"}, {"label": "매일우유", "label_readable": True},
                          confirmed={("i1", "label"): "서울우유"})
    assert o.effective == "서울우유" and o.outcome == "conflict" and o.reopen


# ---- C3: reasons accumulate ----

class FakeProposer:
    def __init__(self, items, lines):
        self.items, self.lines, self.calls = items, lines, 0

    def propose(self, jpeg_bytes):
        self.calls += 1
        return Proposal(shelf_lines=self.lines, items=self.items, model="fake")


class FakeAsker:
    def __init__(self, answer):
        self.answer, self.calls = answer, 0

    def ask(self, crop_jpeg, fields, target):
        self.calls += 1
        return self.answer


def test_an_agreeing_crop_does_not_clear_an_unconfirmed_shelf():
    img = shelf(shelves=(0.3, 0.6))
    p = FakeProposer([item("i1", (100, 300, 140, 360), label="서울우유")], [0.3, 0.45])  # 0.45 is not a shelf
    r = scan.run(jpeg(img), p, zoomer=zoom.Zoomer(FakeAsker({"label": "서울우유", "label_readable": True})))
    assert r["action"] == decide.ASK and any(w.startswith("shelf_unconfirmed") for w in r["why"])


def test_a_crop_conflict_asks_even_when_shelves_agree():
    img = shelf(shelves=(0.3, 0.6))
    p = FakeProposer([item("i1", (100, 300, 140, 360), label="서울우유")], [0.3, 0.6])
    r = scan.run(jpeg(img), p, zoomer=zoom.Zoomer(FakeAsker({"label": "매일우유", "label_readable": True})))
    assert r["action"] == decide.ASK and "label_conflict:i1" in r["why"]


def test_a_failed_photo_spends_no_model_or_crop_call():
    from tests.synth import shake
    p, a = FakeProposer([], [0.3]), FakeAsker(None)
    r = scan.run(jpeg(shake(shelf())), p, zoomer=zoom.Zoomer(a))
    assert r["action"] == decide.RETAKE and p.calls == 0 and a.calls == 0


def test_the_model_gets_the_canonical_bytes_the_gate_checked():
    raw = jpeg(shelf(h=3024, w=4032))
    seen = []

    class Spy(FakeProposer):
        def propose(self, b):
            seen.append(b)
            return super().propose(b)

    r = scan.run(raw, Spy([], [0.3, 0.6]))
    assert seen == [frames.canonical(raw).jpeg]
    assert [s["step"] for s in r["trace"]][:2] == ["frames", "gate"]


# ---- the model answer parser ----

def test_parser_keeps_closed_objects_and_drops_a_truncated_one():
    from verifier import claude
    text = '```json\n[{"shelf_edge": 0, "front": [0, 588, 1568], "back": null}, {"id": "i1", "box": [1,2,3,4]}, {"id": "i2", "app'
    els = claude.parse_array(text)
    assert els == [{"shelf_edge": 0, "front": [0, 588, 1568], "back": None}, {"id": "i1", "box": [1, 2, 3, 4]}]
    lines, items = claude.split(els, 1176)
    assert lines == [0.5] and [i["id"] for i in items] == ["i1"]


def test_parser_returns_none_without_an_array():
    from verifier import claude
    assert claude.parse_array("sorry") is None and claude.parse_object("no json") is None


def test_the_asker_is_told_where_the_item_is_not_what_it_was_read_as():
    from verifier import claude
    seen = []

    class Spy:
        def ask(self, crop, fields, target):
            seen.append(target)
            return {"label": "서울우유", "label_readable": True}

    img = shelf()
    p = FakeProposer([item("i1", (100, 300, 140, 360), label="서울우유")], [0.3, 0.6])
    scan.run(jpeg(img), p, zoomer=zoom.Zoomer(Spy()))
    (t,) = seen
    assert t[2:] == (21, 21, 61, 81)  # the box inside its crop (pad 21 px)
    assert "{" not in zoom.ASK_PROMPT.format(cw=1, ch=1, x0=0, y0=0, x1=1, y1=1).split("JSON")[0]


def test_a_partly_hidden_label_that_matches_is_same():
    (o,) = zoom.reconcile(item("i1", (0, 0, 1, 1), label="백설 다담 된장찌개 양념"), {"label"},
                          {"label": "백설 다담 된장찌", "label_readable": True, "label_partial": True}, confirmed={})
    assert o.outcome == "same"


def test_an_empty_or_unreadable_reading_is_never_filed():
    img = jpeg(shelf(shelves=(0.3, 0.6)))
    r = scan.run(img, FakeProposer([], [0.3, 0.6]))
    assert r["action"] == decide.ASK and r["why"] == ["nothing_read"]

    class Unreadable(FakeProposer):
        def propose(self, b):
            return Proposal(shelf_lines=[], items=[], model="fake", raw={"parsed": False})
    r = scan.run(img, Unreadable([], []))
    assert r["action"] == decide.ASK and r["why"][0] == "model_unreadable"


def test_a_big_crop_is_reduced_to_the_model_limit_and_the_target_follows():
    big = np.zeros((4000, 4000, 3), np.uint8)
    c, k = zoom.crop_image(big, (0, 0, 3200, 3100))
    assert max(c.shape[:2]) == zoom.CROP_LONG and abs(k - 1568 / 3200) < 1e-9
    p = zoom.Plan("i1", frozenset({"quantity"}), (0, 0, 3200, 3100), (0, 0, 3200, 3100), (), 0.5)
    t = zoom.target_in_crop(p, 1.0, {"box": [320, 310, 2880, 2790]}, k)
    assert t[0] == 1568 and t[2] == round(320 * k)


def test_a_judge_turns_a_language_difference_into_same_but_never_invents():
    it = item("i1", (0, 0, 1, 1), label="땅콩버터")
    ans = {"label": "SKIPPY PEANUT BUTTER", "label_readable": True}
    (o,) = zoom.reconcile(it, {"label"}, ans, {}, same_label=lambda a, b: True)
    assert o.outcome == "same" and o.effective == "땅콩버터"
    (o,) = zoom.reconcile(it, {"label"}, ans, {}, same_label=lambda a, b: False)
    assert o.outcome == "conflict"
    (o,) = zoom.reconcile(item("i1", (0, 0, 1, 1), label=None), {"label"}, ans, {}, same_label=lambda a, b: True)
    assert o.outcome == "provisional"  # nothing to compare with: the judge is not asked


def test_a_one_letter_fragment_is_unresolved_not_a_conflict():
    (o,) = zoom.reconcile(item("i1", (0, 0, 1, 1), label="오뚜기 드레싱"), {"label"},
                          {"label": "탈", "label_readable": True, "label_partial": True}, {})
    assert o.outcome == "unresolved"
