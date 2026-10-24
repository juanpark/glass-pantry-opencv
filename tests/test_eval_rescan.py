from tools.eval_rescan import score
from verifier import change


class Al:
    ok = True


def _r(**outcomes):
    return {"items": [{"id": i, "outcome": o, "box_now": [0, 0, 10, 10]} for i, o in outcomes.items()]}


def test_a_removed_thing_reported_as_moved_is_not_a_caught_removal():
    s = score({"removed": ["a"]}, _r(a=change.MOVED), [], Al())
    assert s["removed_flagged"] == 0


def test_a_moved_thing_is_scored_as_moved_not_as_removed():
    p = {"moved": [{"id": "a", "to": [100, 100, 150, 150]}]}
    s = score(p, _r(a=change.CHANGED, b=change.SAME), [[90, 90, 160, 160]], Al())
    assert (s["moved_flagged"], s["moved_to_found"], s["removed"], s["false_flags"], s["false_new"]) == (1, 1, 0, 0, 0)


def test_a_moved_thing_found_at_its_new_place_by_its_own_box():
    p = {"moved": [{"id": "a", "to": [0, 0, 20, 20]}]}
    s = score(p, _r(a=change.MOVED), [], Al())
    assert (s["moved_flagged"], s["moved_to_found"]) == (1, 1)
