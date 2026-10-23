# Glass Pantry Shelf Check: technical report (DRAFT, 2026-10-23)

> Numbers marked **[dev]** come from photos used during development and tuning; they show behaviour, not accuracy.
> The held-out results go in §6 once the test photos are annotated.

## 1. Problem
People forget what is in their fridge. Typing an inventory is tedious, so a phone photo is the natural input. A
vision-language model can list what a shelf photo shows, but it fails in two quiet ways:
- **Small text is guessed.** A model that cannot read a small label still writes a plausible product name. On our
  photos a milk carton was named "1회용 간장" in one run and "1등급 계란" in the next.
- **The list is never doubted.** A reading that looks complete is filed as fact.

A fridge app that silently files wrong names is worse than one that asks.

## 2. Users
Households keeping track of food. Glass Pantry is our mobile app for this (Korean kitchens first: a label does not
always say what is inside a reused jar). This entry is the vision engine behind the scan, built as a service with
a web page so that anyone can try it.

## 3. What it does
The page follows the Glass Pantry app's pipeline (docs/pipeline.md): **pick the fridge** (layouts exported from the
app's catalogue) → **trace each compartment over a photo** → **fill each shelf, drawer or door bin from its own
photo**. A person confirms every layout and every list; the fridge is kept in the browser tab only.

**Picking the fridge (one model call).** The person photographs the model sticker or the fridge. OpenCV's photo
gate runs first: a blurry or smeared photo is sent back with the reason and costs nothing (its brightness and
glare limits were set on shelf photos and would refuse a clean white sticker, so they are not applied here). Claude
reads the model number as printed and the fridge's kind (fridge over freezer, side-by-side …); it never picks a
catalogue row. Plain code matches the reading: the exact model number; else a sibling number of the same maker
(a shared 7-character prefix); else the generic layout of that kind and library fridges of that kind. A maker that
contradicts the catalogue row is never an exact match, and an answer that is not exactly one JSON object, or was cut
off, suggests nothing. The person chooses, then confirms with the same button as picking from the list.

**Tracing a compartment (no model call).** Two steps on the same photo. *Step 1, outline the opening:* a
see-through shape with named corners (top-left …) and edges (top edge, left wall …); the person drags a corner or a
whole edge onto the opening. OpenCV checks the quadrilateral (convex, ordered, area ≥ 15%, corner angles 55-125°,
opposite sides within 2.5×) and straightens the opening plane with `getPerspectiveTransform` + `warpPerspective`.
*Step 2, match the shelves and drawers:* the catalogue's levels appear inside the outline in perspective (the same
homography, computed in the browser), named as they will be saved; the person drags, adds or removes lines and
confirms. We also built OpenCV suggestions for the corners (largest valid convex quadrilateral) and for snap edges
(Canny + Hough row profile); both failed their pre-set bar on the test photos and are switched off (§6), so OpenCV
draws nothing of its own. A removed shelf's things move to "Unplaced"; nothing is ever deleted. A photo whose
opening cannot be framed is traced unstraightened and labelled unverified (an outline the lines cannot be drawn
through, such as crossed corners, is refused even then).

**Filling a level.** One shelf photo goes through an agent loop. **OpenCV's evidence decides each next action:**

1. **Frames.** One canonical image (1568 px long edge) is used by every check and sent to the model, so no check
   can pass a different photo from the one that is read. The full-resolution original is kept for close-ups.
2. **Photo gate (OpenCV).** Laplacian variance (blur), gradient anisotropy (hand shake), mean brightness, clipped
   highlights. A failed photo → *retake*. **No model call is spent.**
3. **Model reading.** Claude Opus 5.5 lists the items, each with a pixel box, a label reading, a count, and the
   shelf edges. The prompt is our app's production prompt, frozen with a hash.
4. **Shelf check (OpenCV).** Canny + probabilistic Hough give a row profile of near-horizontal edges. Each shelf
   line the model proposed must be backed by a real edge within ±2% of the height. If not → *ask*. OpenCV never
   adds a shelf.
5. **Zoom pass (OpenCV picks, the model re-reads).**
   - **Selection** (from box geometry and image content):
     - labelled items whose box is under 3% of the photo;
     - (built and tested, now **off**: counts of two or more; see §6).
   - **Skipped, with no call:**
     - groups cut by the photo edge;
     - boxes with no fine detail left (Laplacian variance at a fixed 400 px scale below 60): blur means the
       information is gone, not that it should be guessed.
   - **Budget:** at most 4 close-ups per scan.
   - **The close-up:** cut from the original at full detail, reduced only to the model's size limit. The model is
     told *where* the item is in the crop, never what the first reading said.
