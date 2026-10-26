"""Disease classifiers behind one interface. The real models are supplied by the team;
a flagged stub keeps the system runnable until then."""
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import DATA_DIR

MODEL_DIR = DATA_DIR / "models"

# Labels for the stub / Gemini fallback only; the real models carry their own label order in <crop>.json.
DEFAULT_LABELS = {
    "mulberry": ["healthy", "leaf_rust", "leaf_spot", "stem_canker", "powdery_mildew", "root_knot", "leaf_blight", "mosaic_virus"],
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
        if "unspecified" in name and self.crop == "silkworm":  # test hook: image says "diseased, type unknown"
            return Prediction(self.crop, "silkworm_disease_unspecified", 0.9, [("silkworm_disease_unspecified", 0.9), ("healthy", 0.06), ("grasserie", 0.04)], "stub", True)
        hit = next((l for l in self.labels if l in name or l.replace("_", "") in name.replace("_", "")), None)
        if hit:
            label, conf = hit, 0.9
        else:
            digest = int(hashlib.md5(Path(image_path).read_bytes()).hexdigest(), 16)
            label, conf = self.labels[digest % len(self.labels)], 0.55 + (digest % 40) / 100
        rest = [(l, round((1 - conf) / (len(self.labels) - 1), 3)) for l in self.labels if l != label]
        return Prediction(self.crop, label, conf, [(label, conf)] + rest[:2], "stub", True)


class OnnxClassifier:
    """Runs an exported model. <crop>.json keys:
      labels, input_size, mean, std, layout (NCHW|NHWC)
      resample   nearest | bilinear | bicubic (must match training; default bicubic)
      output     "logits" (default: softmax is applied) | "probs" (model already outputs probabilities, e.g. sigmoid heads)
      min_margin for multi-label/sigmoid heads: when the top score beats the runner-up by less than this, the model is
                 not really choosing a class, so confidence is capped at `uncertain_cap` (below MIN_CONFIDENCE ->
                 the incident is routed to "ask an expert" instead of acting on a coin-flip)."""
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
        resample = {"nearest": Image.NEAREST, "bilinear": Image.BILINEAR, "bicubic": Image.BICUBIC}[self.cfg.get("resample", "bicubic")]
        img = Image.open(image_path).convert("RGB").resize((size, size), resample)   # same resampling as at training time
        x = np.asarray(img, dtype=np.float32) / 255.0
        x = (x - np.array(self.cfg.get("mean", [0.485, 0.456, 0.406]), dtype=np.float32)) / \
            np.array(self.cfg.get("std", [0.229, 0.224, 0.225]), dtype=np.float32)
        if self.cfg.get("layout", "NCHW") == "NCHW":
            x = x.transpose(2, 0, 1)
        x = x[None].astype(np.float32)
        out = self.session.run(None, {self.session.get_inputs()[0].name: x})[0][0].astype(np.float64)
        if self.cfg.get("output", "logits") == "probs":
            probs = out
        else:
            e = np.exp(out - out.max())
            probs = e / e.sum()
        order = probs.argsort()[::-1]
        top = [(normalise_label(self.labels[i]), float(probs[i])) for i in order[:3]]
        conf = top[0][1]
        margin = self.cfg.get("min_margin")
        if margin and len(top) > 1 and top[0][1] - top[1][1] < margin:
            conf = min(conf, self.cfg.get("uncertain_cap", 0.45))
        return Prediction(self.crop, top[0][0], conf, top, "onnx", False)


class GeminiVisionClassifier:
    """Opt-in stand-in (DISEASE_FALLBACK=gemini) until a trained model is dropped in: Gemini looks at the photo
    and must answer with one of the known labels. Clearly flagged as a model fallback in the finding."""
    def __init__(self, crop: str):
        self.crop, self.labels = crop, DEFAULT_LABELS[crop]

    def predict(self, image_path: str) -> Prediction:
        from app.llm.provider import LLMUnavailable, get_llm
        from app.llm.schemas import DiagnosisOut
        llm = get_llm()
        if llm is None:
            return StubClassifier(self.crop).predict(image_path)
        path = Path(image_path)
        mime = "image/png" if path.suffix.lower() == ".png" else "image/webp" if path.suffix.lower() == ".webp" else "image/jpeg"
        system = (f"You identify {self.crop} health problems from a photo. Choose exactly one label from: {', '.join(self.labels)}. "
                  "Use 'healthy' only if the photo shows a healthy specimen. If the photo is not a clear picture of the "
                  "specimen, give a low confidence. Never exceed 0.9 confidence.")
        try:
            out = llm.generate_json(DiagnosisOut, system, "Identify the problem in this photo.", "vision.classify", images=[(path.read_bytes(), mime)])
        except LLMUnavailable:
            return StubClassifier(self.crop).predict(image_path)
        label = out.label if out.label in self.labels else self.labels[0]
        conf = min(max(out.confidence, 0.0), 0.9) if out.label in self.labels else 0.2
        return Prediction(self.crop, label, conf, [(label, conf)], "gemini_vision", False)


@lru_cache
def get_classifier(crop: str) -> DiseaseClassifier:
    """Order: ARIADNE_CLASSIFIER=stub (tests) -> trained ONNX model -> Gemini vision (DISEASE_FALLBACK=gemini) -> stub."""
    if os.environ.get("ARIADNE_CLASSIFIER") == "stub":
        return StubClassifier(crop)
    variant = os.environ.get("ARIADNE_MODEL_VARIANT", "")  # "legacy": the team's original Keras models, for the ablation only
    stem = f"{crop}_{variant}" if variant else crop
    model, cfg_path = MODEL_DIR / f"{stem}.onnx", MODEL_DIR / f"{stem}.json"
    if model.exists() and cfg_path.exists():
        try:
            return OnnxClassifier(crop, model, json.loads(cfg_path.read_text()))
        except Exception as exc:  # bad model must not take the service down
            print(f"[vision] could not load {model.name}: {exc}; using fallback")
    from app.config import settings
    if settings.disease_fallback == "gemini":
        return GeminiVisionClassifier(crop)
    print(f"[vision] no trained {crop} model in {MODEL_DIR}: using the file-name STUB (demo/tests only)")
    return StubClassifier(crop)
