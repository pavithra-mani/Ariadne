"""Evaluate the two EXISTING silkworm models on the leak-safe split (tools/silkworm_split.py).

 legacy      data/models/silkworm.onnx (from modellll.h5, 128px, /255, 5 sigmoid outputs; the team's Flask model)
 thirdparty  data/models/Silkworm-Disease-CNN-main/Model/1 (TanmayKJha/Silkworm-Disease-CNN; 250px, rescale inside, 3 softmax
             outputs, trained on 2 dirs: diseased / undiseased)
Binary view (sick = infected + grasserie) for both; 3-class view for legacy (non-grasserie disease labels -> infected).
  /tmp/conv/venv/bin/python -I tools/eval_silkworm_baselines.py
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/images/SILK WORM DATASETS/images"
SPLIT = json.loads((ROOT / "data/eval/silkworm_split.json").read_text())["files"]
LEG = ["flacherie", "grasserie", "muscardine", "pebrine", "healthy"]


def load(name, size, resample):
    return np.asarray(Image.open(SRC / name).convert("RGB").resize((size, size), resample), dtype=np.float32)


def binm(y, p):  # 1 = sick
    tn, fp, fn, tp = confusion_matrix(y, p, labels=[0, 1]).ravel()
    pr, rc, f1, _ = precision_recall_fscore_support(y, p, average="binary", zero_division=0)
    return {"n": int(len(y)), "accuracy": round((tp + tn) / len(y), 3), "precision_sick": round(float(pr), 3), "recall_sick": round(float(rc), 3),
            "f1_sick": round(float(f1), 3), "specificity": round(float(tn / max(tn + fp, 1)), 3), "confusion[[TN,FP],[FN,TP]]": [[int(tn), int(fp)], [int(fn), int(tp)]]}


def main():
    import onnxruntime as ort
    import tensorflow as tf
    res = {}
    names = sorted(SPLIT)
    y_sick = np.array([0 if SPLIT[n]["class"] == "healthy" else 1 for n in names])
    y3 = np.array([["healthy", "infected", "grasserie"].index(SPLIT[n]["class"]) for n in names])
    part = np.array([SPLIT[n]["split"] for n in names])

    sess = ort.InferenceSession(str(ROOT / "data/models/silkworm.onnx"), providers=["CPUExecutionProvider"])
    for tag, rs in (("nearest", Image.NEAREST), ("bicubic", Image.BICUBIC)):
        P = []
        for i in range(0, len(names), 64):
            x = np.stack([load(n, 128, rs) / 255.0 for n in names[i:i + 64]])
            P.append(sess.run(None, {sess.get_inputs()[0].name: x.astype(np.float32)})[0])
        P = np.concatenate(P)
        top = P.argmax(1)
        sick = np.array([LEG[t] != "healthy" for t in top]).astype(int)
        three = np.array([0 if LEG[t] == "healthy" else 2 if LEG[t] == "grasserie" else 1 for t in top])
        for s in ("test", "train"):
            m = part == s
            res[f"legacy_{tag}_{s}_binary"] = binm(y_sick[m], sick[m])
        m = part == "test"
        res[f"legacy_{tag}_test_3class_confusion[rows=true healthy,infected,grasserie; cols=pred]"] = confusion_matrix(y3[m], three[m], labels=[0, 1, 2]).tolist()
        res[f"legacy_{tag}_test_grasserie_recall_exact"] = round(float(((three == 2) & (y3 == 2) & m).sum() / max(((y3 == 2) & m).sum(), 1)), 3)
        res[f"legacy_{tag}_test_mean_top_prob"] = round(float(P[m].max(1).mean()), 3)
        np.save("/tmp/mt/legacy_probs_%s.npy" % tag, P)

    m3 = tf.keras.layers.TFSMLayer(str(ROOT / "data/models/Silkworm-Disease-CNN-main/Model/1"), call_endpoint="serving_default")
    P = []
    for i in range(0, len(names), 64):
        x = np.stack([load(n, 250, Image.BILINEAR) for n in names[i:i + 64]])  # raw 0-255: rescaling is inside the model
        o = m3(tf.constant(x))
        o = list(o.values())[0].numpy() if isinstance(o, dict) else o.numpy()
        P.append(o)
    P = np.concatenate(P)
    res["thirdparty_output_row_sums_first5"] = [round(float(v), 3) for v in P[:5].sum(1)]
    sick = (P[:, :2].argmax(1) == 0).astype(int)  # class order = alphabetical dirs: 0 diseased, 1 undiseased
    for s in ("test", "train"):
        m = part == s
        res[f"thirdparty_{s}_binary"] = binm(y_sick[m], sick[m])
    sick_flip = 1 - sick
    res["thirdparty_test_binary_if_labels_flipped"] = binm(y_sick[part == "test"], sick_flip[part == "test"])
    res["thirdparty_mean_p_diseased_on_test_healthy"] = round(float(P[(part == "test") & (y_sick == 0), 0].mean()), 3)
    res["thirdparty_mean_p_diseased_on_test_sick"] = round(float(P[(part == "test") & (y_sick == 1), 0].mean()), 3)
    res["base_rate_sick_test"] = round(float(y_sick[part == "test"].mean()), 3)
    out = ROOT / "data/eval/results/silkworm_baselines.json"
    out.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
