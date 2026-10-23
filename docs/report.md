# Glass Pantry Shelf Check: technical report (DRAFT, 2026-10-24)

> Development observations and held-out results are kept apart below. The held-out zoom results were measured with
> count re-reads on; the current label-only configuration has not been evaluated on a fresh held-out set. Numbers
> marked **[dev]** come from photos used during development; they show behaviour, not accuracy.

## 1. Problem
People forget what is in their fridge. Typing an inventory is tedious, so a phone photo is the natural input. A
vision-language model can list what a shelf photo shows, but a single reading can contain plausible but incorrect
names: a model that cannot read a small label may still write a product name. On our development photos a milk
carton was named "1회용 간장" in one run and "1등급 계란" in the next.

This prototype adds targeted checks and re-reads around the model. Both a plain reading and this workflow still need
a person to confirm the list; the aim is fewer silent errors, not automatic filing.

## 2. Users
Households keeping track of food, Korean kitchens first (a label does not always say what is inside a reused jar).
Glass Pantry is our mobile app for this, in TestFlight testing. **This entry is a separate web prototype** inspired by
the app's workflow; it reuses the app's frozen scan prompt and an export of its appliance catalogue. Its OpenCV
verification loop is **not** in the phone app, and identical results are not claimed. It is a prototype: user
benefit and usability have not been measured.

## 3. What it does
The page follows the app's steps (docs/pipeline.md): **pick the fridge** → **trace each compartment over a photo** →
**fill each shelf or drawer from its own photo**. A person confirms every layout and every list; the fridge is kept
in the browser tab only (session storage). The browser prototype supports catalogue appliances; cupboards, pantries
and nested containers are future work.

**Picking the fridge (one model call).** The person photographs the model sticker or the fridge. OpenCV's photo
gate runs first: a blurry or smeared photo is sent back with the reason, before any model call or daily admission
(AWS processing still runs). The gate's brightness and glare limits were set on shelf photos and would refuse a clean
white sticker, so they are not applied here. Claude reads the model number as printed, the maker and the fridge's
kind; it never picks a catalogue row. Plain code matches the reading: the exact model number; else a sibling number
of the same maker (a shared 7-character prefix); else the generic layout of that kind and library fridges of that
kind. Maker conflicts block exact and family matches when both makers are among the supported Samsung, LG and Winia
names; other makers are not recognised by that filter. The kind may come from explicit sticker text or from a
matched catalogue candidate (including a family match). An answer that is not one complete JSON object (one code
fence allowed) or was cut off suggests nothing. Suggestions do not verify the appliance's actual interior; the
person chooses, then confirms with the same button as picking from the list.

**Tracing a compartment (no model call).** Two steps on the same photo. *Step 1, outline the opening:* a
see-through shape with named corners (top-left …) and edges (top edge, left wall …); the person drags a corner or a
whole edge onto the opening. OpenCV checks the quadrilateral (convex, ordered, area ≥ 15%, corner angles 55-125°,
opposite sides within 2.5×) and straightens the opening plane with `getPerspectiveTransform` + `warpPerspective`.
*Step 2, match the shelves and drawers:* the catalogue's levels appear inside the outline in perspective (the same
homography, computed in the browser), named as they will be saved; the person drags, adds or removes lines and
confirms. We also built OpenCV suggestions for the corners (largest valid convex quadrilateral) and for snap edges
(Canny + Hough row profile); both failed their pre-set bar on the test photos and are switched off (§6), so OpenCV
draws nothing of its own. A removed shelf's things move to "Unplaced"; nothing is deleted. A photo whose opening
cannot be framed may be traced unstraightened and is labelled unverified; even then an outline the lines cannot be
drawn through (crossed corners, a corner on the diagonal, under 5% of the photo) is refused.

**Seeing the fridge in 3D (no model call).** The web 3D view draws live compartment shelves and drawers and their
placed items as schematic boxes or cylinders (three.js). The shelf photo's item boxes guide horizontal position,
width and height, clamped to stay inside the item's own level; depth is approximate, not reconstructed or measured.
Older rows without placement are spread evenly. Door bins, retired levels and Unplaced things are not drawn in 3D.
The geometry is a pure function of the twin (`web/scene.js`, tested on all 16 layouts) and never changes the twin.

**Filling a level.** One shelf photo goes through an agent loop in which OpenCV measurements gate the model call,
select close-ups and contribute shelf-support evidence; the recommendation also depends on parser status and model
comparisons.

