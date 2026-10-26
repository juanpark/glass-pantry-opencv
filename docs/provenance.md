# Where the code came from

Glass Pantry is a mobile app our team started on 2026-08-30, after this competition's build phase opened (08-26).
The lab reuses a few of the app's parts and builds the engine new.

| Part | Origin |
|---|---|
| Scan prompt (`verifier/prompts/contents.txt`) | Exported verbatim from the app (commit 6913119), frozen with a hash |
| Photo gate thresholds (`verifier/gate.py`) | From our 2026-10-01 experiments on 12 shelf photos; code rewritten here |
| Shelf check (`verifier/planes.py`) | Ported from our earlier evaluation script; the OpenCV 5 N×4 line shape kept |
| Fridge layouts (`web/layouts/layouts.json`) | Exported from the app's catalogue by its own parser (commit 6913119, `tools/export_layouts_test.dart`), checked against the app's filing destinations, frozen with a hash |
| Canonical frames, Claude adapter, zoom pass, label judge, decisions | New for the lab |
| Lambda service, web page, deploy workflow, call cap, time budgets | New for the lab |
| Straightening (`verifier/opening.py`) | New for the lab |
| What changed? (`verifier/change.py`, `verifier/rescan.py`) | New for the lab; the ALIKED and LightGlue weights are third-party (report §4) |
| Evaluation tools (annotation page, diagnostic) | New for the lab |
| Item models for the 3D view (`web/items/*.glb`, `items.json`) | Exported from the app (commit 6913119) by `tools/export_items.py`: 52 models the app's own Blender script generates from colour blocks (no brands, logos or bought assets), with the app's match words and sizes |
| three.js 0.160.0 (3D drawing, OrbitControls, GLTFLoader) | Third-party, MIT licence, loaded from the jsDelivr CDN at a pinned version |

The app itself is not part of this repository. Its source stays private; the video shows it separately and says
which parts it does and does not contain.
