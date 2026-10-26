"""Run the INSTALLED ONNX models through the app's OnnxClassifier on the held-out test split: the numbers must match training.
  PYTHONPATH=backend ARIADNE_DATA_DIR=data backend/.venv/bin/python -I tools/verify_onnx.py   (run from the repo root)
"""
import json, sys
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.vision.classifier import MODEL_DIR, OnnxClassifier  # noqa: E402

SRC = {"silkworm": ROOT / "data/images/SILK WORM DATASETS/images", "mulberry": Path("/tmp/mt/mulberry_small")}
MAP = {"silkworm": {"healthy": "healthy", "infected": "silkworm_disease_unspecified", "grasserie": "grasserie"}, "mulberry": {"healthy": "healthy", "leaf_rust": "leaf_rust", "leaf_spot": "leaf_spot"}}
for crop in ("silkworm", "mulberry"):
    clf = OnnxClassifier(crop, MODEL_DIR / f"{crop}.onnx", json.loads((MODEL_DIR / f"{crop}.json").read_text()))
    man = json.loads((ROOT / f"data/eval/{crop}_split.json").read_text())["files"]
    ok = n = 0
    for name, v in sorted(man.items()):
        if v["split"] != "test":
            continue
        pr = clf.predict(str(SRC[crop] / (v.get("path") or name)))
        ok += pr.label == MAP[crop][v["class"]]; n += 1
    print(crop, "test accuracy via OnnxClassifier:", round(ok / n, 4), "n =", n)
