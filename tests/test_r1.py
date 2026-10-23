"""Codex V2 R1 findings 1-3 and 6, through the real adapters with a fake Messages API."""
import cv2
import pytest

from tests.synth import shelf
from verifier import claude, decide, frames, scan, zoom
from tests.test_v2 import FakeAsker, FakeProposer, item, jpeg



@pytest.fixture(autouse=True)
def _recount_on(monkeypatch):
    """The count re-read logic stays tested; production has it off (test_v2: test_count_re_reads_are_off_in_production)."""
    from verifier import zoom as _z
    monkeypatch.setattr(_z, "RECOUNT", True)

def fake_api(monkeypatch, replies):
    """replies: list of (stop, text) returned in order by claude.call."""
    calls = []

    def call(content, key=None, model=claude.MODEL, max_tokens=8192, effort=claude.EFFORT, deadline=None):
        calls.append(model)
        stop, text = replies.pop(0)
        return {"text": text, "stop": stop, "request_id": f"req{len(calls)}", "ms": 1, "in": 1, "out": 1, "cost": 0.0}
    monkeypatch.setattr(claude, "call", call)
    return calls


SMALL = (100, 300, 140, 360)  # small enough to be re-read for its label


def full_read(items, lines=((0, 353, 1568), (0, 706, 1568))):
    import json
    els = [{"shelf_edge": n, "front": list(f), "back": None} for n, f in enumerate(lines)] + items
    return json.dumps(els, ensure_ascii=False)


def test_a_cut_off_crop_answer_certifies_nothing(monkeypatch):
    fake_api(monkeypatch, [("end_turn", full_read([item("i1", SMALL, label="MILK")])),
                           ("max_tokens", '{"label":"MILK","label_readable":true,"count_complete":true}')])
    r = scan.run(jpeg(shelf()), claude.ClaudeProposer("k"), zoomer=zoom.Zoomer(claude.ClaudeAsker("k")))
    (o,) = r["zoom"]["observations"]
    assert o["outcome"] == "unresolved"


@pytest.mark.parametrize("bad", ['{"label":[],"label_readable":true}', '{"label":123,"label_readable":true}',
                                 '{"label":"  ","label_readable":true}', '{"label":"MILK"}',
                                 '{"label":"MILK","label_readable":"yes"}'])
def test_a_malformed_crop_answer_is_unresolved(monkeypatch, bad):
    fake_api(monkeypatch, [("end_turn", full_read([item("i1", SMALL, label="MILK")])), ("end_turn", bad)])
    r = scan.run(jpeg(shelf()), claude.ClaudeProposer("k"), zoomer=zoom.Zoomer(claude.ClaudeAsker("k")))
    (o,) = r["zoom"]["observations"]
    assert o["outcome"] == "unresolved", o


def test_a_cut_off_judge_never_clears_a_conflict(monkeypatch):
    fake_api(monkeypatch, [("end_turn", full_read([item("i1", SMALL, label="서울우유")])),
                           ("end_turn", '{"label":"매일우유","label_readable":true}'),
                           ("max_tokens", '{"same_product": true}')])
    r = scan.run(jpeg(shelf()), claude.ClaudeProposer("k"),
                 zoomer=zoom.Zoomer(claude.ClaudeAsker("k"), judge=claude.LabelJudge("k")))
    (o,) = r["zoom"]["observations"]
    assert o["outcome"] == "conflict" and r["action"] == decide.ASK


def test_a_cut_off_full_read_keeps_what_closed_and_asks(monkeypatch):
    text = full_read([item("i1", (500, 300, 900, 900))])[:-1] + ', {"id": "i2", "appea'
    fake_api(monkeypatch, [("max_tokens", text)])
    r = scan.run(jpeg(shelf()), claude.ClaudeProposer("k"))
    assert [i["id"] for i in r["proposal"]["items"]] == ["i1"]
    assert r["action"] == decide.ASK and "read_incomplete" in r["why"]


def test_duplicate_ids_are_not_re_read_and_are_asked_about(monkeypatch):
    calls = fake_api(monkeypatch, [("end_turn", full_read([item("i1", SMALL, label="first"),
                                                         item("i1", (300, 300, 340, 360), label="second")]))])
    r = scan.run(jpeg(shelf()), claude.ClaudeProposer("k"), zoomer=zoom.Zoomer(claude.ClaudeAsker("k")))
    assert len(calls) == 1  # the full read only: no crop was bound to an ambiguous id
    assert r["zoom"]["observations"] == [] and "item_id_duplicate:i1" in r["why"] and r["action"] == decide.ASK


def test_every_observation_names_its_photo_and_proposal(monkeypatch):
    fake_api(monkeypatch, [("end_turn", full_read([item("i1", SMALL, label="MILK")])),
                           ("end_turn", '{"label":"MILK","label_readable":true}')])
    raw = jpeg(shelf())
    r = scan.run(raw, claude.ClaudeProposer("k"), zoomer=zoom.Zoomer(claude.ClaudeAsker("k")))
    (o,) = r["zoom"]["observations"]
    import hashlib
    assert o["source"] == hashlib.sha256(frames.canonical(raw).jpeg).hexdigest()[:16] and o["proposal"] == "req1"


