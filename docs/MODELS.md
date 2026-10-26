# Disease models: evidence, decisions, limits

Measured 2026-10-26. Everything below is reproducible with the scripts in `tools/`; raw numbers are in `data/eval/results/`.
Sources and licences: `sources/SOURCES.md` (IDs D1a, D4, D5, P1, P2, M1-M5).

## Summary (what drives decisions now)
| Crop | Model in use | Held-out accuracy | Majority-class baseline | Old model |
|---|---|---|---|---|
| Silkworm | MobileNetV2 fine-tuned (`silkworm.onnx`), labels `healthy`, `silkworm_disease_unspecified`, `grasserie` | **0.952** (macro-F1 0.851; healthy-vs-sick 0.987) | 0.513 | legacy `modellll.h5`: 0.496 healthy-vs-sick (chance) |
| Mulberry | MobileNetV2 fine-tuned (`mulberry.onnx`), labels `healthy`, `leaf_rust`, `leaf_spot` | **0.970** (macro-F1 0.959) | 0.432 | legacy `model2.h5`: 0.249 (worse than the baseline) |

**Read the limitations before quoting these numbers.** They are in-distribution results; on photos from other sources both models failed (see "Out-of-source checks").

## Protocol (both crops)
1. **Leak-safe split.** The silkworm set is a Roboflow export: each source photo appears 2-3 times as augmented copies (`Grasserie-12-_jpg.rf.<hash>.jpg`). Files are grouped by source stem, then near-duplicates (64-bit dHash, Hamming <= 6; <= 8 for mulberry) are merged. 5,830 silkworm files -> 2,453 groups (462 near-duplicate merges; 8 cross-class near-duplicate pairs = label noise in the data). 1,091 mulberry photos -> 1,065 groups. Groups are split 70/15/15 stratified by class (seed 14): `tools/silkworm_split.py`, `tools/mulberry_split.py` -> `data/eval/*_split.json`.
2. **Training** (`tools/train_classifier.py`): MobileNetV2 (ImageNet weights, Apache-2.0), 224 px, augmentation (flip, rotation, zoom, brightness, contrast), dropout 0.3; 8 epochs head only (lr 1e-3) then 8 epochs fine-tuning the last 40 layers (lr 1e-5), early stopping on validation loss. Class imbalance: sqrt-damped inverse-frequency class weights (silkworm grasserie x2.89).
3. **Calibration:** temperature scaling fitted on the validation split only (silkworm T=1.05, mulberry T=0.85), baked into the ONNX graph (softmax probabilities). The app treats confidence < 0.5 as "uncertain -> ask an expert" (`MIN_CONFIDENCE`).
4. **Export & parity:** SavedModel -> ONNX (tf2onnx, opset 13); the installed ONNX run through the app's `OnnxClassifier` reproduces the Keras test accuracy exactly (0.9522 / 0.9704): `tools/verify_onnx.py`.

## Silkworm
Data: D2, 5,830 images (healthy 2,832 incl. 14 "Healthy_Worms", infected 2,760, grasserie 238). Test: 900 images (462 healthy, 398 infected, 40 grasserie).

