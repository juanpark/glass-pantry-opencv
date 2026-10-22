"""One shelf photo through the loop: frames -> gate -> model proposes -> OpenCV checks -> zoom pass -> decision.

The model is any `Proposer`: a vision-language model behind an HTTP call, a recorded answer, or a fake in
tests. OpenCV never names things; it checks the photo and the proposal, picks what deserves a second look, and
its result picks the action. Every step is in the trace with its time.
"""

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
    step("frames", size=list(f.size), original_size=list(f.original_size), scale=round(f.scale, 6))

    g = gate.check(f.image)
    step("gate", **g.to_dict())
    early = decide.after_gate(g)
    if early:
        return done(early.action, early.why)

    p = proposer.propose(f.jpeg)
    step("propose", model=p.model, shelf_lines=p.shelf_lines, items=len(p.items), **p.raw)

    checks = planes.check(f.image, p.shelf_lines)
    step("planes", checks=[c.to_dict() for c in checks])

    z = None
    if zoomer is not None:
        z = zoomer.run(f, p.items, confirmed)
        step("zoom", plans=len(z["plans"]), calls=len(z["calls"]),
             outcomes=[(o["item_id"], o["field"], o["outcome"]) for o in z["observations"]])

    d = decide.after_checks(checks, z["observations"] if z else ())
    proposal = {"model": p.model, "shelf_lines": p.shelf_lines, "items": p.items}
    return done(d.action, d.why, proposal, z)
