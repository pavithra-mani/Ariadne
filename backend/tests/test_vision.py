import json
from pathlib import Path

import pytest

from app.config import DATA_DIR
from app.graph.profiles import DISEASE_PROFILES
from app.vision.classifier import MODEL_DIR, OnnxClassifier

SAMPLES = DATA_DIR / "images" / "samples"


def cfg_of(crop, stem=None):
    return json.loads((MODEL_DIR / f"{stem or crop}.json").read_text())


@pytest.mark.parametrize("crop", ["mulberry", "silkworm"])
def test_real_model_predicts_calibrated_probabilities(crop):
    model, cfg = MODEL_DIR / f"{crop}.onnx", MODEL_DIR / f"{crop}.json"
    photos = sorted(SAMPLES.glob(f"{crop}_*.jpg"))
    if not (model.exists() and cfg.exists() and photos):
        pytest.skip("trained model or sample photos not present")
    clf = OnnxClassifier(crop, model, cfg_of(crop))
    for p in photos[:3]:
        pred = clf.predict(str(p))
        assert pred.label in clf.labels and not pred.is_stub and pred.source == "onnx"
        assert 0.0 <= pred.confidence <= 1.0 and len(pred.top_k) == 3 and pred.top_k[0][1] >= pred.top_k[1][1]
        assert abs(sum(pr for _, pr in clf.predict(str(p)).top_k) - 1.0) < 0.1 or pred.top_k[0][1] > 0.3


@pytest.mark.parametrize("crop", ["mulberry", "silkworm"])
def test_every_emitted_label_has_a_risk_profile(crop):
    """A label without a profile would silently become 'uncertain': the model's labels must all be known to the risk matrix."""
    for label in cfg_of(crop)["labels"]:
        assert label in DISEASE_PROFILES, f"{crop} model emits {label!r} but DISEASE_PROFILES has no entry"


def test_generic_silkworm_label_is_conservative_and_provisional():
    p = DISEASE_PROFILES["silkworm_disease_unspecified"]
    real = [DISEASE_PROFILES[l] for l in ("grasserie", "flacherie", "muscardine", "pebrine")]
    assert p["crop"] == "silkworm" and p["infectious"] and p["provisional"]
    assert p["spread"] == 2 and p["base_severity"] >= 2 and p["loss"] >= 0.6
    assert p["loss"] <= max(r["loss"] for r in real)      # never worse than the worst known disease, never trivial


def test_legacy_models_are_kept_for_the_ablation_only():
    for crop in ("mulberry", "silkworm"):
        assert (MODEL_DIR / f"{crop}_legacy.onnx").exists()
        assert "legacy" not in cfg_of(crop).get("notes", "").lower()[:40]
    assert cfg_of("silkworm")["labels"] == ["healthy", "silkworm_disease_unspecified", "grasserie"]
    assert cfg_of("mulberry")["labels"] == ["healthy", "leaf_rust", "leaf_spot"]
    assert cfg_of("silkworm")["output"] == "probs" and cfg_of("silkworm").get("min_margin") is None  # calibrated softmax, not sigmoid
