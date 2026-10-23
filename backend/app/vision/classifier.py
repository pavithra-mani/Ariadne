"""Disease classifiers behind one interface. The real models are supplied by the team;
a flagged stub keeps the system runnable until then."""
import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import DATA_DIR

MODEL_DIR = DATA_DIR / "models"

DEFAULT_LABELS = {
    "mulberry": ["healthy", "leaf_rust", "leaf_spot", "powdery_mildew", "leaf_blight", "mosaic_virus"],
    "silkworm": ["healthy", "grasserie", "flacherie", "muscardine", "pebrine"],
}


@dataclass
class Prediction:
    crop: str
    label: str
    confidence: float
    top_k: list[tuple[str, float]] = field(default_factory=list)
    source: str = "stub"  # stub | onnx
    is_stub: bool = True

    def dict(self) -> dict:
        return {"crop": self.crop, "label": self.label, "confidence": round(self.confidence, 3),
                "top_k": [(l, round(p, 3)) for l, p in self.top_k], "source": self.source,
                "is_stub": self.is_stub}


class DiseaseClassifier(Protocol):
    crop: str

    def predict(self, image_path: str) -> Prediction: ...


def normalise_label(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


class StubClassifier:
    def __init__(self, crop: str):
        self.crop = crop
        self.labels = DEFAULT_LABELS[crop]

    def predict(self, image_path: str) -> Prediction:
        name = Path(image_path).name.lower()
        if any(w in name for w in ("blurry", "unclear", "unknown")):  # demo hook: a photo the model is unsure about
            digest = int(hashlib.md5(Path(image_path).read_bytes()).hexdigest(), 16)
            return Prediction(self.crop, self.labels[1 + digest % (len(self.labels) - 1)], 0.31,
                              [(self.labels[1], 0.31), (self.labels[2], 0.28)], "stub", True)
        hit = next((l for l in self.labels if l in name or l.replace("_", "") in name.replace("_", "")), None)
        if hit:
            label, conf = hit, 0.9
        else:
            digest = int(hashlib.md5(Path(image_path).read_bytes()).hexdigest(), 16)
            label, conf = self.labels[digest % len(self.labels)], 0.55 + (digest % 40) / 100
        rest = [(l, round((1 - conf) / (len(self.labels) - 1), 3)) for l in self.labels if l != label]
        return Prediction(self.crop, label, conf, [(label, conf)] + rest[:2], "stub", True)


class OnnxClassifier:
    def __init__(self, crop: str, model: Path, cfg: dict):
        import onnxruntime as ort
        self.crop = crop
        self.session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
        self.cfg = cfg
        self.labels = cfg["labels"]

    def predict(self, image_path: str) -> Prediction:
        import numpy as np
        from PIL import Image
        size = self.cfg.get("input_size", 224)
        img = Image.open(image_path).convert("RGB").resize((size, size))
        x = np.asarray(img, dtype=np.float32) / 255.0
        x = (x - np.array(self.cfg.get("mean", [0.485, 0.456, 0.406]), dtype=np.float32)) / \
            np.array(self.cfg.get("std", [0.229, 0.224, 0.225]), dtype=np.float32)
        if self.cfg.get("layout", "NCHW") == "NCHW":
            x = x.transpose(2, 0, 1)
        x = x[None].astype(np.float32)
        logits = self.session.run(None, {self.session.get_inputs()[0].name: x})[0][0]
        e = np.exp(logits - logits.max())
        probs = e / e.sum()
        order = probs.argsort()[::-1]
        top = [(normalise_label(self.labels[i]), float(probs[i])) for i in order[:3]]
        return Prediction(self.crop, top[0][0], top[0][1], top, "onnx", False)


@lru_cache
def get_classifier(crop: str) -> DiseaseClassifier:
    model, cfg_path = MODEL_DIR / f"{crop}.onnx", MODEL_DIR / f"{crop}.json"
    if model.exists() and cfg_path.exists():
        try:
            return OnnxClassifier(crop, model, json.loads(cfg_path.read_text()))
        except Exception as exc:  # bad model must not take the service down
            print(f"[vision] could not load {model.name}: {exc}; using stub")
    return StubClassifier(crop)
