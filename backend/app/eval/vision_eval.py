"""Evaluate the plugged-in disease models on the supplied image sets.

    cd backend && python -m app.eval.vision_eval [--n 300]

Silkworm: Healthy / Infected / Grasserie folders -> healthy-vs-sick metrics and grasserie recall.
Mulberry: the supplied sets carry no disease labels (uploads are unlabelled; the cultivar set is 10 mulberry varieties),
so only the prediction/confidence distribution is reported - NOT accuracy.
The models may have been trained on (some of) these images; treat the numbers as an upper bound."""
import argparse
import collections
import json
import random
import time
from pathlib import Path

from app.config import DATA_DIR
from app.eval.run import RESULTS
from app.vision.classifier import MODEL_DIR, OnnxClassifier

SW = DATA_DIR / "images" / "SILK WORM DATASETS" / "images"
UPLOADS = DATA_DIR / "models" / "MULBERRY LEAF PREDICTION" / "static" / "uploads"
CULTIVAR = DATA_DIR / "images" / "Mulberry Leaf Dataset" / "Mulberry Leaf Dataset"
MIN_CONF = 0.5  # graph/profiles.MIN_CONFIDENCE


def load(crop: str) -> OnnxClassifier:
    return OnnxClassifier(crop, MODEL_DIR / f"{crop}.onnx", json.loads((MODEL_DIR / f"{crop}.json").read_text()))


def predict_all(clf, paths):
    rows = []
    for p in paths:
        try:
            pr = clf.predict(str(p))
            rows.append({"file": p.name, "label": pr.label, "conf": pr.confidence})
        except Exception:
            continue
    return rows


def silkworm(n: int, rng: random.Random) -> dict:
    files = sorted(SW.glob("*.jpg"))
    groups = {"healthy": [f for f in files if f.name.startswith(("Healthy", "Healthy_Worms")) ],
              "infected": [f for f in files if f.name.startswith("Infected")],
              "grasserie": [f for f in files if f.name.startswith("Grasserie")]}
    clf = load("silkworm")
    res, tp = {}, collections.Counter()
    for g, fs in groups.items():
        rows = predict_all(clf, rng.sample(fs, min(n, len(fs))))
        res[g] = {"n": len(rows), "labels": dict(collections.Counter(r["label"] for r in rows)),
                  "uncertain_frac": round(sum(r["conf"] < MIN_CONF for r in rows) / max(len(rows), 1), 3)}
        sick_pred = sum(r["label"] != "healthy" for r in rows)
        tp[g] = sick_pred
        res[g]["pred_sick_frac"] = round(sick_pred / max(len(rows), 1), 3)
    n_h, n_i, n_g = res["healthy"]["n"], res["infected"]["n"], res["grasserie"]["n"]
    tp_sick = tp["infected"] + tp["grasserie"]
    fp = tp["healthy"]
    sick_n = n_i + n_g
    tn = n_h - fp
    prec = tp_sick / max(tp_sick + fp, 1)
    rec = tp_sick / max(sick_n, 1)
    acc = (tp_sick + tn) / max(n_h + sick_n, 1)
    return {"groups": res, "healthy_vs_sick": {"accuracy": round(acc, 3), "precision": round(prec, 3), "recall": round(rec, 3),
            "specificity": round(tn / max(n_h, 1), 3)},
            "grasserie_recall": round(res["grasserie"]["labels"].get("grasserie", 0) / max(n_g, 1), 3),
            "grasserie_sick_recall": res["grasserie"]["pred_sick_frac"]}


def mulberry(n: int, rng: random.Random) -> dict:
    clf = load("mulberry")
    sets = {"uploads": [p for p in UPLOADS.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")],
            "cultivar_photos": list(CULTIVAR.glob("*/*/*.jpg"))}
    out = {"note": "no disease ground truth available: distribution only, not accuracy"}
    for k, fs in sets.items():
        rows = predict_all(clf, rng.sample(fs, min(n, len(fs))))
        out[k] = {"n": len(rows), "labels": dict(collections.Counter(r["label"] for r in rows)),
                  "uncertain_frac": round(sum(r["conf"] < MIN_CONF for r in rows) / max(len(rows), 1), 3)}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    n = ap.parse_args().n
    rng = random.Random(14)
    report = {"n_per_group": n, "caveat": "models may have been trained on these images", "silkworm": silkworm(n, rng),
              "mulberry": mulberry(n, rng)}
    RESULTS.mkdir(parents=True, exist_ok=True)
    f = RESULTS / f"vision_{time.strftime('%Y%m%d_%H%M%S')}.json"
    f.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print("saved", f)
