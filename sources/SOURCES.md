# Source register

Status: `used` = in the running system, `evaluated` = tried and measured, `rejected` = tried, not used (reason given).

## Live data
| ID | Source | URL | Retrieved | Terms | Used for | Where | Status |
|---|---|---|---|---|---|---|---|
| S1 | Central Silk Board (Ministry of Textiles, GoI) - Reeling cocoon prices by Karnataka market | https://csb.gov.in/statistics/silk-bulletin/reeling-cocoons-prices | 2026-10-26 (and each start-up) | public statistics page; csb.gov.in/robots.txt returns 403 (no explicit rule) - one identified GET per page, at most every 6 h | cocoon price (mean of markets' cross-breed average) | `backend/app/refresh/live_data.py` | used |
| S2 | Central Silk Board - Raw silk prices of Karnataka, Tamil Nadu and Andhra Pradesh | https://csb.gov.in/statistics/silk-bulletin/raw-silk-prices-of-karnataka-tamilnadu-andhra-pradesh | 2026-10-26 | as S1 | yarn price (filature 20/22 avg), thread price (multi-end avg) | same | used |
| S3 | Karnataka Sericulture Dept - Daily cocoon rates page | https://sericulture.karnataka.gov.in/info-4/Daily+Cocoon+Rates/Commercial+Cocoons+Rates/en | 2026-10-26 | page is JavaScript-rendered; rates not retrievable without a browser | - | - | rejected (no machine-readable data) |

## Knowledge base documents (RAG)
| ID | Source | Reference | Used for | Status |
|---|---|---|---|---|
| K1-K13 | 13 public documents (FAO Silk Reeling and Testing Manual, CSB SILKS portal, INSERCO Sericologia, ALCP2, MoSPI, AgEcon, Cuban J. Agric. Sci.) | full citations, URLs, licences and caveats in `data/kb/SOURCES.md` | retrieval-augmented advice | used |
| K14 | General-knowledge note on mulberry stem canker / root knot (not a citation; expert review needed) | `data/kb/mulberry/stem_canker_root_knot.md` | RAG for two disease labels | used (flagged unverified) |

## Models and datasets supplied by the team
| ID | Item | Provenance | Terms | Used for | Status |
|---|---|---|---|---|---|
| M1 | Mulberry leaf disease CNN `model2.h5` (Keras, 128x128, 6 outputs) | team's earlier Flask project ("MULBERRY LEAF PREDICTION"); training data not included | team-owned | disease classification | used (accuracy unverified - see eval notes) |
| M2 | Silkworm disease CNN `modellll.h5` (Keras, 128x128, 5 classes) | same project; notebook `reshmesiri.ipynb` (Colab, trained on ~580 images) | team-owned | disease classification | used (measured ~chance on D2) |
| D1 | Mulberry Leaf Dataset (10 cultivar classes, 224x224, Chiang Mai/Buriram-style names) | supplied by team; original publisher/URL to be confirmed by the team | not stated | evaluated: cultivar classification, NOT disease -> cannot validate M1 | evaluated |
| D2 | Silkworm image set (Healthy 2818 / Infected 2760 / Grasserie 238 / Healthy_Worms 14) | supplied by team; original publisher/URL to be confirmed | not stated | evaluation + (planned) training of a replacement | evaluated |
| D3 | `static/uploads` (1,955 unlabelled user photos from the old Flask app) | team's old app | team-owned | behaviour check of M1 only | evaluated |
| M3 | `Silkworm-Disease-CNN-main` (diseased/undiseased, 250x250 SavedModel, 168k params) | https://github.com/TanmayKJha/Silkworm-Disease-CNN (as named in its README) | see repo | candidate silkworm replacement | to evaluate |

## LLM benchmarking (this project, 2026-10-26)
| ID | Source | Used for |
|---|---|---|
| L1 | Google Gemini API (`models.list`, `generate_content`), own timing runs: 2.5-flash-lite 1.0 s, 2.5-flash 1.5 s, 3-flash-preview 3.5 s, 3.1-flash-lite-preview 3.2 s, 3.5-flash(-lite) 18-24 s then 504 (free-tier key, one structured triage call, 3 runs) | model choice; raw numbers in `docs/AGENT_AND_NETWORK.md` |

## Software the method depends on (cite in a paper)
LangGraph (agent graph + checkpointing), Google OR-Tools (vehicle routing), ChromaDB (retrieval), ONNX Runtime (inference), FastAPI, PostgreSQL. Versions in `backend/requirements.txt`.

