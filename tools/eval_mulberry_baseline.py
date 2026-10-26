"""Evaluate the EXISTING mulberry model (model2.h5 -> data/models/mulberry_legacy.onnx; 128px, /255, 6 sigmoid outputs:
leaf_rust, leaf_spot, stem_canker, powdery_mildew, root_knot, healthy[hypothesis]) on the labelled Bangladesh photos (test split),
mapped to the 3 classes the data supports (stem_canker/powdery_mildew/root_knot predictions count as wrong), and on the 10-cultivar
healthy-leaf set (D1) to measure its false-alarm rate.
  /tmp/conv/venv/bin/python -I tools/eval_mulberry_baseline.py /tmp/mt/mulberry_small
"""
import json
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

ROOT = Path(__file__).resolve().parents[1]
LAB = ["leaf_rust", "leaf_spot", "stem_canker", "powdery_mildew", "root_knot", "healthy"]
D1 = ROOT / "data/images/Mulberry Leaf Dataset/Mulberry Leaf Dataset/Test set"


def run(sess, paths):
    P = []
    for i in range(0, len(paths), 64):
        x = np.stack([np.asarray(Image.open(p).convert("RGB").resize((128, 128), Image.NEAREST), dtype=np.float32) / 255 for p in paths[i:i + 64]])
        P.append(sess.run(None, {sess.get_inputs()[0].name: x})[0])
    return np.concatenate(P)


def main(src: Path):
    sess = ort.InferenceSession(str(ROOT / "data/models/mulberry_legacy.onnx"), providers=["CPUExecutionProvider"])
    man = json.loads((ROOT / "data/eval/mulberry_split.json").read_text())["files"]
    res = {}
    for part in ("test", "train"):
        items = sorted((n, v) for n, v in man.items() if v["split"] == part)
        P = run(sess, [src / n for n, _ in items])
        names3 = ["healthy", "leaf_rust", "leaf_spot", "other"]
        top = P.argmax(1)
        pred = np.array([{"healthy": 0, "leaf_rust": 1, "leaf_spot": 2}.get(LAB[t], 3) for t in top])
        y = np.array([["healthy", "leaf_rust", "leaf_spot"].index(v["class"]) for _, v in items])
        pr, rc, f1, sup = precision_recall_fscore_support(y, pred, labels=[0, 1, 2], zero_division=0)
        res[part] = {"n": len(y), "accuracy": round(float((y == pred).mean()), 4), "macro_f1_3class": round(float(f1.mean()), 4),
                     "per_class": {c: {"precision": round(float(pr[i]), 3), "recall": round(float(rc[i]), 3), "support": int(sup[i])} for i, c in enumerate(names3[:3])},
                     "confusion[rows=true healthy,rust,spot; cols=pred healthy,rust,spot,other]": confusion_matrix(y, pred, labels=[0, 1, 2, 3])[:3].tolist(),
                     "majority_class_accuracy": round(float(np.bincount(y).max() / len(y)), 4),
                     "predicted_label_histogram": {LAB[i]: int((top == i).sum()) for i in range(6)}}
    d1 = sorted(D1.rglob("*.jpg"))[:400]
    top = run(sess, d1).argmax(1)
    res["D1_healthy_cultivars"] = {"n": len(d1), "called_healthy": round(float((top == 5).mean()), 3), "predicted_label_histogram": {LAB[i]: int((top == i).sum()) for i in range(6)},
                                   "note": "all D1 leaves are healthy cultivars; any non-healthy call is a false alarm (domain differs: Thailand cultivars, 224px crops)"}
    (ROOT / "data/eval/results/mulberry_baseline.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
