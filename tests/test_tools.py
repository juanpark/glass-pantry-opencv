import json

from tools import eval_zoom


def res(why, label_outcome):
    return {"trace": [{"step": "propose", "cost": 0.1, "ms": 1}, {"step": "planes", "ms": 2}, {"step": "decide", "ms": 3}],
            "why": why, "proposal": {"items": [{"id": "i1", "label": "A", "box": [0, 0, 10, 10]},
                                               {"id": "i2", "label": "B", "box": [0, 0, 10, 10]}]},
            "zoom": {"observations": [{"item_id": "i1", "field": "label", "outcome": label_outcome, "crop": "X", "note": ""}]}}


def run(tmp_path, why, ann):
    (tmp_path / "s1__r1__zoom.json").write_text(json.dumps(res(why, "conflict")))
    (tmp_path / "annotations.json").write_text(json.dumps(ann))
    return tmp_path


def test_partial_annotation_is_reported_as_partial(tmp_path, capsys):
    eval_zoom.main(run(tmp_path, ["label_conflict:i1"], {"s1__r1__zoom|i1|label": "close-up"}))
    out = capsys.readouterr().out
    assert "eligible labelled readings 2, annotated 1, unannotated 1" in out and "PARTIAL" in out


def test_a_flag_in_a_scan_that_already_asked_is_counted_apart(tmp_path, capsys):
    ann = {"s1__r1__zoom|i1|label": "close-up", "s1__r1__zoom|i2|label": "first"}
    eval_zoom.main(run(tmp_path, ["shelf_unconfirmed:0.400", "label_conflict:i1"], ann))
    out = capsys.readouterr().out
    assert "flagged by the zoom pass (label conflict): 1 (in scans that asked nothing else: 0)" in out
    assert "PARTIAL" not in out


def test_a_flag_in_an_otherwise_clear_scan_is_counted_as_new(tmp_path, capsys):
    ann = {"s1__r1__zoom|i1|label": "close-up", "s1__r1__zoom|i2|label": "first"}
    eval_zoom.main(run(tmp_path, ["label_conflict:i1"], ann))
    assert "(in scans that asked nothing else: 1)" in capsys.readouterr().out


def test_a_stale_annotation_is_ignored_and_reported(tmp_path, capsys):
    r = res(["label_conflict:i1"], "conflict")
    r["proposal"]["items"][1]["label"] = None  # i2 no longer has a label reading
    (tmp_path / "s1__r1__zoom.json").write_text(json.dumps(r))
    (tmp_path / "annotations.json").write_text(json.dumps({"s1__r1__zoom|i1|label": "first",
                                                           "s1__r1__zoom|i2|label": "neither"}))
    eval_zoom.main(tmp_path)
    out = capsys.readouterr().out
    assert "eligible labelled readings 1, annotated 1, unannotated 0, unsure 0, scored 1" in out
    assert "ignored 1 label annotations" in out


def test_unsure_is_annotated_but_not_scored(tmp_path, capsys):
    eval_zoom.main(run(tmp_path, ["label_conflict:i1"], {"s1__r1__zoom|i1|label": "unsure",
                                                         "s1__r1__zoom|i2|label": "first"}))
    assert "annotated 2, unannotated 0, unsure 1, scored 1" in capsys.readouterr().out


