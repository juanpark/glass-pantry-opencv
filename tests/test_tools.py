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
    assert '$("#modelNote").hidden = true' in _body(p, "function selectModel(", "\n}")  # via selectModel (R1 test below)
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


def test_every_way_of_choosing_a_fridge_withdraws_an_open_switch_question():
    """Codex red-team R1: Choose (identify) set the picker without withdrawing the question; the confirm then
    switched to a fridge other than the one shown."""
    p = _page()
    assert "selectModel(" in _body(p, '$("#model").addEventListener', ";\n")
    assert "selectModel(s.key)" in p
    yes = p[p.index("yes.onclick"):p.index("no.onclick")]
    assert '$("#model").value !== r.key' in yes  # the confirmation is for the fridge still selected, or nothing
    init = _body(p, "async function init(){", "\n}\n")
    assert "T.isTwin(" in p[p.index("function load(){"):p.index("function commit(")]
    assert init.index('addEventListener("change", gate)') < init.index("render()")  # consent works even if drawing fails


def test_the_3d_view_is_lazy_read_only_and_served():
    """Slice 5: the 3D view loads only when opened, has a failure note, and confirmed rows keep where they stood."""
    import json
    from service import handler as h
    p = _page()
    d3 = _body(p, "async function draw3d(change = null){", "\n}")
    assert 'import("./twin3d.js")' in d3 and "could not load" in d3
    assert "commit(" not in d3 and "T.commit(" not in d3
    assert "...placement(tr.dataset.id)" in p
    for path in ("/scene.js", "/twin3d.js", "/compare.js"):
        r = h.handler({"rawPath": path, "requestContext": {"http": {"method": "GET"}}})
        assert r["statusCode"] == 200 and r["headers"]["content-type"].startswith("text/javascript")
    wf = (__import__("pathlib").Path(__file__).resolve().parent.parent / ".github/workflows/deploy.yml").read_text()
    assert "tests/js/scene.test.mjs" in wf


def test_reframing_on_resize_also_resets_the_orbit_target():
    """Codex 3D R2: after a pan, resize must look at the cabinet's centre again, not the panned point."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "web" / "twin3d.js").read_text(encoding="utf-8")
    fit = src[src.index("const fit = () =>"):src.index("const ro =")]
    assert fit.index("ctl.target.set(...frame())") < fit.index("ctl.update()")


def test_a_comparison_still_loading_never_returns_after_apply():
    """Codex v6 R1 #1: the image continuation and every frame check that this comparison is still the open one."""
    p = _page()
    show = _body(p, "function showRescan(res, url, my, read){", "\n}")
    assert show.count("live()") >= 2 and "const live = () => fillLive(my) && fill.rescan === rs" in show


def test_the_phone_apps_item_models_are_served_and_nothing_else_under_items():
    """Plan v6: the 3D view draws the app's own models; only exported item files can be fetched."""
    import base64
    import json
    from service import handler as h

    def get(path):
        return h.handler({"rawPath": path, "requestContext": {"http": {"method": "GET"}}})
    lib = json.loads(get("/items/items.json")["body"])["items"]
    assert len(lib) >= 50 and all(len(m) >= 2 for it in lib for m in it["match"])
    r = get(f"/items/item-{lib[0]['key']}.glb")
    assert r["statusCode"] == 200 and r["isBase64Encoded"] and r["headers"]["content-type"] == "model/gltf-binary"
    assert base64.b64decode(r["body"])[:4] == b"glTF"
    for bad in ("/items/item-nope.glb", "/items/item-../../service/handler.py", "/items/items.glb", "/items/item-A.glb"):
        assert get(bad)["statusCode"] == 404, bad


def test_the_fridge_is_kept_on_this_device_and_can_be_forgotten():
    """Juan 10/24: remember the fridge across visits (this browser only), with a way to forget it."""
    p = _page()
    # on this device with the writer lock; tab-only (sessionStorage) only where Web Locks are missing (Codex keep R2)
    assert "window.localStorage" in p and 'mode === "none" ? window.sessionStorage' in p
    assert 'id="forget"' in p and "T.forget(" in p
    assert 'addEventListener("storage"' in p  # another tab's save pauses this one instead of overwriting it


def test_only_the_writer_tab_saves_and_forget_stops_saving_first():
    """Codex v6 keep R1: one writer tab (Web Locks); Forget pauses every save before deleting and reports a failure."""
    p = _page()
    assert "const m = await T.claimWriter(navigator.locks)" in p and "read-only" in p and "ready = true;" in p
    assert "let mode = null;" in p  # nothing is writable until the lock is decided and the saved fridge is loaded
    cm = _body(p, "function commit(next, note){", "\n}")
    assert "!canWrite()" in cm
    assert "canWrite()" in _body(p, "async function saveRescan(", "\n}")
    fg = _body(p, '$("#forget").onclick = () => {', "\n  };")
    assert fg.index("broken = true") < fg.index("T.forget(")
    assert "location.reload()" in fg and "if(!r.ok)" in fg
