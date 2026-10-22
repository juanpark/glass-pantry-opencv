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
