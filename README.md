# Glass Pantry Vision Lab (OpenCV AI Competition 2026)

**Using OpenCV to upgrade our fridge app.** A lab for the Glass Pantry app, the fridge app we are building (an early build, in private testing). We test vision
here, and what passes goes into the app. The lab is not the app. Team 8yte, South Korea and Bangladesh.

Live: https://4bqaeiqta4gtyej43dpooy7cuq0gybcv.lambda-url.us-east-1.on.aws/ (the front page). Pages: `/` the front
page, `/fridge` the full flow, `/shelf` one shelf check with a recorded example, `/health`.

The lab runs the app's workflow in a browser: pick your fridge from its model sticker, trace each compartment over a
photo, then photograph each shelf. A vision-language model (Claude) lists what it sees. OpenCV 5 gates the photo,
checks the model's shelf lines against real edges, straightens traced openings, and picks small labels for a second
read from the uploaded image (the browser sends at most 3024 px, cut to the shelf band the person marks). The engine
recommends file, ask or retake; a person confirms before anything is kept. The fridge lives in this browser on this
device, never on the server, drawn in 2D and in 3D with the app's own item models.

When a shelf is photographed again, *What changed?* (experimental; it failed its pre-set bar, see the report) lines
the new photo up with the last one using OpenCV 5's learned matching (ALIKED + LightGlue) and marks only what may
have changed for a second look.

Measured 10/26 against the alternatives, on 12 pairings of 12 photos from one kitchen already used in development (a
retrospective comparison, protocol frozen first): one Claude call given both photos and the old list was credited with
every change and asked about 27 to 29 of 148 unchanged things (OpenCV's first pass: 66), for about a third of the cost
and time of our measured OpenCV-then-close-up stages; it is planned as step two. Among the model-free passes, the
learned matcher cleared the most unchanged things under shared rules: 82 of 148; without LightGlue, 29; SIFT 33;
ORB 20. See the report, §6.

![Architecture](docs/architecture/architecture.png)

## Run it

```
uv sync                                # Python 3.12; pinned: opencv-contrib-python-headless 5.0.0.93, numpy 2.3.4 (uv.lock)
uv run python tools/fetch_models.py    # the two ONNX models for What changed? (SHA-1 checked; models/ is git-ignored)
uv run pytest                          # generated images and a fake model API only: no photos, no paid calls
node --test tests/js/*.test.mjs        # the page's rules (Node 20+)
```

Real model runs need an Anthropic API key in `.env.local` (`ANTHROPIC_API_KEY=...`, git-ignored):

```
uv run python tools/run_dev.py OUT_DIR photo.jpg --zoom     # result JSON, crops, overlay picture
uv run python tools/serve_local.py --live                   # the web page on http://127.0.0.1:8765
```

## Deploy (AWS)

`.github/workflows/deploy.yml` tests, builds the Lambda container (x86_64) with SAM, and deploys the stack
`glass-pantry-opencv` in us-east-1. It runs on pushes to `main` that change code (documentation-only pushes do not
deploy) or on manual dispatch. It signs in with GitHub OIDC (no stored keys) to a role meant for this stack's own
resources, then smoke-tests the endpoint and runs four probes that the role is refused elsewhere. The owner creates
the execution role, the log group, the ECR repository, the upload bucket and the call-counter table once
(`template.yaml` names them), and an EventBridge Scheduler schedule that invokes the function every 5 minutes as a
keep-warm ping (the handler then loads the OpenCV 5 matching models and runs them once on a made-up image; no
admission, no model call).

Guards on the live endpoint, all server-side: an owner on/off switch in Parameter Store, a shared daily scan cap
(atomic DynamoDB counter, fails closed), upload size and pixel limits, a time budget for every model call, and logs
that hold codes and counts only.

## Code

| Path | Does |
|---|---|
| `verifier/frames.py` | one canonical 1568 px image for every check and the model; the original kept for close-ups |
| `verifier/gate.py` | photo gate: blur, shake, dark, blown-out (no model call on a bad photo) |
| `verifier/prompt.py` | the Glass Pantry app's scan prompt, frozen with a hash |
| `verifier/claude.py` | Messages API calls, answer parsing and validation, the label judge |
| `verifier/planes.py` | shelf check: shelf lines from the model tested against real horizontal edges (Canny + probabilistic Hough) |
| `verifier/zoom.py` | the zoom pass: OpenCV's close-up picker chooses, crops from the original, the model re-reads, the result is reconciled |
| `verifier/decide.py` | evidence → file / ask / retake |
| `verifier/scan.py` | one photo through the loop, with a timed trace of every step |
| `verifier/change.py`, `verifier/rescan.py` | What changed? (experimental): OpenCV 5 ALIKED + LightGlue alignment, per-item outcomes, new regions, `POST /rescan` |
| `verifier/identify.py` | matches the model's sticker reading to the catalogue (exact, family, kind) |
| `verifier/opening.py` | outline checks and straightening (`warpPerspective`); suggestions built but off |
| `service/handler.py` | the Lambda handler: pages, health, recorded example, scan, identify, straighten |
| `web/fridge.html`, `web/twin.js` | the fridge page: pick, trace, fill; the browser twin and its rules |
| `web/scene.js`, `web/twin3d.js` | the 3D view (pure geometry and library matching; three.js drawing, the change played on the shelf) |
| `web/compare.js` | What changed? drawn: the two photos, OpenCV's matched pairs, the outcome boxes |
| `web/items/`, `tools/export_items.py` | the app's 52 item models and match words, exported for the 3D view |
| `web/home.html` | the front page (`/`): the idea, the steps, the measured results |
| `web/index.html` | the single-shelf check (`/shelf`): upload, overlays, the list to confirm |
| `tools/` | local runs, annotation of results, the evaluation diagnostic |

Docs: [technical report](docs/report.md), [pipeline](docs/pipeline.md), [architecture](docs/architecture/),
[where the code came from](docs/provenance.md).
