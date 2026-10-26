"""Transfer-learning image classifier (MobileNetV2, ImageNet weights) with a leak-safe split, class weighting, temperature
calibration, held-out metrics and ONNX export. One script for both crops.

  /tmp/conv/venv/bin/python -I tools/train_classifier.py --crop silkworm
  /tmp/conv/venv/bin/python -I tools/train_classifier.py --crop mulberry --images /tmp/mt/mulberry_small

Inputs : data/eval/<crop>_split.json (files{name:{class,group,split}}) and an image directory.
Outputs: data/models/<crop>.onnx + <crop>.json (calibrated softmax probabilities, labels, preprocessing),
         data/eval/results/<crop>_new.json (test metrics, calibration, coverage curve), /tmp/mt/<crop>_best.keras
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SIZE = 224
CFG = {
    "silkworm": {"images": ROOT / "data/images/SILK WORM DATASETS/images", "labels": ["healthy", "silkworm_disease_unspecified", "grasserie"],
                 "map": {"healthy": 0, "infected": 1, "grasserie": 2}},
    "mulberry": {"images": None, "labels": ["healthy", "leaf_rust", "leaf_spot"], "map": {"healthy": 0, "leaf_rust": 1, "leaf_spot": 2}},
}


def load_arrays(crop, images, split):
    man = json.loads((ROOT / f"data/eval/{crop}_split.json").read_text())["files"]
    cfg = CFG[crop]
    X, y, names, part = [], [], [], []
    for n, v in sorted(man.items()):
        p = Path(images) / (v["path"] if "path" in v else n)
        X.append(np.asarray(Image.open(p).convert("RGB").resize((SIZE, SIZE), Image.BILINEAR), dtype=np.uint8))
        y.append(cfg["map"][v["class"]])
        names.append(n)
        part.append(v["split"])
    return np.stack(X), np.array(y), np.array(names), np.array(part)


def ece(conf, correct, bins=10):
    e, n = 0.0, len(conf)
    edges = np.linspace(0, 1, bins + 1)
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            e += m.sum() / n * abs(conf[m].mean() - correct[m].mean())
    return float(e)


def metrics(y, p, labels):
    from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
    k = len(labels)
    pr, rc, f1, sup = precision_recall_fscore_support(y, p, labels=list(range(k)), zero_division=0)
    return {"accuracy": round(float((y == p).mean()), 4), "macro_f1": round(float(f1.mean()), 4),
            "per_class": {labels[i]: {"precision": round(float(pr[i]), 3), "recall": round(float(rc[i]), 3), "f1": round(float(f1[i]), 3), "support": int(sup[i])} for i in range(k)},
            "confusion[rows=true, cols=pred]": confusion_matrix(y, p, labels=list(range(k))).tolist()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crop", required=True, choices=list(CFG))
    ap.add_argument("--images")
    ap.add_argument("--epochs1", type=int, default=8)
    ap.add_argument("--epochs2", type=int, default=8)
    ap.add_argument("--seed", type=int, default=14)
    a = ap.parse_args()
    import tensorflow as tf
    tf.keras.utils.set_random_seed(a.seed)
    cfg = CFG[a.crop]
    images = a.images or cfg["images"]
    labels = cfg["labels"]
    X, y, names, part = load_arrays(a.crop, images, None)
    tr, va, te = part == "train", part == "val", part == "test"
    print("train/val/test", tr.sum(), va.sum(), te.sum(), "class counts train", np.bincount(y[tr], minlength=len(labels)))
    counts = np.bincount(y[tr], minlength=len(labels)).astype(float)
    cw = {i: float((counts.sum() / (len(labels) * counts[i])) ** 0.5) for i in range(len(labels))}  # sqrt-damped inverse frequency
    print("class weights", {labels[i]: round(w, 2) for i, w in cw.items()})

    aug = tf.keras.Sequential([tf.keras.layers.RandomFlip("horizontal_and_vertical"), tf.keras.layers.RandomRotation(0.12),
                               tf.keras.layers.RandomZoom(0.15), tf.keras.layers.RandomBrightness(0.2, value_range=(0, 255)),
                               tf.keras.layers.RandomContrast(0.2)])
    base = tf.keras.applications.MobileNetV2(input_shape=(SIZE, SIZE, 3), include_top=False, weights="imagenet", pooling="avg")
    base.trainable = False
    inp = tf.keras.Input((SIZE, SIZE, 3))
    x = aug(inp)
    x = tf.keras.layers.Rescaling(1 / 127.5, offset=-1)(x)   # MobileNetV2 expects [-1, 1]
    x = base(x, training=False)
    x = tf.keras.layers.Dropout(0.3)(x)
    out = tf.keras.layers.Dense(len(labels))(x)               # logits
    model = tf.keras.Model(inp, out)
    loss = tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True)
    ckpt = tf.keras.callbacks.ModelCheckpoint(f"/tmp/mt/{a.crop}_best.keras", monitor="val_loss", save_best_only=True)
    es = tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=3, restore_best_weights=True)
    ds = lambda m, shuf: tf.data.Dataset.from_tensor_slices((X[m].astype("float32"), y[m])).shuffle(4096, seed=a.seed).batch(32).prefetch(2) if shuf else \
        tf.data.Dataset.from_tensor_slices((X[m].astype("float32"), y[m])).batch(64)
    model.compile(tf.keras.optimizers.Adam(1e-3), loss, metrics=["accuracy"])
    h1 = model.fit(ds(tr, True), validation_data=ds(va, False), epochs=a.epochs1, class_weight=cw, callbacks=[ckpt, es], verbose=2)
    base.trainable = True
    for l in base.layers[:-40]:
        l.trainable = False
    model.compile(tf.keras.optimizers.Adam(1e-5), loss, metrics=["accuracy"])
    h2 = model.fit(ds(tr, True), validation_data=ds(va, False), epochs=a.epochs2, class_weight=cw, callbacks=[ckpt, tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=3, restore_best_weights=True)], verbose=2)

    logits = lambda m: model.predict(X[m].astype("float32"), batch_size=64, verbose=0)
    lv, lt = logits(va), logits(te)
    # temperature scaling on the VALIDATION set only
    def nll(T, lg, yy):
        z = lg / T; z = z - z.max(1, keepdims=True); p = np.exp(z) / np.exp(z).sum(1, keepdims=True)
        return -np.log(p[np.arange(len(yy)), yy] + 1e-9).mean()
    Ts = np.linspace(0.3, 5, 95)
    T = float(Ts[np.argmin([nll(t, lv, y[va]) for t in Ts])])
    sm = lambda lg, t: (lambda z: np.exp(z - z.max(1, keepdims=True)) / np.exp(z - z.max(1, keepdims=True)).sum(1, keepdims=True))(lg / t)
    pt_raw, pt = sm(lt, 1.0), sm(lt, T)
    pred = pt.argmax(1)
    yt = y[te]
    res = {"crop": a.crop, "labels": labels, "seed": a.seed, "n_train": int(tr.sum()), "n_val": int(va.sum()), "n_test": int(te.sum()),
           "class_weights": {labels[i]: round(w, 3) for i, w in cw.items()}, "temperature": round(T, 3),
           "history_val_acc": [round(float(v), 4) for v in h1.history["val_accuracy"] + h2.history["val_accuracy"]],
           "test": metrics(yt, pred, labels),
           "test_baseline_majority_class_accuracy": round(float(np.bincount(yt).max() / len(yt)), 4),
           "calibration": {"ece_before_T": round(ece(pt_raw.max(1), pt_raw.argmax(1) == yt), 4), "ece_after_T": round(ece(pt.max(1), pred == yt), 4),
                           "mean_confidence_after_T": round(float(pt.max(1).mean()), 3), "accuracy": round(float((pred == yt).mean()), 3)}}
    cov = []
    for tau in (0.5, 0.6, 0.7, 0.8, 0.9):
        m = pt.max(1) >= tau
        cov.append({"confidence>=": tau, "coverage": round(float(m.mean()), 3), "accuracy_on_covered": round(float((pred[m] == yt[m]).mean()), 4) if m.any() else None})
    res["selective_prediction"] = cov
    if a.crop == "silkworm":  # binary healthy vs any disease, for comparison with the legacy models
        sick_t, sick_p = (yt != 0).astype(int), (pred != 0).astype(int)
        tn = int(((sick_t == 0) & (sick_p == 0)).sum()); fp = int(((sick_t == 0) & (sick_p == 1)).sum())
        fn = int(((sick_t == 1) & (sick_p == 0)).sum()); tp = int(((sick_t == 1) & (sick_p == 1)).sum())
        res["test_binary_healthy_vs_sick"] = {"accuracy": round((tp + tn) / len(yt), 3), "precision_sick": round(tp / max(tp + fp, 1), 3), "recall_sick": round(tp / max(tp + fn, 1), 3),
                                              "specificity": round(tn / max(tn + fp, 1), 3), "confusion[[TN,FP],[FN,TP]]": [[tn, fp], [fn, tp]]}
    Path(ROOT / f"data/eval/results/{a.crop}_new.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))

    # ---- export: bake temperature + softmax into the graph; preprocessing lives in the config (x/255 -> (x-0.5)/0.5)
    inf_in = tf.keras.Input((SIZE, SIZE, 3))                     # input is already (x/255 - 0.5)/0.5, i.e. [-1, 1]
    z = base(inf_in, training=False)
    z = model.layers[-1](z)
    z = tf.keras.layers.Lambda(lambda t: tf.nn.softmax(t / T))(z)
    export = tf.keras.Model(inf_in, z)
    sample = X[te][:8].astype("float32")
    a1 = tf.nn.softmax(model.predict(sample, verbose=0) / T).numpy()
    a2 = export.predict(sample / 127.5 - 1.0, verbose=0)
    print("export parity max abs diff", float(np.abs(a1 - a2).max()))
    export.export("/tmp/mt/%s_saved" % a.crop)
    json.dump({"labels": labels, "input_size": SIZE, "mean": [0.5, 0.5, 0.5], "std": [0.5, 0.5, 0.5], "layout": "NHWC", "output": "probs",
               "notes": f"MobileNetV2 (ImageNet) fine-tuned by tools/train_classifier.py on a leak-safe split; softmax with temperature T={T:.3f} (fit on validation). "
                        f"Test accuracy {res['test']['accuracy']}, macro-F1 {res['test']['macro_f1']}. See docs/MODELS.md."},
              open(ROOT / f"data/models/{a.crop}.json.new", "w"), indent=1)


if __name__ == "__main__":
    main()