@pytest.mark.parametrize("skip", ["truncated", "blurry", "budget"])
def test_a_skipped_re_read_keeps_the_persons_value(skip):
    img = shelf()
    if skip == "truncated":
        its = [item("i1", (0, 300, 120, 400), quantity=6)]
        conf = {("i1", "quantity"): 4}
    elif skip == "blurry":
        img[300:360, 100:140] = int(img[300:360, 100:140].mean())
        its = [item("i1", SMALL, label="x")]
        conf = {("i1", "label"): "mine"}
    else:
        its = [item(f"i{n}", (100 + 60 * n, 300, 140 + 60 * n, 360), label="x") for n in range(5)]
        conf = {}
    f = frames.canonical(jpeg(img))
    z = zoom.Zoomer(FakeAsker({"label": "x", "label_readable": True}), budget=4).run(f, its, conf)
    skipped = [o for o in z["observations"] if o["note"]]
    assert skipped
    for o in skipped:
        assert o["outcome"] == "unresolved"
        assert o["effective"] == conf.get((o["item_id"], o["field"]), o["full"])


def test_no_re_read_starts_without_enough_time():
    t = [1000.0]
    a = FakeAsker({"label": "x", "label_readable": True})
    f = frames.canonical(jpeg(shelf()))
    z = zoom.Zoomer(a, deadline=1020.0, clock=lambda: t[0]).run(f, [item("i1", SMALL, label="x")], {})
    assert a.calls == 0 and z["observations"][0]["note"] == "skipped:time"


def test_a_call_with_no_time_left_is_not_sent():
    import time
    with pytest.raises(claude.ModelError, match="no_time"):
        claude.call([{"type": "text", "text": "x"}], key="k", deadline=time.monotonic() + 3)


# ---- Codex V2 R2 ----

def test_a_broken_array_under_end_turn_is_incomplete(monkeypatch):
    text = full_read([item("i1", (500, 300, 900, 900))])[:-1] + ", BROKEN"
    fake_api(monkeypatch, [("end_turn", text)])
    r = scan.run(jpeg(shelf()), claude.ClaudeProposer("k"))
    assert [i["id"] for i in r["proposal"]["items"]] == ["i1"]
    assert r["action"] == decide.ASK and "read_incomplete" in r["why"]


def test_an_item_without_an_id_is_kept_and_asked_about(monkeypatch):
    noid = {"appearance": "jar", "box": [500, 300, 900, 900], "quantity": 1}
    calls = fake_api(monkeypatch, [("end_turn", full_read([item("i1", (300, 300, 340, 360)), noid]))])
    r = scan.run(jpeg(shelf()), claude.ClaudeProposer("k"), zoomer=zoom.Zoomer(claude.ClaudeAsker("k")))
    assert len(r["proposal"]["items"]) == 2 and "item_id_invalid" in r["why"] and r["action"] == decide.ASK
    assert all(o["item_id"] == "i1" for o in r["zoom"]["observations"])


def test_a_slow_exchange_is_abandoned_at_the_deadline(monkeypatch):
    import time
    import urllib.request

    def slow(req, timeout=None):
        time.sleep(9)  # every step within its socket timeout, the whole exchange too long
        raise AssertionError("never reached in time")
    monkeypatch.setattr(urllib.request, "urlopen", slow)
    t0 = time.monotonic()
    with pytest.raises(claude.ModelError, match="deadline"):
        claude.call([{"type": "text", "text": "x"}], key="k", deadline=t0 + claude.RESERVE + 5.5)
    assert time.monotonic() - t0 < 6.5


def test_a_crop_that_times_out_leaves_a_reviewable_unresolved_result():
    class Slow:
        def ask(self, crop, fields, target):
            raise claude.ModelError("deadline")
    f = frames.canonical(jpeg(shelf()))
    z = zoom.Zoomer(Slow()).run(f, [item("i1", SMALL, label="MILK")], {})
    (o,) = z["observations"]
    assert o["outcome"] == "unresolved" and o["effective"] == "MILK"


def test_an_over_budget_skip_keeps_the_persons_value():
    its = [item(f"i{n}", (100 + 60 * n, 300, 140 + 60 * n, 360), label="x") for n in range(5)]
    f = frames.canonical(jpeg(shelf()))
    z = zoom.Zoomer(FakeAsker({"label": "x", "label_readable": True}), budget=4).run(
        f, its, {(f"i{n}", "label"): "mine" for n in range(5)})
    over = [o for o in z["observations"] if o["note"] == "skipped:budget"]
    assert over and all(o["effective"] == "mine" for o in over)


@pytest.mark.parametrize("full, crop", [("설탕", "무설탕"), ("salt", "unsalted"), ("regular", "not regular")])
def test_a_longer_close_up_reading_is_never_same_by_containment_alone(full, crop):
    asked = []
    (o,) = zoom.reconcile(item("i1", (0, 0, 1, 1), label=full), {"label"}, {"label": crop, "label_readable": True}, {},
                          same_label=lambda a, b: asked.append((a, b)) or False)
    assert o.outcome == "conflict" and asked == [(full, crop)]


def test_a_negative_judgement_on_a_longer_reading_asks(monkeypatch):
    fake_api(monkeypatch, [("end_turn", full_read([item("i1", SMALL, label="설탕")])),
                           ("end_turn", '{"label":"무설탕","label_readable":true}'),
                           ("end_turn", '{"same_product": false}')])
    r = scan.run(jpeg(shelf()), claude.ClaudeProposer("k"),
                 zoomer=zoom.Zoomer(claude.ClaudeAsker("k"), judge=claude.LabelJudge("k")))
    assert r["action"] == decide.ASK and "label_conflict:i1" in r["why"]
