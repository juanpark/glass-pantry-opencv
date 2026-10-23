# The pipeline: from a photo to a fridge you can open

The web page follows the same four steps as the Glass Pantry phone app, so that a phone photo and a browser give
the same result. OpenCV suggests, checks and straightens; a person confirms every layout and every list. Status
markers: **built** (code and tests on this branch), **planned** (decided, not yet built).

## The four steps

| Step | The person | Claude | OpenCV | Status |
|---|---|---|---|---|
| 1. Identify the fridge | picks it from the list (model or generic type) | none | none | **built** |
| 2. Load its layout | sees a flat front view: compartments, shelves, drawers, door bins | none | none (the app's catalogue as data, `web/layouts/layouts.json`) | **built** |
| 3. Confirm the layout over a photo | one photo per compartment; places four corners, then the shelf lines; confirms | none | validates the quad; `warpPerspective` to a front view of the opening plane. Corner suggestions and edge snap targets are built but **off**: they failed their pre-set bar on the test photos (below) | **built** (`verifier/opening.py`, `POST /straighten`) |
| 4. Fill a shelf, drawer or door bin | photographs it; edits and confirms the list | reads the items | photo gate; shelf check; zoom pass (small labels and counts re-read from the full photo) | **built** (`POST /scan`) |

Rules the page keeps (`web/fridge.html`):
- **Suggestions are judged before they ship.** On the held-out test photos (hand truth, `tools/eval_trace.py`) the corner
  suggestion was never within 3% of the true corners (0/3; worst corner 12-19% of the diagonal off) and the snap
  targets found 93% of real edges but added 3-15 false ones per photo, so both are switched off; the person places
  corners and lines by hand.
- **Nothing is filed without a person.** A suggestion (when enabled) is drawn dashed and labelled; an opening is accepted only after
  the person confirms the corners. A photo where the opening cannot be framed is traced unstraightened, labelled
  unverified.
- **OpenCV never invents.** It never adds a shelf, an item or a model, and never moves a line by itself; a line the
  person drops near an edge lands on it.
- **A scan adds; it never deletes.** Removing a shelf moves its things to Unplaced; changing the fridge model with
  things in it asks first and moves them to Unplaced.
- **Answers stay bound to their photo and layout.** Corners carry the photo's hash; a scan answer is refused if its
  shelf was re-traced or removed meanwhile.
- **The fridge stays in the browser.** Session storage only; a save is written, read back and compared before the
  page says "saved". The server keeps no photos.

## How items are drawn (planned)

One rule for the phone app and the web page:
1. **The item matches a library row** (the app's item catalogue: names and sizes per product family) → the library
   model.
2. **No match** → the nearest basic shape built on the fly: box, can, bottle, carton, tray, tub, pouch, bag, rounded
   produce, at the size the photo shows (snapped to a catalogue size when the product is recognised).
3. **The label** comes from the photo: OpenCV flattens a flat face with a homography, the same operation as step 3;
   curved labels are later.

Per-product models are upgrades for common items, not a requirement, so any product in any market can be drawn.

## Beyond the fridge

The data is a tree of containers (a space holds containers, containers hold levels, levels hold items), so a
pantry, a cupboard or a tabletop uses the same steps. A container carries context such as its climate (room, fridge,
freezer). Rooms need a scale source (an object of known size, or phone depth), which this entry does not attempt.