## Disease-model research (added 2026-10-26; details and numbers in `docs/MODELS.md`)
| ID | Source | URL | Retrieved | Terms / licence as stated | Use | Where | Status |
|---|---|---|---|---|---|---|---|
| D1a | Provenance of D1: Chom & Surinta, "Mulberry Leaf Dataset", Mendeley Data v3, DOI 10.17632/ds45yy9jrc.3 (5,262 images, 10 cultivars, Thailand, 2020; Data in Brief 2024 article PMC11220858) | https://data.mendeley.com/datasets/ds45yy9jrc/3 | 2026-10-26 | CC BY 4.0 | confirms D1 is cultivar classification (healthy leaves), not disease; used only as a healthy-leaf false-alarm probe | `tools/eval_mulberry_baseline.py` | evaluated (not for disease training) |
| D4 | Kaggle "Mulberry Leaf Dataset" (nahiduzzaman13): 1,091 original photos, Rajshahi Bangladesh, expert-labelled by Bangladesh Sericulture Development Board consultation: Disease Free leaves 440 / Leaf Rust 489 / Leaf spot 162 (11.4 GB of full-resolution JPEGs) | https://www.kaggle.com/datasets/nahiduzzaman13/mulberry-leaf-dataset | 2026-10-26 | Kaggle metadata: "CC0: Public Domain" | ground truth to evaluate the legacy mulberry model and to train the replacement | `tools/fetch_mulberry_kaggle.py` (HTTP range requests, stores 512 px copies only, outside git), `data/eval/mulberry_split.json` | used |
| P1 | Frontiers in Plant Science 2023, "Explainable deep learning model for automatic mulberry leaf disease classification" (PDS-CNN; 1,091 images 440/489/162; ~95% accuracy reported) DOI 10.3389/fpls.2023.1175515 | https://www.frontiersin.org/articles/10.3389/fpls.2023.1175515/full | 2026-10-26 | article licence not shown on fetched text; data statement: "included in the article/supplementary files" | origin of D4 (same class counts); reference accuracy | docs/MODELS.md | cited |
| P2 | PLOS ONE 2024, "Recognition of mulberry leaf diseases based on multi-scale residual network fusion SENet" (uses D4 + own images from Guangxi; reports 98.72%) DOI 10.1371/journal.pone.0298700 | https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0298700 | 2026-10-26 | CC BY 4.0 (article); dataset terms on Kaggle (D4) | corroborates D4 availability | docs/MODELS.md | cited |
| M4 | Keras Applications MobileNetV2 ImageNet weights (`mobilenet_v2_weights_tf_dim_ordering_tf_kernels_1.0_224_no_top.h5`) | https://storage.googleapis.com/tensorflow/keras-applications/mobilenet_v2/mobilenet_v2_weights_tf_dim_ordering_tf_kernels_1.0_224_no_top.h5 | 2026-10-26 | Apache-2.0 (Keras/TensorFlow) | pretrained backbone for both replacement classifiers | `tools/train_classifier.py` | used |
| M5 | Silkworm candidates found but NOT obtainable/usable (details in docs/MODELS.md): Roboflow Universe "silkworm-classification" (104 images, CC BY 4.0; HTTP 403 without account) https://universe.roboflow.com/diseaseclassification-iqdqk/silkworm-classification ; Roboflow "silkworms" https://universe.roboflow.com/navya-bik2e/silkworms-zzbgo (CC BY 4.0 shown; needs account to download); IEEE DataPort silkworm disease set for SAI-RTDETR, DOI 10.21227/yw5f-9q76 (login); AIKosh Andhra Pradesh Sericulture Dept dataset https://aikosh.indiaai.gov.in/home/datasets/details/silkworm_datasets_of_sericulture_department_government_of_andhra_pradesh.html (login/terms unknown); GitHub lonlonago/Silkworm-Health-Status-Detection-Dataset-10197-imagesVOC-YOLO-format (repo holds README + 2 preview images only, no licence); GitHub ngvuthtinh/Silkworm_Segmentation (no licence, not evaluated); Grasserie study dataset 668 healthy / 574 infected https://repository.horizon.ac.id/items/show/10579 (availability unconfirmed) | 2026-10-26 | as listed | candidates only | - | rejected (not freely downloadable or no licence) |
| D5 | Kaggle silkworm disease set (492 images, 247 diseased / 245 healthy) = training data of M3, present locally in `data/models/Silkworm-Disease-CNN-main/Training/Images` (identified from M3's README) | https://github.com/TanmayKJha/Silkworm-Disease-CNN | 2026-10-26 | see repo (no licence file checked) | used only to test overlap with D2 (0 near-duplicates found) | `docs/MODELS.md` | evaluated |

## Conceptual references (agentic-ness criteria) - cited from memory, NOT fetched in this project: verify each before publication
| ID | Reference | Where to verify | Used for |
|---|---|---|---|
| R1 | M. Wooldridge and N. R. Jennings, "Intelligent agents: theory and practice", The Knowledge Engineering Review 10(2), 1995 | DOI 10.1017/S0269888900008122 | autonomy, reactivity, pro-activeness, social ability |
| R2 | S. Russell and P. Norvig, Artificial Intelligence: A Modern Approach (4th ed.) | publisher | agent/environment definitions |
| R3 | S. Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models", 2022 | arXiv:2210.03629 | tool-using reason-act loop |
| R4 | N. Shinn et al., "Reflexion: Language Agents with Verbal Reinforcement Learning", 2023 | arXiv:2303.11366 | reflection/memory criterion |
| R5 | Anthropic, "Building effective agents" (workflows vs agents) | https://www.anthropic.com/research/building-effective-agents | workflow/agent distinction used in `docs/AGENTICNESS.md` |
| K15 | Knowledge-base note compiled from K-documents already in the KB (CSB SILKS silkworm page, `diseases.md`, ALCP2 guideline): first-response hygiene for a silkworm disease of unknown type | `data/kb/silkworm/generic_disease_hygiene.md` | 2026-10-26 | as its sources; general practice, needs expert review | retrieved as the hygiene steps for `silkworm_disease_unspecified` | `backend/app/graph/nodes.py` (RAG query) | used (flagged unverified) |
| M1/M2 status | Legacy Keras models M1 (`model2.h5`) and M2 (`modellll.h5`) are superseded: measured at/below chance (silkworm healthy-vs-sick 0.496; mulberry 0.249 vs 0.432 baseline) | `docs/MODELS.md` | 2026-10-26 | - | kept as `*_legacy.onnx` for the ablation | `data/models/` | superseded |
| M6 | New models trained in this project (MobileNetV2 fine-tunes of M4 on D2 and D4), with temperature scaling | `data/models/{silkworm,mulberry}.onnx`, `tools/train_classifier.py` | 2026-10-26 | project-owned weights; inherits M4 (Apache-2.0), D2 (terms unknown) and D4 (CC0) | decisions | `backend/app/vision/classifier.py` | used (in-distribution only) |
