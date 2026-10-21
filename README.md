# Glass Pantry verifier (OpenCV AI Competition 2026)

A vision-language model proposes what stands on a fridge shelf. OpenCV 5 checks the photo and the proposal, and
that check decides the next action: **file** it into the fridge's 3D twin, **ask** the person, or ask for a
**retake**.

```
uv sync            # Python 3.12, pinned: opencv-contrib-python-headless 5.0.0.93, numpy 2.3.4
uv run pytest      # generated test images only; no personal photos in this repo
```

| Module | Does |
|---|---|
| `verifier/gate.py` | photo gate: blur, shake, dark, blown-out |
| `verifier/planes.py` | shelf lines the model proposed vs real horizontal edges (Canny + Hough) |
| `verifier/decide.py` | evidence -> retake / ask / file |
| `verifier/scan.py` | one photo through the loop, with a trace of every step |
