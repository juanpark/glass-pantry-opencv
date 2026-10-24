"""Download the ONNX models the engine runs in OpenCV 5's DNN engine, and check each file's SHA-1.

    python tools/fetch_models.py [DIR]      (default: models/ next to this repo's verifier/)

The URLs and hashes are the ones OpenCV's own test data uses (opencv_extra testdata/dnn/download_models.py, 5.x).
Weights: ALIKED (BSD-3-Clause, github.com/Shiaoming/ALIKED) and LightGlue (Apache-2.0, github.com/cvg/LightGlue);
the ONNX exports are the copies OpenCV's tests fetch. A file whose hash does not match is deleted, never used.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/YangGuanyuhan/lightglue_opencv_project/main/model/"
MODELS = {
    "aliked-n16rot-top1k-640.onnx": "41faa7bf5d7eb68a2851471ba03aa20c9db30e4c",
    "aliked_lightglue.onnx": "02723aa521990e57fe33d90b67977590c460e351",
}


def sha1(p: Path) -> str:
    return hashlib.sha1(p.read_bytes()).hexdigest()


def fetch(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, want in MODELS.items():
        p = out / name
        if p.exists() and sha1(p) == want:
            continue
        urllib.request.urlretrieve(BASE + name, p)
        if sha1(p) != want:
            p.unlink()
            raise SystemExit(f"{name}: hash mismatch, deleted")
        print(f"{name}: ok")


if __name__ == "__main__":
    fetch(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "models")
