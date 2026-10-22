import cv2
import pytest

from tests.synth import shake, shelf
from verifier import decide, gate, planes, scan


def test_gate_passes_a_sharp_shelf():
    r = gate.check(shelf())
    assert r.passed, r


@pytest.mark.parametrize("bad, reason", [
    (lambda i: cv2.GaussianBlur(i, (9, 9), 0), "blurry"),
    (shake, "shake"),
    (lambda i: cv2.convertScaleAbs(i, alpha=0.25), "dark"),
    (lambda i: cv2.convertScaleAbs(i, alpha=2.5), "blown"),
])
def test_gate_flags_each_kind_of_bad_photo(bad, reason):
    r = gate.check(bad(shelf()))
    assert not r.passed and reason in r.reasons, r


def test_a_real_shelf_edge_is_confirmed_and_snapped():
    (c,) = planes.check(shelf(shelves=(0.3, 0.6)), [0.31])
    assert c.confirmed
    assert abs(c.snapped_y - 0.3) <= 0.01, c


def test_a_shelf_the_photo_does_not_show_is_unconfirmed():
    (c,) = planes.check(shelf(shelves=(0.3, 0.6)), [0.45])
    assert not c.confirmed and c.snapped_y is None, c


def test_bad_photo_means_retake_before_any_model_call():
    d = decide.after_gate(gate.check(shake(shelf())))
    assert d.action == decide.RETAKE and "photo:shake" in d.why


def test_good_photo_goes_on_to_the_model():
    assert decide.after_gate(gate.check(shelf())) is None


def test_all_shelves_confirmed_means_file():
    d = decide.after_checks(planes.check(shelf(shelves=(0.3, 0.6)), [0.3, 0.6]))
    assert d.action == decide.FILE, d


def test_one_unconfirmed_shelf_means_ask():
    d = decide.after_checks(planes.check(shelf(shelves=(0.3, 0.6)), [0.3, 0.45]))
    assert d.action == decide.ASK and d.why == ["shelf_unconfirmed:0.450"], d


class _Fake:
    def __init__(self, lines):
        self.lines, self.calls = lines, 0

    def propose(self, jpeg):
        self.calls += 1
        return scan.Proposal(shelf_lines=self.lines, items=[{"name": "jam"}], model="fake")


def test_scan_retake_spends_no_model_call():
    # run() takes only the bytes the model would get, so the gate always checks that exact photo
    fake = _Fake([0.3, 0.6])
    out = scan.run(_jpeg(shake(shelf())), fake)
    assert out["action"] == "retake" and fake.calls == 0
    assert [s["step"] for s in out["trace"]] == ["frames", "gate", "decide"]


def test_scan_trace_shows_the_check_that_changed_the_action():
    out = scan.run(_jpeg(shelf(shelves=(0.3, 0.6))), _Fake([0.3, 0.45]))
    assert out["action"] == "ask"
    assert [s["step"] for s in out["trace"]] == ["frames", "gate", "propose", "planes", "decide"]
    unconfirmed = [c for c in out["trace"][3]["checks"] if not c["confirmed"]]
    assert [c["proposed_y"] for c in unconfirmed] == [0.45]


def test_scan_files_when_everything_agrees():
    out = scan.run(_jpeg(shelf(shelves=(0.3, 0.6))), _Fake([0.3, 0.6]))
    assert out["action"] == "file" and out["proposal"]["items"] == [{"name": "jam"}]


@pytest.mark.parametrize("y", [-0.05, 1.05, float("nan"), float("inf")])
def test_a_shelf_outside_the_photo_is_never_confirmed(y):
    (c,) = planes.check(shelf(shelves=(0.3, 0.6)), [y])
    assert not c.confirmed and c.snapped_y is None, c


def _jpeg(img):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    assert ok
    return buf.tobytes()


def test_scan_refuses_bytes_that_are_not_an_image():
    fake = _Fake([0.3, 0.6])
    out = scan.run(b"not a jpeg", fake)
    assert out["action"] == "retake" and out["why"] == ["photo:unreadable"] and fake.calls == 0
