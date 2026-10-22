# Where the code came from

Glass Pantry is a mobile app our team started on 2026-08-30, after this competition's build phase opened (08-26).
This entry reuses a few of its parts and builds the engine new.

| Part | Origin |
|---|---|
| Scan prompt (`verifier/prompts/contents.txt`) | Exported verbatim from the app (commit 6913119), frozen with a hash |
| Photo gate thresholds (`verifier/gate.py`) | From our 2026-10-01 experiments on 12 shelf photos; code rewritten here |
| Shelf-line check (`verifier/planes.py`) | Ported from our earlier evaluation script; the OpenCV 5 N×4 line shape kept |
| Canonical frames, Claude adapter, zoom pass, label judge, decisions | New for this entry |
| Lambda service, web page, deploy workflow, call cap, time budgets | New for this entry |
| Change detection experiment | New for this entry |
| Evaluation tools (annotation page, diagnostic) | New for this entry |

The app itself is not part of this repository. Its source stays private; the video shows it separately and says
which parts it does and does not contain.
