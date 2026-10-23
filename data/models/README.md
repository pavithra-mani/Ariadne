# Disease models (drop-in)

Place your pre-trained models here. Ariadne loads them automatically at startup:

    data/models/mulberry.onnx   + data/models/mulberry.json
    data/models/silkworm.onnx   + data/models/silkworm.json

`<crop>.json`:
    {"labels": ["healthy", "leaf_rust", ...],   // class order of the model output
     "input_size": 224,
     "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225],
     "layout": "NCHW"}                          // or "NHWC"

For other formats (PyTorch / Paddle / Keras) implement `DiseaseClassifier` in
`backend/app/vision/classifier.py` and register it in `get_classifier`.
Until a model is present a clearly-flagged stub classifier is used (reads the label from
the image file name, e.g. `grasserie_1.jpg`, otherwise a deterministic pseudo-label).
