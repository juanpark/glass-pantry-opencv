"""Zoom pass: OpenCV picks the few places worth a second look, and the model re-reads only those.

A narrow re-observation, not a rescan. It may look at two fields of a proposed item, the printed label and the
count, and it never touches anything else (box, shelf, identity, contents). The crop answer is kept beside the
full-photo answer; when they disagree neither wins and a person is asked. What it cannot do, by construction:
find an item the model did not propose, or read text that the photo blurred away.

OpenCV's part is the choice of what to re-read and what to leave alone:
- a label on a small box (small text is where invented brand names come from);
- a count of two or more;
- skipped, with a reason and no call: a count group cut by the photo edge (its crop could never show the whole
  group), and a box with no fine detail left (Laplacian variance in the original), where a re-read could only guess.
"""

from dataclasses import dataclass, asdict

import cv2
import numpy as np

SMALL_BOX = 0.03  # box area / photo area below this: label text is small enough to be guessed
BLURRY = 40.0  # Laplacian variance of the box (original pixels) below this: no detail left to read
EDGE = 2  # px from the photo edge that counts as touching it
PAD = 0.35  # crop margin around the box, as a share of its larger side
BUDGET = 4  # crop calls per scan, fixed before any test
CROP_LONG = 1568  # a crop larger than this is reduced (the model refuses images over its size limit)


@dataclass(frozen=True)
class Plan:
    item_id: str
    fields: frozenset  # subset of {"label", "quantity"}
    rect: tuple  # crop, canonical px
    rect_original: tuple  # the same crop, original px
    why: tuple  # what OpenCV saw
    priority: float


@dataclass(frozen=True)
class Observation:
    item_id: str
    field: str
    full: object  # the full-photo reading, kept as it was
    crop: object  # the crop reading, or None
    outcome: str  # same | provisional | conflict | unresolved
    effective: object  # what a person is shown before review
    reopen: bool = False  # a contrary reading against a person's answer
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _box(it, w, h):
    b = it.get("box")
    if not (isinstance(b, (list, tuple)) and len(b) == 4 and all(isinstance(v, (int, float)) for v in b)):
        return None
    x0, y0, x1, y1 = (float(v) for v in b)
    x0, x1 = sorted((max(0.0, x0), min(float(w), x1)))
    y0, y1 = sorted((max(0.0, y0), min(float(h), y1)))
    return (x0, y0, x1, y1) if x1 - x0 >= 4 and y1 - y0 >= 4 else None


def _sharpness(img, rect) -> float:
    x0, y0, x1, y1 = (int(round(v)) for v in rect)
    patch = img[y0:y1, x0:x1]
    if patch.size == 0:
        return 0.0
    g = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) if patch.ndim == 3 else patch
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def select(canon: np.ndarray, original: np.ndarray, scale: float, items: list[dict], budget: int = BUDGET):
    """Plans (at most `budget`, highest priority first) and skips [(item_id, field, reason)]."""
    h, w = canon.shape[:2]
    plans, skipped = [], []
    for it in items:
        b = _box(it, w, h)
        if b is None or not isinstance(it.get("id"), str):
            continue
        area = (b[2] - b[0]) * (b[3] - b[1]) / (w * h)
        fields, why = set(), []
        if it.get("label") and area < SMALL_BOX:
            fields.add("label")
            why.append(f"small_label:{area:.4f}")
        q = it.get("quantity")
        if isinstance(q, (int, float)) and not isinstance(q, bool) and q >= 2:
            if b[0] <= EDGE or b[1] <= EDGE or b[2] >= w - EDGE or b[3] >= h - EDGE:
                skipped.append((it["id"], "quantity", "unresolved:truncated"))
            else:
                fields.add("quantity")
                why.append(f"count:{q:g}")
        if not fields:
            continue
        rect_o = tuple(v / scale for v in b)
        if _sharpness(original, rect_o) < BLURRY:
            skipped += [(it["id"], f, "unresolved:blurry") for f in sorted(fields)]
            continue
        pad = PAD * max(b[2] - b[0], b[3] - b[1])
        rect = (max(0.0, b[0] - pad), max(0.0, b[1] - pad), min(float(w), b[2] + pad), min(float(h), b[3] + pad))
        # Smaller boxes first (where text is guessed), counts next.
        priority = (1.0 - area / SMALL_BOX if "label" in fields else 0.0) + (0.5 if "quantity" in fields else 0.0)
        plans.append(Plan(it["id"], frozenset(fields), tuple(round(v, 1) for v in rect),
                          tuple(round(v / scale, 1) for v in rect), tuple(why), round(priority, 4)))
    plans.sort(key=lambda p: -p.priority)
    over = plans[budget:]
    skipped += [(p.item_id, f, "skipped:budget") for p in over for f in sorted(p.fields)]
    return plans[:budget], skipped


