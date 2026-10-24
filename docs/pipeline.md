# The pipeline: from a photo to a fridge you can open

This web prototype follows the four steps of the Glass Pantry phone app's workflow, reusing its scan prompt and an
export of its appliance catalogue; it is separate from the app, and identical results are not claimed. OpenCV
checks and straightens; a person confirms every layout and every list. Status
markers: **built** (code and tests on this branch), **planned** (decided, not yet built).

## The four steps

| Step | The person | Claude | OpenCV | Status |
|---|---|---|---|---|
| 1. Identify the fridge | photographs the model sticker or the fridge, or picks from the list; chooses among the suggestions | reads the model number and the fridge's kind (never picks a row) | photo gate first: photos below the configured blur/shake thresholds are refused before admission or a model call | **built** (`verifier/identify.py`, `POST /identify`) |
| 2. Load its layout | sees a flat front view: compartments, shelves, drawers, door bins | none | none (the app's catalogue as data, `web/layouts/layouts.json`) | **built** |
| 3. Confirm the layout over a photo | one photo per compartment; step 1 drags a see-through outline (named corners and edges) onto the opening; step 2 drags the catalogue's shelves and drawers, drawn in perspective, onto the real ones; confirms | none | validates the quad; `warpPerspective` to a front view of the opening plane. Corner suggestions and edge snap targets are built but **off**: they failed their pre-set bar on the test photos (below) | **built** (`verifier/opening.py`, `POST /straighten`) |
| 4. Fill a shelf, drawer or door bin | photographs it; drags two lines to this shelf's top and bottom (only that strip is sent); edits and confirms the list | reads the items | photo gate; shelf check; zoom pass (small labels re-read from the received strip; count re-reads built but off after their test) | **built** (`POST /scan`) |
| 5. Photograph it again: what changed? | photographs the same shelf later; checks the lines; answers the questions; may ask for the marked spots to be read; applies | reads only the marked spots, if asked | OpenCV 5 ALIKED + LightGlue align the new strip to the last one; per item no visible change / possible change / moved / cannot compare; new regions. Gone things go to Unplaced, never deleted | **experimental** (`verifier/rescan.py`, `POST /rescan`); failed its pre-set bar on false flags (report §6) |

Rules the page keeps (`web/fridge.html`):
- **Suggestions are judged before they ship.** On the held-out test photos (hand truth, `tools/eval_trace.py`) the corner
  suggestion was never within 3% of the true corners (0/3; worst corner 12-19% of the diagonal off) and the snap
  targets found 93% of real edges but added 3-15 false ones per photo, so both are switched off; the person places
  corners and lines by hand.
- **Nothing is filed without a person.** A suggestion (when enabled) is drawn dashed and labelled; an opening is accepted only after
  the person confirms the corners. A photo where the opening cannot be framed is traced unstraightened, labelled
  unverified.
- **OpenCV never invents.** It never adds a shelf, an item or a model, and never moves a line by itself; with edge snap
  targets switched on (they are off, above), a line the person drops near an edge would land on it.
- **A scan adds; it never deletes.** Removing a shelf moves its things to Unplaced; changing the fridge model with
  things in it asks first and moves them to Unplaced.
- **Answers stay bound to their photo and layout.** Corners carry the photo's hash; a scan answer is refused if its
  shelf was re-traced or removed meanwhile.
- **The fridge stays in the browser.** It is kept in this browser on this device (local storage) until the person
  taps Forget or clears the site's data; one tab writes at a time and another tab opens read-only. A browser without
  usable Web Locks keeps it in that tab only (session storage); there Forget clears that tab, and the page says a
  fridge saved earlier on the device is kept and how to clear it. A save is written, read back and compared before
  the page says "saved". The live handler keeps uploaded photos in memory for the request only; the one recorded
  example it serves was published with the owner's approval.

## How items are drawn

**Built (this web page):** a library model when the reading matches a row of the app's item catalogue (the app's
52 baked models, exported by `tools/export_items.py`; the app's longest-word rule; catalogue size, scaled down uniformly to
the renderer's limits: at most 90% of the level's height, half its width, and its depth). Otherwise a box or cylinder from a
basic family (bottle, can, jar, carton, tub, tray, pouch, bag, box) chosen by the scan's vessel word, sized by the
shelf photo's item box, with its own photo crop on its front when a matching retained crop for that item and shelf is available and
decodes (the shelf's latest kept photo lists it); otherwise plain. A model that fails to load leaves its placeholder shape. The item box guides horizontal position; depth comes from where its foot stands in the photo (approximate). Door bins, retired
levels and Unplaced are not drawn in 3D (`web/scene.js`).

**Planned:** the label flattened from the photo with a homography onto a flat face; per-product models are upgrades
for common items, not a requirement.

## Beyond the fridge

The phone app's data is a tree of containers (a space holds containers, containers hold levels, levels hold
items), so a pantry, a cupboard or a tabletop could use the same steps; this web prototype supports catalogue
appliances only. A container carries context such as its climate (room, fridge,
freezer). Rooms need a scale source (an object of known size, or phone depth), which this entry does not attempt.
