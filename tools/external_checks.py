"""Out-of-source sanity checks of the INSTALLED models (different photographers/sites than the training data).
  silkworm: D5 (third-party 492 images, diseased/undiseased) -> healthy-vs-sick
  mulberry: D1 healthy cultivars (Thailand, 400 test images) -> share called healthy; D3 unlabelled uploads -> label histogram
  PYTHONPATH=backend ARIADNE_DATA_DIR=data backend/.venv/bin/python -I tools/external_checks.py
"""
import json, sys, random
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.vision.classifier import MODEL_DIR, OnnxClassifier  # noqa: E402
load = lambda c: OnnxClassifier(c, MODEL_DIR / f"{c}.onnx", json.loads((MODEL_DIR / f"{c}.json").read_text()))
res = {}
sw = load("silkworm")
tp = ROOT / "data/models/Silkworm-Disease-CNN-main/Training/Images"
tn = fp = fn = tpos = 0
for d, sick in (("diseased", 1), ("undiseased", 0)):
    for p in sorted((tp / d).iterdir()):
        if p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        pred_sick = sw.predict(str(p)).label != "healthy"
        if sick: tpos += pred_sick; fn += not pred_sick
        else: fp += pred_sick; tn += not pred_sick
res["silkworm_D5_healthy_vs_sick"] = {"n": tn + fp + fn + tpos, "accuracy": round((tn + tpos) / (tn + fp + fn + tpos), 3), "recall_sick": round(tpos / max(tpos + fn, 1), 3), "specificity": round(tn / max(tn + fp, 1), 3), "confusion[[TN,FP],[FN,TP]]": [[tn, fp], [fn, tpos]]}
mb = load("mulberry")
d1 = sorted((ROOT / "data/images/Mulberry Leaf Dataset/Mulberry Leaf Dataset/Test set").rglob("*.jpg"))
random.Random(14).shuffle(d1); d1 = d1[:400]
c = Counter(); conf = []
for p in d1:
    pr = mb.predict(str(p)); c[pr.label] += 1; conf.append(pr.confidence)
res["mulberry_D1_healthy_cultivars"] = {"n": len(d1), "labels": dict(c), "called_healthy": round(c["healthy"] / len(d1), 3), "mean_confidence": round(sum(conf) / len(conf), 3)}
d3 = sorted((ROOT / "data/models/MULBERRY LEAF PREDICTION/static/uploads").glob("*.[jJ][pP]*"))
random.Random(14).shuffle(d3); d3 = d3[:300]
c = Counter(); lowc = 0
for p in d3:
    pr = mb.predict(str(p)); c[pr.label] += 1; lowc += pr.confidence < 0.5
res["mulberry_D3_uploads_unlabelled"] = {"n": len(d3), "labels": dict(c), "share_below_0.5_confidence": round(lowc / len(d3), 3)}
(ROOT / "data/eval/results/external_checks.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
