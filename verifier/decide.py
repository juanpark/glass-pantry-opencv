"""The agent's decision: what OpenCV's evidence makes the system do next.

    retake  the photo failed the gate; ask for a new photo of this shelf (no model call is spent)
    ask     the model's reading and the photo disagree; a person confirms before anything is filed
    file    every check agrees; the reading goes into the tree and the 3D twin

The order matters: a bad photo is never read, and a disagreement is never filed silently.
"""

from dataclasses import dataclass, field

from .gate import GateResult
from .planes import PlaneCheck

RETAKE, ASK, FILE = "retake", "ask", "file"


@dataclass(frozen=True)
class Decision:
    action: str
    why: list[str] = field(default_factory=list)  # short codes a client can translate


def after_gate(gate: GateResult) -> Decision | None:
    """A decision before any model call, or None to go on and read the photo."""
    if not gate.passed:
        return Decision(RETAKE, [f"photo:{r}" for r in gate.reasons])
    return None


def after_checks(planes: list[PlaneCheck], zoom_observations: list[dict] = ()) -> Decision:
    """Reasons only accumulate: an agreeing crop never clears an unconfirmed shelf, and a crop conflict asks
    even when every shelf is confirmed. Unresolved crops are not a reason to ask; they keep the full-photo
    reading, which is what a person reviews anyway."""
    why = [f"shelf_unconfirmed:{p.proposed_y:.3f}" for p in planes if not p.confirmed]
    field = {"label": "label", "quantity": "count"}
    why += [f"{field[o['field']]}_conflict:{o['item_id']}" for o in zoom_observations if o["outcome"] == "conflict"]
    return Decision(ASK, why) if why else Decision(FILE)