def test_an_invalid_choice_stops_the_evaluation(tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        eval_zoom.main(run(tmp_path, [], {"s1__r1__zoom|i1|label": "maybe"}))


def _trace_case(tmp_path, truth, expected):
    import json
    import subprocess
    import sys
    import cv2
    from tests.test_opening import opening_photo
    img, q = opening_photo()
    for n in expected:
        cv2.imwrite(str(tmp_path / f"{n}.jpg"), img)
    from verifier import frames
    size = list(frames.canonical(cv2.imencode(".jpg", img)[1].tobytes()).size)
    k = size[0] / img.shape[1]
    full = {"eligible": True, "corners": (q * k).tolist(), "lines": [0.3, 0.55, 0.8], "size": size}
    t = {n: full for n in truth}
    (tmp_path / "truth.json").write_text(json.dumps(t))
    (tmp_path / "notes.json").write_text(json.dumps({"compartments": {n: {} for n in expected}}))
    return subprocess.run([sys.executable, "tools/eval_trace.py", str(tmp_path), str(tmp_path / "truth.json"),
                           str(tmp_path / "notes.json")], capture_output=True, text=True)


def test_eval_trace_scores_a_complete_set(tmp_path):
    r = _trace_case(tmp_path, ["A", "B"], ["A", "B"])
    assert r.returncode == 0 and "GATE (frozen)" in r.stdout


def test_eval_trace_refuses_a_gate_decision_with_a_photo_missing(tmp_path):
    r = _trace_case(tmp_path, ["A"], ["A", "B"])
    assert r.returncode == 2 and "INCOMPLETE" in r.stdout and "KEEP" not in r.stdout and "GATE" not in r.stdout


def test_eval_trace_refuses_an_empty_expected_list(tmp_path):
    r = _trace_case(tmp_path, ["A"], [])
    assert r.returncode == 2 and "INCOMPLETE" in r.stdout


def test_the_fridge_page_does_not_advertise_switched_off_suggestions():
    from pathlib import Path
    from service import handler as h
    page = (Path(__file__).resolve().parent.parent / "web" / "fridge.html").read_text(encoding="utf-8")
    if not h.SUGGEST_CORNERS:
        assert "suggests corners" not in page and "by hand" in page


def test_the_page_refuses_an_unusable_outline_and_names_spaces_as_saved():
    """Outline review R1: the unverified path and Confirm both refuse an outline the lines cannot be drawn through,
    and step 2's names come from the same proposal Confirm saves (the pure rules are tested in tests/js)."""
    import re
    from pathlib import Path
    page = (Path(__file__).resolve().parent.parent / "web" / "fridge.html").read_text(encoding="utf-8")

    def body(start):
        i = page.index(start)
        return page[i:page.index("\n};", i)]
    no_corners, confirm = body('$("#noCorners").onclick'), body('$("#layoutOk").onclick')
    assert no_corners.index("T.outlineProblem(") < no_corners.index("startLines(")
    assert confirm.index("T.outlineProblem(") < confirm.index("T.applyTrace(")
    bands = page[page.index("function bandNames()"):page.index("function drawTrace()")]
    assert "T.traceNames(" in bands and not re.search(r"levelsOf|levelName", bands)


def test_the_fridge_picker_leads_with_brand_and_model_number():
    """Juan 10/23: RB38J was not findable on the iPhone picker, which cut the model number off the end."""
    import json
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    page = (root / "web" / "fridge.html").read_text(encoding="utf-8")
    src = page[page.index("function label(r){"):page.index("async function init()")]
    rows = json.loads((root / "web" / "layouts" / "layouts.json").read_text())
    out = subprocess.run(["node", "-e", src + "\nconsole.log(JSON.stringify(R.map(label)))".replace("R", json.dumps(rows), 1)],
                         capture_output=True, text=True, check=True).stdout
    labels = dict(zip([r["key"] for r in rows], json.loads(out)))
    assert labels["model:samsung-rb38j-bottom"].startswith("Samsung RB38J7200S4 · ")
    assert labels["model:lg-dios-4door"].startswith("LG M874GBB252 · ")
    assert labels["template:standard"] == "Generic: fridge on top, freezer below"
    assert all(not v.startswith("Generic: ") or " " in v[9:] for v in labels.values())  # every generic has a plain name


def _page():
    from pathlib import Path
    return (Path(__file__).resolve().parent.parent / "web" / "fridge.html").read_text(encoding="utf-8")


def _body(page, start, end="\n};"):
    i = page.index(start)
    return page[i:page.index(end, i)]


def test_red_team_page_fixes_are_wired():
    """Red team 10/23 (private notes, redteam_ocv_v4_live.md): each finding's guard is where the person acts."""
    p = _page()
    # 1: the unverified path and Confirm measure the outline against the photo's size
    assert "T.outlineProblem(trace.corners, trace.size)" in _body(p, '$("#noCorners").onclick')
    assert "T.outlineProblem(trace.corners, trace.size)" in _body(p, '$("#layoutOk").onclick')
    # 2: nothing in a card may widen the page; tables scroll inside their wrapper
    assert ".card>*{min-width:0}" in p.replace(" ", "") and ".row>*{min-width:0}" in p.replace(" ", "")
    # 3: a refused save is said in the card the person is using
    assert "commit(res.next, traceNote)" in p and "commit(r.next, fillNote)" in p
    # 4: a photo too small to trace is refused before step 1
    assert "MIN_TRACE" in _body(p, '$("#tracePick").addEventListener', "\n});")
    # 6: changing the dropdown while the switch question is open withdraws the question
    assert "modelNote" in _body(p, '$("#model").addEventListener', ";\n")
    # 7: touch gets a finger-sized reach in CSS pixels
    assert "pointerType" in p and "FINGER" in p


def test_straighten_refusals_carry_a_message():
    import base64
    import json
    from service import handler as h
    big = {"rawPath": "/straighten", "requestContext": {"http": {"method": "POST"}}, "headers": {},
           "body": "x" * (h.MAX_BYTES * 2), "isBase64Encoded": False}
    r = h.handler(big, is_enabled=lambda: True)
    assert r["statusCode"] == 413 and json.loads(r["body"]).get("message")
    bad = {**big, "body": json.dumps({"photo": base64.b64encode(b"not an image").decode()})}
    r = h.handler(bad, is_enabled=lambda: True)
    assert r["statusCode"] == 400 and json.loads(r["body"]).get("message")
