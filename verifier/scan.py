"""One shelf photo through the loop: gate -> model proposes -> OpenCV checks -> decision, with a trace.

The model is any `Proposer`: a vision-language model behind an HTTP call, a recorded answer, or a fake in
tests. OpenCV never names things; it checks the photo and the proposal, and its result picks the action.
"""

import time
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from . import decide, gate, planes


@dataclass(frozen=True)
class Proposal:
    """What the model says the photo shows. Shelf lines are fractions of the image height (0 = top)."""
    shelf_lines: list[float]
    items: list[dict] = field(default_factory=list)  # passed through untouched: names, shelf index, boxes
    model: str = ""


class Proposer(Protocol):
    def propose(self, jpeg: bytes) -> Proposal: ...


def run(img: np.ndarray, jpeg: bytes, proposer: Proposer) -> dict:
    """The whole loop for one photo. Returns the decision and every piece of evidence behind it."""
    trace: list[dict] = []
    t0 = time.perf_counter()

    def step(name: str, **data):
        trace.append({"step": name, "ms": round((time.perf_counter() - t0) * 1000, 1), **data})

    g = gate.check(img)
    step("gate", **g.to_dict())
    early = decide.after_gate(g)
    if early:
        step("decide", action=early.action, why=early.why)
        return {"action": early.action, "why": early.why, "proposal": None, "trace": trace}

    p = proposer.propose(jpeg)
    step("propose", model=p.model, shelf_lines=p.shelf_lines, items=len(p.items))

    checks = planes.check(img, p.shelf_lines)
    step("planes", checks=[c.to_dict() for c in checks])

    d = decide.after_checks(checks)
    step("decide", action=d.action, why=d.why)
    return {"action": d.action, "why": d.why,
            "proposal": {"model": p.model, "shelf_lines": p.shelf_lines, "items": p.items}, "trace": trace}
