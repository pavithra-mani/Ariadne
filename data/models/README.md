# Disease models

Active (loaded by `backend/app/vision/classifier.py`):

    data/models/silkworm.onnx + silkworm.json   labels: healthy, silkworm_disease_unspecified, grasserie
    data/models/mulberry.onnx + mulberry.json   labels: healthy, leaf_rust, leaf_spot

MobileNetV2 fine-tuned on a leak-safe split, temperature-calibrated softmax; see `docs/MODELS.md` for protocol, numbers and
**limitations (they fail on photos from other sources)**. `<crop>.json` keys: labels, input_size, mean/std (x/255 then (x-mean)/std),
layout (NHWC), output ("probs" | "logits"), resample (nearest|bilinear|bicubic - must match training), optional min_margin/uncertain_cap.

Legacy (the team's original Keras models, kept for ablation only): `*_legacy.{onnx,json}`, select with `ARIADNE_MODEL_VARIANT=legacy`.
Third-party/large material (not committed): `MULBERRY LEAF PREDICTION/`, `Silkworm-Disease-CNN-main/`.
Tests use a file-name stub (`ARIADNE_CLASSIFIER=stub`); in production a missing model falls back to Gemini vision only if DISEASE_FALLBACK=gemini.