| Model (900 test images, healthy vs sick) | Accuracy | Specificity | Recall (sick) |
|---|---|---|---|
| Legacy `modellll.h5` (team's Flask model) | 0.496 | 0.102 | 0.911 |
| Third-party `Silkworm-Disease-CNN` (M3; 250 px, 2 classes; 0 of its 492 training images occur in D2) | 0.397 (0.603 if its outputs are flipped) | 0.214 | 0.589 |
| **New MobileNetV2** | **0.987** | **0.985** | **0.989** |

The legacy model calls ~90% of healthy worms sick and recognises 15-20% of grasserie; on its own *train* part it is equally poor, so this is not a leakage artefact. Resize method (nearest vs bicubic) made no difference.

New model, 3 classes (rows = true, columns = predicted):

| | healthy | disease unspecified | grasserie | precision | recall |
|---|---|---|---|---|---|
| healthy (462) | 455 | 6 | 1 | 0.989 | 0.985 |
| disease unspecified (398) | 5 | 376 | 17 | 0.949 | 0.945 |
| grasserie (40) | 0 | 14 | 26 | 0.591 | 0.650 |

Calibration: ECE 0.012; accuracy on predictions with confidence >= 0.9 is 0.991 (85% coverage), >= 0.7: 0.979 (94%).

**Why the label `silkworm_disease_unspecified`:** the data only separates healthy / infected / grasserie. "Infected" is not one disease, and nothing in the data says which. Mapping it to flacherie or pebrine would be invented. The app treats it as a *provisional* diagnosis: conservative risk profile (severity 2, spread 2, loss 0.6, infectious), a question asking for discriminating symptoms (milky fluid / swollen shiny skin / climbing the edge -> grasserie; black pepper-like spots / uneven growth -> pebrine; chalky mummified larvae -> muscardine; sluggish, vomiting, diarrhoea, not feeding -> flacherie), generic hygiene steps retrieved from the knowledge base, and mandatory expert confirmation (`escalate`). If the farmer's symptom text names a specific disease with confidence >= 0.5 it overrides the generic label (`finding.source = "image+symptoms"`).

## Mulberry
Ground truth: D4 (Kaggle `nahiduzzaman13/mulberry-leaf-dataset`, CC0), 1,091 expert-labelled photos from Rajshahi, Bangladesh: healthy 440, leaf rust 489, leaf spot 162 (originals of the Frontiers 2023 PDS-CNN paper, P1; also used by P2). Only downscaled copies are stored (`tools/fetch_mulberry_kaggle.py`; the archive is 11.4 GB). Test: 169 photos (71 / 73 / 25).

| Model | Accuracy (3-class) | Leaf-rust recall | Notes |
|---|---|---|---|
| Legacy `model2.h5` | 0.249 | 0.068 | worse than always answering "leaf rust" (0.432); of 169 test photos it predicts leaf rust for only 9 (73 are rust), leaf spot for 74 (25 are spot), and stem canker / powdery mildew / root knot for 69 (classes absent from the data); on 400 healthy Thai cultivar leaves it says healthy only 27% of the time |
| **New MobileNetV2** | **0.970** | 0.973 | healthy 71/71, rust 71/73, spot 22/25; ECE 0.033; at confidence >= 0.9: 1.000 accuracy on 89% of images |

Confusion (new, rows true healthy/rust/spot): [[71,0,0],[1,71,1],[1,2,22]]. The old model's labels `stem_canker`, `powdery_mildew`, `root_knot` have **no free labelled data** (searched Hugging Face, Zenodo, Mendeley, figshare, GitHub, Kaggle): the new model cannot emit them; the profiles and KB notes remain for text reports.

## Limitations (important for a paper)
* **Same-source test sets.** Silkworm: train and test images share one Roboflow export, so near-identical scenes, backgrounds, lighting and camera likely appear on both sides despite grouping; 0.95 is an optimistic estimate of field accuracy. Mulberry: one site/photographer set (Bangladesh), 169 test images.
* **Out-of-source checks (`tools/external_checks.py`, `data/eval/results/external_checks.json`) failed:** the silkworm model labels **all 492** third-party silkworm images (a different source, 250 px) "sick" (specificity 0.0, mean confidence 0.91, 100% >= 0.5), so calibration does **not** protect against domain shift. The mulberry model calls only 56% of 400 healthy Thai cultivar leaves healthy (rest leaf spot/leaf rust; mean confidence 0.75), and 58% of 300 unlabelled Indian uploads healthy. Treat predictions on photos unlike the training set as unreliable; the cure is data from the target farms (below), not a threshold.
* **Grasserie:** only 238 images (40 in test, recall 0.65 +- a wide interval); 14 of 40 were called generic disease.
* The generic profile values are working assumptions for expert review.
* `data/images/SILK WORM DATASETS` and the Kaggle mulberry photos' original publishers/licences for D2 are not confirmed (see `sources/SOURCES.md`).

## What to collect next (minimal labelling protocol)
Photograph 150+ samples per class **on the target farms** with phones, in daylight, one subject per photo, 3 angles; label by a sericulture officer on the spot (healthy, each named disease, and "unsure"); record farm, date, camera; keep every photo of one tray/plant in the same split. Re-run `tools/*_split.py`, `train_classifier.py`, `verify_onnx.py`, `external_checks.py`. Add real field photos to the test split first: a model is only credible once it beats the baseline there.

## Mulberry/silkworm legacy models
Kept for the ablation as `data/models/{mulberry,silkworm}_legacy.{onnx,json}`; select with `ARIADNE_MODEL_VARIANT=legacy`. They no longer drive decisions by default.

## Reproduce
```bash
# silkworm
/tmp/conv/venv/bin/python -I tools/silkworm_split.py
/tmp/conv/venv/bin/python -I tools/eval_silkworm_baselines.py      # legacy + third-party baselines
/tmp/conv/venv/bin/python -I tools/train_classifier.py --crop silkworm
# mulberry
/tmp/conv/venv/bin/python -I tools/fetch_mulberry_kaggle.py /tmp/mt/mulberry_small
/tmp/conv/venv/bin/python -I tools/mulberry_split.py /tmp/mt/mulberry_small
/tmp/conv/venv/bin/python -I tools/eval_mulberry_baseline.py /tmp/mt/mulberry_small
/tmp/conv/venv/bin/python -I tools/train_classifier.py --crop mulberry --images /tmp/mt/mulberry_small
# export + verify (tf2onnx: python -m tf2onnx.convert --saved-model /tmp/mt/<crop>_saved --output <crop>.onnx --opset 13)
PYTHONPATH=backend ARIADNE_DATA_DIR=data backend/.venv/bin/python -I tools/verify_onnx.py
PYTHONPATH=backend ARIADNE_DATA_DIR=data backend/.venv/bin/python -I tools/external_checks.py
```
(`/tmp/conv/venv`: Python 3.12 with tensorflow 2.19, tf2onnx, onnx, scikit-learn, remotezip, pillow.) Note: python.org builds need the MobileNetV2 weights placed in `~/.keras/models/` by `curl` (SSL certificate issue).