1. **Frames.** In the browser, the chosen image is re-encoded and reduced to at most 3024 px before upload. The
   server keeps that received image in memory for close-ups and makes one canonical frame (long edge at most 1568
   px) used by every check and sent to the model. (Development runs on the command line used full-resolution files,
   so their close-ups are not necessarily equivalent to the browser's.)
2. **Photo gate (OpenCV).** Laplacian variance (blur), Sobel gradient-energy ratio (hand shake), mean brightness and
   clipped highlights. A failed photo → *retake*, with no model call. The thresholds are development-calibrated
   heuristics, not a validated readability test.
3. **Model reading.** Claude Opus 5.5 lists the items, each with a pixel box, a label reading, a count, and the
   shelf edges. The prompt is the app's scan prompt, frozen with a hash.
4. **Shelf check (OpenCV).** Canny + probabilistic Hough give a row profile of near-horizontal edges. Each shelf
   line the model proposed is tested for horizontal edge support within ±2% of the image height; a line without
   support → *ask*. This does not establish that an edge is a shelf or that a shelf is absent, and a line at the
   photo's border may raise a false question or match a nearby edge. OpenCV never adds a shelf.
5. **Zoom pass (OpenCV selects, the model re-reads).**
   - **Selection:** labelled items whose box is under 3% of the photo, including boxes that touch the photo edge.
     (Count re-reads were built and tested and are now **off**, §6; only that disabled path skips edge-cut groups.)
   - **Skipped, with no call:** label candidates whose sharpness (Laplacian variance on a patch reduced to at most
     400 px) is below 60, and plans beyond the budget of 4 close-ups per scan.
   - **The close-up:** cut from the received image, reduced only to the model's size limit. The model is told
     *where* the item is in the crop, never what the first reading said.
6. **Reconcile.**
   - Only the label (and, when count re-reads are on, the count) may be re-observed; box, shelf and identity are
     never changed.
   - Label differences left after normalisation and accepted partial matches go to a text-only judge (Claude Haiku
     5.5): the same product in another language or form? The judge can only clear a difference; a failed judge call
     cannot clear it.
   - A real disagreement becomes a conflict shown with both readings; the first is prefilled and the person may
     keep or edit it before confirming the whole list (individual conflicts are not mandatory answer steps).
   - A failed, cut-off or malformed close-up stays "unresolved", keeps the first reading, and does not by itself
     force *ask*.
7. **Recommend.** The engine recommends *file*, *ask* or *retake*; these are not storage operations. An incomplete
   first answer keeps its closed item records for review and recommends *ask*. Reasons only accumulate: a confirmed
   close-up never clears an unconfirmed shelf. Scans append to the browser twin without replacing saved entries.
   **A person confirms the list before anything is kept.**

![Architecture: browser, AWS Lambda with OpenCV 5, Anthropic API](architecture/architecture.png)

The browser holds the fridge (session storage) and draws it. The Lambda container receives one photo per request,
keeps it in memory only for that request, runs the OpenCV steps, and calls the Anthropic API. A shelf scan or a
fridge identification takes one admission from the DynamoDB daily counter before any model call (identify's quality
gate runs before its admission, the shelf scan's gate just after it); outline straightening needs no admission. The API key and the owner's on/off switch are in SSM Parameter Store.

![Agent loop for one shelf photo: OpenCV's evidence leads to retake, ask or file](architecture/agent_loop.png)

A recorded run (the page's sample, `web/samples/sample.json`) shows the loop changing its recommendation: the gate
passed (Laplacian variance 468), Claude listed 28 items, OpenCV selected 4 close-ups, one label re-read disagreed
with the first reading (`label_conflict:i11`), so the recommendation became **ask**, not file.

## 4. OpenCV 5 in the loop
Pinned: `opencv-contrib-python-headless==5.0.0.93` (uv.lock).

| Function | Implementation | What it changes |
|---|---|---|
| Photo gate | OpenCV `Laplacian` and `Sobel`; NumPy gradient-energy, mean-intensity and clipped-white calculations | retake with no model call (shelf scans; for identify only blur and shake) |
| Shelf check | `Canny`, `HoughLinesP` (OpenCV 5 N×4 output) | ask about a proposed shelf line without horizontal edge support |
| Close-up selection | box geometry, `Laplacian` variance on a reduced patch | which items get a second look; which are left unresolved |
| Crops | `resize` (`INTER_AREA`), `imencode` | the evidence the second look sees |
| Outline check + straightening | quad validation, `getPerspectiveTransform`, `warpPerspective` | refuses an outline it cannot straighten, with the reason in words; a front view of the opening plane |
| Opening suggestion (built, **off**) | `Canny`, `findContours`, `convexHull`, `approxPolyDP` | failed its pre-set bar (§6); people place corners by hand |
| Snap edges (built, **off**) | `Canny`, `HoughLinesP` row profile on the straightened view | failed its pre-set bar (§6) |
| Change detection (experiment) | `SIFT`, `BFMatcher` kNN + ratio test, `findHomography` with `USAC_MAGSAC`, `warpPerspective`, gradient ZNCC | per old item: unchanged / possible change / cannot compare |

## 5. AWS deployment
- **Compute:** the repository configures an x86_64 Lambda container image (2048 MB, 150 s timeout) behind a
  Function URL in us-east-1, deployed with SAM by GitHub Actions on qualifying pushes to `main` (documentation-only
  pushes do not deploy) or manual dispatch. CI signs in with GitHub OIDC; no long-lived AWS deployment keys. Each
  deploy runs the tests first, smoke-tests the endpoint, and runs four negative-permission probes on the deploy role.
- **Endpoint:** `/fridge` (this page), `/` (single-shelf check), `/health` (live/paused, engine version).
- **Guards:**
  - the owner's on/off switch and the Anthropic API key in SSM Parameter Store;
  - a shared cap of 40 admissions per UTC day in DynamoDB (an atomic conditional update; fails closed). This is a
    call cap, not a dollar budget; the provider-side spending limit is set outside this repository;
  - upload size and pixel limits;
  - a deadline on how long the application waits for each model call (an already-sent provider request is not
    cancelled).
- **Logs:** CloudWatch logs hold codes and counts only: no photos, crops, labels or model text.
- **Most model calls per scan:** 1 reading + 4 close-ups + 4 judge calls. Identifying the fridge: 1 call.
- **Model cost [dev]:** the count-enabled development run's token-price estimate was $2.14 for 24 scans (about
  $0.089 per scan), excluding AWS and other infrastructure. Current label-only cost is unmeasured.

## 6. Evaluation
**Protocol** (frozen before the test photos were opened):
- **Development:** 12 earlier photos of one kitchen and all earlier recorded runs.
- **Test:** new capture sessions. Split by shelf and session.
- **Annotation (test):** for each labelled item the model proposed, the owner saw the item cut from the image with
  both readings and marked which was right, before scoring.
- **Measure:** a label-conflict diagnostic: of the wrong first readings, how many did the zoom pass flag; how many
  right readings did it flag (false flags); plus model-price estimates and time per scan without and with the zoom
  stage, from the same runs.

**[dev] observations, 24 scans of 12 photos:** seven label conflicts were raised. A later Claude-based review of the
crops judged four first readings wrong (두부 → 도토리묵; the milk carton twice; an ice-cream brand), two conflicts false
alarms (from a cut-off judge reply, fixed since) and one unclear. **These judgements are not independent human
ground truth.** Twenty-three close-up label readings agreed with the first reading.

**[test] results** (6 new shelf photos from 3 spaces, before/after one change each, 2 runs per photo = 12 scans).
**Measured with count re-reads on**; the label-only configuration has not been measured on held-out photos.
- **Labels:** among the 28 scored label-reading instances (repeated photos, so not 28 independent products), **no
  first reading was wrong**, so the zoom pass had nothing to catch on this set. It raised **2 false label alarms**
  (2 of 28). This set cannot establish error-detection recall or an accuracy improvement. Not measured: items the
  model never listed, and the accuracy of the final list.
- **Counts:** 5 count re-reads, **5 false alarms**: four on an egg tray (first reading 30 eggs, close-up "1" tray)
  and one 1000 → 1; the owner chose the first reading every time. Count re-reads are now off; label re-reads stay.
- **Model-price estimate and time per scan, count-enabled configuration:** $0.065 → $0.080 with the zoom stage
  (+23%). The diagnostic's upper-middle runtimes (the 7th sorted value of 12) were 19.5 s without the zoom-stage
  suffix and 23.9 s with it: same-run summaries, not conventional medians or an independently timed comparison.
- **Step 3 suggestions** (5 compartment photos: 3 with the whole opening visible, 2 deliberately not): corner
  suggestion within 3% of the true corners on 0 of 3 (worst corner 12-19% of the diagonal off) and offered on both
  photos where it should not have been; snap targets found 14 of 15 true edges but added 3, 13 and 15 false ones.
  Both failed the bar set before testing (offered on ≥60% with median error ≤3%; recall ≥60% with ≤2 false per
  photo) and are off.

**Identifying the fridge** (first run, prompt not changed afterwards; 5 photos from one kitchen; 5 calls, model-price
estimate $0.063): the three photos of the rating sticker were read as RB38J7200S4 and matched exactly; a photo of
the open fridge with no sticker was read as "fridge on top, freezer below" with no model number invented, and got
the generic layout of that kind first; a shelf close-up got no suggestion. Not tested on real photos: a sibling model
number, another maker, a closed fridge front.

**Reading these together:** on the development photos, an AI review judged that the zoom pass turned four wrong
product names into questions; on the new photos there was no wrong first label among the 28 scored instances, and
the zoom pass only added questions. One kitchen, 12 scans: no recall or end-to-end accuracy benefit is established.
In the count-enabled configuration it cost +$0.015 (model price) and +4 s per scan with 2 of 28 false label
questions.

**Failures we saw and what we did:**

| Failure | Fix |
|---|---|
| A crop larger than the model's image limit (HTTP 400) | Crops reduced to its limit |
| An empty list from one full reading | Now recommends asking "nothing read?" instead of filing an empty shelf |
| Legible labels on 24 MP photos measured as "blurry" | Sharpness measured on a reduced patch |
| The model placing a shelf edge on the photo's bottom border | Open, see §7 |
| A red-team pass on the live page (9 findings: sideways scrolling on phones, small touch targets, degenerate outlines accepted, refused saves shown out of view, …) | All fixed and reviewed; nothing was lost in any tested sequence |

## 7. Limitations
- Only items the model listed are checked. An item it never mentions is not found by the zoom pass.
- Only small labels are re-read (count re-reads are built but off). A wrong name on a large box is not flagged, and
  a wrong count is never questioned.
- The quality gate and the shelf check are heuristics calibrated on development photos; a border shelf line may
  raise a false question.
- The label judge is a model too. It can call two different products "the same" (we saw a misread brand judged
  equal to the real one).
- Browser uploads are reduced to 3024 px; development runs used full-resolution files.
- The 3D view is schematic (approximate depth, no door bins) and needs WebGL and a CDN (three.js 0.160.0); if it
  cannot load, the 2D drawing stays.
- **Change detection** is an experiment: tested on generated images, not on real handheld pairs. It says nothing
  about things added outside the old items' boxes.
- **Identifying the fridge** knows 11 models and 5 generic layouts. The "same family" rule is a prefix heuristic,
  and maker conflicts are only recognised for Samsung, LG and Winia.
- Real-phone touch use has been tested in emulation; a test on an iPhone is pending at the time of writing.
- **[dev]** numbers come from one kitchen.

## 8. Responsible use
- **Live photos:** the live handler processes uploaded photos in memory and does not intentionally keep their
  images or readings. Photos sent for reading are also sent to Anthropic; our implementation does not set
  Anthropic's retention policy. Application logs omit images, crops, labels and model text. The page says this
  before any upload and asks for consent.
- **The recorded example:** separately, the server stores and publicly serves one recorded development example (a
  photo of the owner's fridge and its readings), published with the owner's approval.
- **People decide:** nothing is kept without a person's confirmation; the engine recommends asking when its
  evidence disagrees.
- **Uploads:** upload only photos you have permission to share with AWS and Anthropic; leave people and personal
  documents out of the frame.
- **Cost and abuse:** an owner switch, a shared daily admission cap (anonymous visitors share it, so it can be used
  up by others), and a separate API key with its own spending limit.

## 9. Shipped vs shown

| Shown | Status |
|---|---|
| Web page + engine on AWS | Deployed from `main`; the owner's switch decides whether live reading is on |
| Recorded example on the page | Replay of one real run, labelled RECORDED |
| Glass Pantry app footage in the video | The existing mobile app (TestFlight). The OpenCV loop is **not** in the app; a prototype build, if shown, is labelled as such |
| Fridge from a sticker photo, two-step outline editor, 3D view | On the web page only, not in the phone app (the app has its own 3D renderer) |
| Change detection | Experiment, not in the service |