6. **Reconcile.**
   - Only the label (and, when count re-reads are on, the count) may be re-observed; box, shelf and identity are
     never changed.
   - Two label strings that differ go to a text-only judge (Claude Haiku 5.5): is this the same product in
     another language or form? The judge can only clear a difference; it never supplies a label.
   - A real disagreement becomes a question; neither reading wins.
   - A failed, cut-off or malformed answer is "unresolved" and keeps the first reading.
   - A person's earlier answer is never overwritten.
7. **Decide.**
   - Reasons only accumulate: a confirmed close-up never clears an unconfirmed shelf.
   - An empty, cut-off or ambiguous reading is never filed.
   - The page shows the overlays, the list, and every question. **A person confirms.**

[Diagram: docs/architecture/architecture.png]

![Agent loop for one shelf photo: OpenCV's evidence decides retake, ask or file](architecture/agent_loop.png)

A recorded run (the page's sample, `web/samples/sample.json`) shows the loop changing its action: the gate passed
(Laplacian variance 468), Claude listed 28 items, OpenCV picked 4 close-ups, one label re-read disagreed with the
first reading (`label_conflict:i11`), so the action became **ask**, not file.

## 4. OpenCV 5 in the loop

| Function | OpenCV | What it changes |
|---|---|---|
| Photo gate | `Laplacian`, `Sobel`, structure tensor, histogram | retake, with no model call (shelf scans and fridge identification) |
| Shelf check | `Canny`, `HoughLinesP` (OpenCV 5 N×4 output) | ask about a shelf the photo does not show |
| Close-up selection | box geometry, `Laplacian` variance at a fixed scale | which items get a second look; which are left unresolved |
| Crops | `resize` (`INTER_AREA`), `imencode` | the evidence the second look sees |
| Outline check + straightening | quad validation, `getPerspectiveTransform`, `warpPerspective` | refuses an outline it cannot straighten, with the reason in words; a front view of the opening plane |
| Opening suggestion (built, **off**) | `Canny`, `findContours`, `convexHull`, `approxPolyDP` | failed its pre-set bar (§6); people place corners by hand |
| Snap edges (built, **off**) | `Canny`, `HoughLinesP` row profile on the straightened view | failed its pre-set bar (§6) |
| Change detection (experiment) | `SIFT`, `BFMatcher` kNN + ratio test, `findHomography` with `USAC_MAGSAC`, `warpPerspective`, gradient ZNCC | per old item: unchanged / possible change / cannot compare |

## 5. AWS deployment
- **Compute:** Lambda container image (x86_64) behind a Function URL, deployed by SAM from GitHub Actions. Sign-in
  is GitHub OIDC to a role scoped to this stack's own resources; no long-lived keys.
- **Guards:**
  - the owner switch and the API key in Parameter Store;
  - a shared daily scan cap in DynamoDB (an atomic conditional update; fails closed);
  - upload size and pixel limits;
  - a wall-clock budget for every model call.
- **Logs:** CloudWatch logs hold codes and counts only: no photos, crops, labels or model text.
- **Most model calls per scan:** 1 reading + 4 close-ups + 4 judge calls. Identifying the fridge: 1 call, counted
  against the same daily cap, after the photo gate.
- **Cost [dev]:** about $0.09 per scan including close-ups; 31 s for a scan inside the Lambda image.

## 6. Evaluation
**Protocol** (frozen before the test photos were opened):
- **Development:** 12 earlier photos of one kitchen and all earlier recorded runs.
- **Test:** new capture sessions, plus teammates' kitchens where available. Split by shelf and session.
- **Annotation:** for each labelled item the model proposed, a person sees the item cut from the original with
  both readings and marks which is right.
- **Measure:** a label-conflict diagnostic. Of the wrong first readings, how many did the zoom pass flag? How
  many right readings did it flag (false flags)? Plus cost and time per scan without and with zoom, from the same
  runs.

**[dev] results, 24 scans of 12 photos:**
- 7 label disagreements:
  - **4 were wrong first readings caught:** 두부 → 도토리묵; the milk carton twice; a misread ice-cream brand;
  - 2 were false alarms from a cut-off judge reply (fixed since);
  - 1 was unclear.
- 23 close-up label readings agreed.

**[test] results** (6 new shelf photos from 3 spaces, before/after one change each, 2 runs per photo = 12 scans;
truth by the owner's annotation before scoring). **Measured with count re-reads ON** (the configuration at the
time); the current label-only configuration has not been measured on held-out photos.
- **Labels:** among the 28 scored eligible label readings the model proposed, **no first reading was wrong**, so
  the zoom pass had nothing to catch on this set. It raised **2 false label alarms** (2 of 28). Not measured:
  items the model never listed, and the accuracy of the final list.
- **Counts:** 5 count re-reads, **5 false alarms**: four were an egg tray (first reading 30 eggs, close-up "1"
  tray) and one was 1000 → 1; the owner chose the first reading every time. Count re-reads are now off; label
  re-reads stay.
- **Cost and time per scan, count-enabled configuration:** $0.065 → $0.080 with zoom (+23%); median
  19.5 s → 23.9 s.
- **Step 3 suggestions** (5 compartment photos: 3 with the whole opening visible, 2 deliberately not): corner
  suggestion within 3% of the true corners on 0 of 3 (worst corner 12-19% of the diagonal off) and offered on both
  photos where it should not have been; snap targets found 14 of 15 true edges but added 3, 13 and 15 false ones. Both
  failed the bar set before testing (offered on ≥60% with median error ≤3%; recall ≥60% with ≤2 false per photo) and
  are off.

**Identifying the fridge** (first run, prompt not changed afterwards; 5 photos from one kitchen; 5 calls, $0.063):
the three photos of the rating sticker were read as RB38J7200S4 and matched exactly; a photo of the open fridge
with no sticker was read as "fridge on top, freezer below" with no model number invented, and got the generic
layout of that kind first; a shelf close-up got no suggestion. Not tested on real photos: a sibling model number,
another maker, a closed fridge front.

**Reading these together:** on the development photos the zoom pass turned 4 wrong product names into questions;
on the new photos there was no wrong first label among the 28 scored readings, and the zoom pass only added
questions. One kitchen, 12 scans: the zoom pass is a safety net whose value depends on how hard the photo is. In the
count-enabled configuration it cost +$0.015 and +4 s per scan with 2 of 28 false label questions; the label-only
cost is expected to be lower but is unmeasured.

**Failures we saw and what we did:**

| Failure | Fix |
|---|---|
| A crop larger than the model's image limit (HTTP 400) | Crops reduced to its limit |
| An empty list from one full reading | Now asks "nothing read?" instead of filing an empty shelf |
| Legible labels on 24 MP photos measured as "blurry" | Sharpness measured at a fixed scale |
| The model placing a shelf edge on the photo's bottom border | Open, see §7 |

## 7. Limitations
- Only items the model listed are checked. An item it never mentions is not found by the zoom pass.
- Only small labels are re-read (count re-reads are built but off). A wrong name on a large box is not flagged, and
  a wrong count is never questioned.
- A shelf edge proposed at the frame border cannot be confirmed by OpenCV, so the page asks about it (noise).
- The label judge is a model too. It can call two different products "the same" (we saw a misread brand judged
  equal to the real one).
- **Change detection** is an experiment: tested on generated images, not on real handheld pairs. It says nothing
  about things added outside the old items' boxes.
- **Identifying the fridge** knows 11 models and 5 generic layouts. The "same family" rule is a prefix heuristic,
  and a sticker alone does not say the fridge's kind unless the model is in the catalogue.
- **[dev]** numbers come from one kitchen.

## 8. Responsible use
- **Photos:** sent to our AWS function and to Anthropic to be read, and not stored by us. The page says so before
  upload. Our logs keep no image or text from the photo.
- **People decide:** nothing is filed without a person's confirmation, and the engine asks rather than asserts
  when its evidence disagrees.
- **Cost and abuse:** an owner switch, a daily cap, and a separate API key with its own spending limit.

## 9. Shipped vs shown

| Shown | Status |
|---|---|
| Web page + engine on AWS | Live (switch on during judging, capped) |
| Recorded example on the page | Replay of one real run, labelled RECORDED |
| Glass Pantry app footage in the video | The released app. The zoom pass is **not** in the released app; a prototype build, if shown, is labelled as such |
| Fridge from a sticker photo, two-step outline editor | Live on the web page; not yet in the phone app |
| Change detection | Experiment, not in the service |
