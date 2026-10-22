"""One shelf photo through the loop: frames -> gate -> model proposes -> OpenCV checks -> zoom pass -> decision.

The model is any `Proposer`: a vision-language model behind an HTTP call, a recorded answer, or a fake in
tests. OpenCV never names things; it checks the photo and the proposal, picks what deserves a second look, and
its result picks the action. Every step is in the trace with its time.
"""

import hashlib
import time
from dataclasses import dataclass, field
from typing import Protocol

from . import decide, frames as frames_mod, gate, planes


@dataclass(frozen=True)
class Proposal:
    """What the model says the photo shows. Shelf lines are fractions of the image height (0 = top)."""
    shelf_lines: list[float]
    items: list[dict] = field(default_factory=list)  # passed through untouched: names, shelf index, boxes
    model: str = ""
    raw: dict = field(default_factory=dict)  # request id, tokens, cost: evidence, never used to decide


class Proposer(Protocol):
    def propose(self, jpeg: bytes) -> Proposal: ...


def run(jpeg: bytes, proposer: Proposer, zoomer=None, confirmed: dict | None = None) -> dict:
    """The whole loop for one photo. Returns the decision and every piece of evidence behind it.

    `jpeg` is the original photo. OpenCV checks the canonical image derived from it, and the model is sent
    exactly those canonical bytes, so a check can never pass a different photo from the one that is read.
    """
    trace: list[dict] = []
    t0 = time.perf_counter()

    def step(name: str, **data):
        trace.append({"step": name, "ms": round((time.perf_counter() - t0) * 1000, 1), **data})

    def done(action, why, proposal=None, zoom=None):
        step("decide", action=action, why=why)
        return {"action": action, "why": why, "proposal": proposal, "zoom": zoom, "trace": trace}

    f = frames_mod.canonical(jpeg)
    if f is None:
        return done(decide.RETAKE, ["photo:unreadable"])
    source = hashlib.sha256(f.jpeg).hexdigest()[:16]  # names this photo in every result that comes from it
    step("frames", size=list(f.size), original_size=list(f.original_size), scale=round(f.scale, 6), source=source)

    g = gate.check(f.image)
    step("gate", **g.to_dict())
    early = decide.after_gate(g)
    if early:
        return done(early.action, early.why)

    p = proposer.propose(f.jpeg)
    step("propose", model=p.model, shelf_lines=p.shelf_lines, items=len(p.items), **p.raw)

    checks = planes.check(f.image, p.shelf_lines)
    step("planes", checks=[c.to_dict() for c in checks])

    from .claude import check_items
    problems = check_items(p.items)
    ambiguous = {w.split(":", 1)[1] for w in problems if w.startswith("item_id_duplicate:")}
    clean = [it for it in p.items if isinstance(it.get("id"), str) and it.get("id").strip() and it["id"] not in ambiguous]

    z = None
    if zoomer is not None:
        binding = {"source": source, "proposal": p.raw.get("request_id") or p.model}
        z = zoomer.run(f, clean, confirmed, binding)
        step("zoom", plans=len(z["plans"]), calls=len(z["calls"]),
             outcomes=[(o["item_id"], o["field"], o["outcome"]) for o in z["observations"]])

    d = decide.after_checks(checks, z["observations"] if z else ())
    why = list(d.why)
    if p.raw.get("parsed") is False:
        why.insert(0, "model_unreadable")  # no list could be read from the answer: never filed as an empty shelf
    elif not p.items:
        why.insert(0, "nothing_read")  # a sharp photo with no items: a person says whether the shelf is empty
    if p.raw.get("complete") is False and p.items:
        why.insert(0, "read_incomplete")  # the answer was cut off: what was read is kept, but the list may be short
    why[0:0] = problems  # ambiguous ids: those items are not re-read, and a person sorts them out
    proposal = {"model": p.model, "shelf_lines": p.shelf_lines, "items": p.items, "source": source,
                "id": p.raw.get("request_id")}
    return done(decide.ASK if why else d.action, why, proposal, z)
