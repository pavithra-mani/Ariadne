"""Domain tables used by deterministic risk assessment.

DISEASE_PROFILES are working assumptions (severity, spread, loss) that the domain experts on
the team should tune; the severity-urgency matrix is the one in the design doc (Fig. 1).
"""
SEVERITY = ["low", "moderate", "high", "critical"]  # index 0..3
URGENCY = ["low", "medium", "high"]                  # index 0..2

# severity x urgency -> priority (P1 = act now)
PRIORITY_MATRIX = [
    # urgency: low   medium  high
    ["P4", "P4", "P3"],  # low
    ["P4", "P3", "P2"],  # moderate
    ["P3", "P2", "P1"],  # high
    ["P2", "P1", "P1"],  # critical
]

# base_severity: 0..3, spread: 0 slow..2 fast, loss: fraction of output lost if 100% affected
DISEASE_PROFILES: dict[str, dict] = {
    "healthy": {"crop": "*", "healthy": True},
    # mulberry
    "leaf_rust": {"crop": "mulberry", "base_severity": 1, "spread": 1, "loss": 0.30, "infectious": False,
                  "keywords": ["rust", "orange", "pustule", "reddish"]},
    "leaf_spot": {"crop": "mulberry", "base_severity": 1, "spread": 1, "loss": 0.25, "infectious": False,
                  "keywords": ["spot", "brown spot", "halo", "fall"]},
    "powdery_mildew": {"crop": "mulberry", "base_severity": 1, "spread": 1, "loss": 0.25, "infectious": False,
                       "keywords": ["powder", "powdery", "mildew", "white patch", "white"]},
    "leaf_blight": {"crop": "mulberry", "base_severity": 2, "spread": 1, "loss": 0.40, "infectious": False,
                    "keywords": ["blight", "blotch", "curl", "shrivel"]},
    "mosaic_virus": {"crop": "mulberry", "base_severity": 2, "spread": 0, "loss": 0.35, "infectious": True,
                     "keywords": ["mosaic", "mottled", "crinkle", "stunted", "yellow"]},
    # silkworm
    "leaf_shortage": {"crop": "silkworm", "base_severity": 1, "spread": 0, "loss": 1.0, "infectious": False,
                      "keywords": []},  # cascade from a mulberry incident, not a disease
    "grasserie": {"crop": "silkworm", "base_severity": 3, "spread": 2, "loss": 0.90, "infectious": True,
                  "keywords": ["milky", "swollen", "shiny", "restless", "climb", "grasserie"]},
    "flacherie": {"crop": "silkworm", "base_severity": 2, "spread": 2, "loss": 0.70, "infectious": True,
                  "keywords": ["sluggish", "vomit", "diarrhoea", "flaccid", "stop feeding", "flacherie"]},
    "muscardine": {"crop": "silkworm", "base_severity": 2, "spread": 1, "loss": 0.60, "infectious": True,
                   "keywords": ["chalky", "mummified", "hard", "muscardine", "white powder"]},
    "pebrine": {"crop": "silkworm", "base_severity": 3, "spread": 2, "loss": 1.00, "infectious": True,
                "keywords": ["black spot", "pepper", "uneven", "pebrine"]},
}

# Confidence below this means "I am not sure": escalate to a human expert rather than act.
MIN_CONFIDENCE = 0.5
ESCALATE_LOSS = 0.20  # expected output loss above which the reeler should be told

LEAF_PER_KG_COCOON = 17.0  # approx. kg of leaf consumed per kg of cocoon (placeholder, tune)
HORIZON_DAYS = 14


def priority(severity_idx: int, urgency_idx: int) -> str:
    return PRIORITY_MATRIX[max(0, min(3, severity_idx))][max(0, min(2, urgency_idx))]

COCOON_PER_YARN = 9.5  # kg fresh cocoon per kg raw silk (design corpus: ~8-12)
