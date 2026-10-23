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

**Tracing a compartment (no model call).** The person places the opening's four corners; OpenCV checks the
quadrilateral (area, angles, foreshortening) and straightens the opening plane with `warpPerspective`; the person
draws the shelf lines on the straightened view. We also built OpenCV suggestions for the corners (largest valid
convex quadrilateral) and for snap edges (Canny + Hough row profile); both failed their pre-set bar on the test
photos and are switched off (§6). A removed shelf's things move to "Unplaced"; nothing
is ever deleted. A photo whose opening cannot be framed is traced unstraightened and labelled unverified.

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
     - counts of two or more.
   - **Skipped, with no call:**
     - groups cut by the photo edge;
     - boxes with no fine detail left (Laplacian variance at a fixed 400 px scale below 60): blur means the
       information is gone, not that it should be guessed.
   - **Budget:** at most 4 close-ups per scan.
   - **The close-up:** cut from the original at full detail, reduced only to the model's size limit. The model is
     told *where* the item is in the crop, never what the first reading said.
6. **Reconcile.**
   - Only the label and the count may be re-observed; box, shelf and identity are never changed.
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

## 4. OpenCV 5 in the loop

| Function | OpenCV | What it changes |
|---|---|---|
| Photo gate | `Laplacian`, `Sobel`, structure tensor, histogram | retake, with no model call |
| Shelf check | `Canny`, `HoughLinesP` (OpenCV 5 N×4 output) | ask about a shelf the photo does not show |
| Close-up selection | box geometry, `Laplacian` variance at a fixed scale | which items get a second look; which are left unresolved |
| Crops | `resize` (`INTER_AREA`), `imencode` | the evidence the second look sees |
| Opening suggestion | `Canny`, `findContours`, `convexHull`, `approxPolyDP`, quad validation | four dashed corners a person confirms or moves |
| Straightening | `getPerspectiveTransform`, `warpPerspective` | a front view of the opening plane to trace on |
| Snap edges | `Canny`, `HoughLinesP` row profile on the straightened view | where a dropped shelf line lands |
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
- **Most model calls per scan:** 1 reading + 4 close-ups + 4 judge calls.
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
truth by the owner's annotation before scoring):
- **Labels:** 28 labelled readings, all annotated. **0 were wrong first readings**, so the zoom pass had nothing to
  catch on this set. It raised **2 false label alarms** (2 of 28).
- **Counts:** 5 count re-reads, **5 false alarms**: the close-up counted packages (one egg tray) where the first
  reading counted units (30 eggs). Count re-reads are now switched off; label re-reads stay.
- **Cost and time per scan:** $0.065 → $0.080 with zoom (+23%); median 19.5 s → 23.9 s.
- **Step 3 suggestions** (5 compartment photos: 3 with the whole opening visible, 2 deliberately not): corner
  suggestion within 3% of the true corners on 0 of 3 (worst corner 12-19% of the diagonal off) and offered on both
  photos where it should not have been; snap targets found 14 of 15 true edges but added 3, 13 and 15 false ones. Both
  failed the bar set before testing (offered on ≥60% with median error ≤3%; recall ≥60% with ≤2 false per photo) and
  are off.

**Reading these together:** on the development photos the zoom pass turned 4 wrong product names into questions;
on the new photos the model read every label right and the zoom pass only added questions. One kitchen, 12 scans:
the honest conclusion is that the zoom pass is a safety net whose value depends on how hard the photo is, at a
known cost (+$0.015, +4 s, ~7% false label questions).

**Failures we saw and what we did:**

| Failure | Fix |
|---|---|
| A crop larger than the model's image limit (HTTP 400) | Crops reduced to its limit |
| An empty list from one full reading | Now asks "nothing read?" instead of filing an empty shelf |
| Legible labels on 24 MP photos measured as "blurry" | Sharpness measured at a fixed scale |
| The model placing a shelf edge on the photo's bottom border | Open, see §7 |

## 7. Limitations
- Only items the model listed are checked. An item it never mentions is not found by the zoom pass.
- Only small labels and counts are re-read. A wrong name on a large box is not flagged.
- A shelf edge proposed at the frame border cannot be confirmed by OpenCV, so the page asks about it (noise).
- The label judge is a model too. It can call two different products "the same" (we saw a misread brand judged
  equal to the real one).
- **Change detection** is an experiment: tested on generated images, not on real handheld pairs. It says nothing
  about things added outside the old items' boxes.
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
| Change detection | Experiment, not in the service |