def crop_image(original: np.ndarray, rect_original) -> tuple[np.ndarray, float]:
    """The crop at full detail, reduced only if it is larger than CROP_LONG. Returns it and its scale."""
    x0, y0, x1, y1 = (int(round(v)) for v in rect_original)
    c = original[y0:y1, x0:x1]
    s = min(1.0, CROP_LONG / max(c.shape[:2]))
    if s < 1.0:
        c = cv2.resize(c, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return c, s


def crop_jpeg(original: np.ndarray, rect_original) -> bytes:
    return cv2.imencode(".jpg", crop_image(original, rect_original)[0], [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()


def target_in_crop(p: Plan, scale: float, it: dict, crop_scale: float = 1.0) -> tuple:
    """The item's box inside its crop, in the pixels of the crop as sent. The asker is told where the item is,
    never what the full-photo reading said it was, so the second look is not steered by the first."""
    x0, y0 = p.rect_original[0], p.rect_original[1]
    b = [v / scale for v in it["box"]]
    cw, ch = p.rect_original[2] - x0, p.rect_original[3] - y0
    k = crop_scale
    return (int(round(cw * k)), int(round(ch * k)),
            *(int(round(min(max(v, 0), lim) * k)) for v, lim in ((b[0] - x0, cw), (b[1] - y0, ch), (b[2] - x0, cw), (b[3] - y0, ch))))


def _norm(s):
    return "".join(str(s).split()).lower() if s is not None else None


def reconcile(it: dict, fields, answer: dict | None, confirmed: dict, same_label=None) -> list[Observation]:
    """One observation per field, by the C1 table. `answer` None = failed, refused or malformed call.
    `same_label(a, b)`: optional judge for two label strings that differ only in language, script or form."""
    out = []
    for f in sorted(fields):
        full = it.get(f)
        person = confirmed.get((it["id"], f))
        if f == "label":
            crop = answer.get("label") if isinstance(answer, dict) and answer.get("label_readable") is True else None
            partial = isinstance(answer, dict) and answer.get("label_partial") is True
            if crop is not None and partial and len(_norm(crop)) < 3:
                crop = None  # a fragment of one or two letters is too little to agree or disagree with anything
            if crop is None:
                o = ("unresolved", full)
            elif full is None:
                o = ("provisional", None)  # shown as a candidate, never as the item's label
            elif _norm(crop) == _norm(full) or (partial and _norm(crop) in _norm(full)):
                o = ("same", full)  # a partly hidden label that matches what it shows
            elif same_label is not None and same_label(full, crop):
                o = ("same", full)  # same product written another way (language, brand vs generic name)
            else:
                o = ("conflict", full)
        else:
            c = answer.get("count") if isinstance(answer, dict) else None
            complete = isinstance(answer, dict) and answer.get("count_complete") is True
            ok = complete and isinstance(c, int) and not isinstance(c, bool) and c >= 0
            crop = c if ok else None
            if crop is None:
                o = ("unresolved", full)
            elif crop == full:
                o = ("same", full)
            else:
                o = ("conflict", full)
        outcome, effective = o
        reopen = False
        if person is not None:
            effective = person  # a person's answer stands; a contrary machine reading only reopens it
            reopen = crop is not None and _norm(crop) != _norm(person)
            if reopen:
                outcome = "conflict"
        out.append(Observation(it["id"], f, full, crop, outcome, effective, reopen))
    return out


ASK_PROMPT = """이 이미지는 냉장고·수납장 사진의 일부를 잘라낸 것입니다 (가로 {cw}px × 세로 {ch}px).
대상은 이 이미지 안의 사각형 [{x0}, {y0}, {x1}, {y1}] (픽셀, 왼쪽 위가 원점) 에 있는 물건 하나입니다. 주변의 다른 물건은 무시하세요.

아래 JSON 하나만 반환하세요. 산문·마크다운 금지.
{{"label": "대상 라벨에 인쇄된 제품명, 또는 null", "label_readable": true/false, "label_partial": true/false,
  "count": 정수 또는 null, "count_complete": true/false}}

- label: 대상의 라벨에서 **실제로 읽히는 글자만** 적으세요. 일부가 가려졌거나 잘렸어도 읽히는 부분은 적고 label_partial true.
  글자가 하나도 또렷하지 않으면 null, label_readable false. 모양·색·상식으로 짐작한 이름은 적지 마세요.
- count: 대상과 **같은 물건이 몇 개** 보이는지. 포장에 인쇄된 용량·개수(예: '10구')가 아니라 실제로 보이는 개수입니다.
- count_complete: 그 무리 전체가 이 이미지 안에 다 보이면 true. 가장자리에서 잘렸거나 가려져 다 셀 수 없으면 false.
"""


class Zoomer:
    """Runs the pass with any `asker` (a model call, a recording, or a fake):
    ask(crop_jpeg, fields, target) -> dict | None, where target = (crop_w, crop_h, x0, y0, x1, y1)."""

    def __init__(self, asker, budget: int = BUDGET, judge=None):
        self.asker, self.budget, self.judge = asker, budget, judge

    def run(self, frames, items: list[dict], confirmed: dict | None = None) -> dict:
        confirmed = confirmed or {}
        plans, skipped = select(frames.image, frames.original, frames.scale, items, self.budget)
        by_id = {it.get("id"): it for it in items}
        observations, calls = [], []
        for p in plans:
            it = by_id[p.item_id]
            try:
                img, k = crop_image(frames.original, p.rect_original)
                jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()
                answer = self.asker.ask(jpg, p.fields, target_in_crop(p, frames.scale, it, k))
            except Exception as e:  # a failed call keeps the existing evidence, unresolved
                answer = None
                calls.append({"item_id": p.item_id, "error": str(e)[:60] or type(e).__name__})
            else:
                calls.append({"item_id": p.item_id, "answer": answer})
            observations += reconcile(it, p.fields, answer, confirmed, self.judge.same if self.judge else None)
        for item_id, f, reason in skipped:
            it = by_id.get(item_id, {})
            observations.append(Observation(item_id, f, it.get(f), None, "unresolved", it.get(f), note=reason))
        return {
            "plans": [{**asdict(p), "fields": sorted(p.fields)} for p in plans],
            "calls": calls,
            "observations": [o.to_dict() for o in observations],
        }
