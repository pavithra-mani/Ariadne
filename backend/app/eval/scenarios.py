"""Scripted end-to-end scenarios for the three entry points plus edge cases (design doc section 5).

Each scenario is run through the real HTTP API on a freshly seeded database. Expectations are
deliberately about behaviour (route, tools, termination), not about exact numbers.
"""
from dataclasses import dataclass, field


@dataclass
class Scenario:
    id: str
    entry: str                      # farmer | reeler | spinner | question
    user: str
    message: str = ""
    fields: dict = field(default_factory=dict)
    image: str | None = None
    setup: dict | None = None       # e.g. {"stock": {"entity_user": "reeler1", "product": "yarn", "on_hand": 0}}
    route: str = ""                 # expected supervisor route
    tools_all: list[str] = field(default_factory=list)
    tools_none: list[str] = field(default_factory=list)
    terminal: tuple[str, ...] = ()  # acceptable status right after the first run
    after: str | None = None        # approve | reject: human decision applied to every pending deal
    final: tuple[str, ...] = ()     # acceptable status after the decision
    abstain: bool = False           # correct behaviour is to abstain / escalate / ask an expert
    sequence: tuple[str, ...] = ("intake", "triage_supervisor")


RECOVERY_TOOLS = ["ortools.vrp", "postgres.deals"]
SPEC = {"mulberry": "mulberry_agent", "silkworm": "silkworm_agent", "reeler": "reeler_agent",
        "spinner": "spinner_agent"}


def seq(route: str, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    return ("intake", "triage_supervisor", SPEC[route], "agentic_rag", "risk_assessment") + extra


SCENARIOS: list[Scenario] = [
    # ---- farmer incidents
    Scenario("F1 silkworm grasserie photo", "farmer", "sf1", "my worms are sick", {"affected_pct": 60},
             "grasserie_sample.jpg", route="silkworm", tools_all=["disease_classifier[stub]", "chroma.retrieve"],
             terminal=("awaiting_approval", "escalated", "advised"), sequence=seq("silkworm")),
    Scenario("F2 silkworm flacherie text only", "farmer", "sf2",
             "larvae are sluggish, stopped feeding, vomiting and flaccid", {"affected_pct": 30},
             route="silkworm", tools_none=["disease_classifier[stub]"],
             terminal=("awaiting_approval", "escalated", "advised"), sequence=seq("silkworm")),
    Scenario("F3 mulberry mild mildew", "farmer", "mf1", "white powder on leaves", {"affected_pct": 8},
             "powdery_mildew_sample.jpg", route="mulberry", tools_none=RECOVERY_TOOLS, terminal=("advised",),
             sequence=seq("mulberry")),
    Scenario("F4 mulberry severe blight", "farmer", "mf2", "blight everywhere", {"affected_pct": 100},
             "leaf_blight_sample.jpg", route="mulberry", tools_all=["chroma.retrieve"],
             terminal=("awaiting_approval", "escalated", "advised"), sequence=seq("mulberry")),
    Scenario("F5 healthy leaf is not an incident", "farmer", "mf3", "please check this leaf", {},
             "healthy_leaf.jpg", route="mulberry", tools_none=RECOVERY_TOOLS, terminal=("answered",),
             sequence=seq("mulberry")),
    Scenario("F6 blurry photo -> expert referral", "farmer", "sf3", "what is this?", {}, "blurry_photo.jpg",
             route="silkworm", tools_none=RECOVERY_TOOLS, terminal=("advised",), abstain=True,
             sequence=seq("silkworm")),
    # ---- reeler incidents
    Scenario("R1 low yarn output (factory)", "reeler", "reeler1", "machine breakdown",
             {"incident_type": "low_yarn_output", "reduction_pct": 90, "duration_days": 14}, route="reeler",
             tools_all=["calc.reallocate"], terminal=("awaiting_approval", "escalated", "advised"),
             sequence=seq("reeler")),
    Scenario("R2 cocoon shortage", "reeler", "reeler2", "cocoon supply is low",
             {"incident_type": "cocoon_shortage", "quantity_kg": 2500, "duration_days": 10}, route="reeler",
             terminal=("awaiting_approval", "escalated", "advised"), sequence=seq("reeler")),
    Scenario("R3 minor delay", "reeler", "reeler3", "small delay",
             {"incident_type": "delivery_delay", "delay_days": 1, "quantity_kg": 1}, route="reeler",
             tools_none=RECOVERY_TOOLS, terminal=("advised",), sequence=seq("reeler")),
    Scenario("R4 zero yarn stock", "reeler", "reeler4", "delivery delayed by 6 days",
             {"incident_type": "delivery_delay", "delay_days": 6}, route="reeler",
             setup={"stock": {"user": "reeler4", "product": "yarn", "on_hand": 0}},
             terminal=("advised", "awaiting_approval", "escalated"), sequence=seq("reeler")),
    Scenario("R5 cocoon stock critical (stock trigger) -> approve", "reeler", "reeler5", "my cocoon stock is critical",
             {"incident_type": "low_stock", "product": "cocoon"}, route="reeler",
             setup={"stock": {"user": "reeler5", "product": "cocoon", "on_hand": 50}},
             tools_all=["calc.rop", "ortools.vrp"], terminal=("awaiting_approval",), after="approve",
             final=("resolved", "partially_resolved"),
             sequence=("intake", "triage_supervisor", "stock_monitor_agent", "agentic_rag", "risk_assessment")),
    # ---- spinner requests
    Scenario("S1 demand surge -> approve", "spinner", "spinner1", "demand surge", {"target_gap": 60, "horizon_days": 7},
             route="spinner", tools_all=["calc.gap", "ortools.vrp"], terminal=("awaiting_approval",),
             after="approve", final=("resolved", "partially_resolved"), sequence=seq("spinner")),
    Scenario("S2 demand surge -> reject", "spinner", "spinner2", "demand surge", {"target_gap": 60, "horizon_days": 7},
             route="spinner", terminal=("awaiting_approval",), after="reject", final=("rejected",),
             sequence=seq("spinner")),
    Scenario("S3 small target met", "spinner", "spinner3", "need a little more", {"target_qty": 5, "horizon_days": 30},
             route="spinner", tools_none=RECOVERY_TOOLS, terminal=("advised",), sequence=seq("spinner")),
    Scenario("S4 impossible target (no source in 5 searches)", "spinner", "spinner4", "huge order",
             {"target_qty": 90000, "horizon_days": 7}, route="spinner", tools_all=["ortools.vrp"],
             terminal=("awaiting_approval", "escalated"), abstain=True, sequence=seq("spinner")),
    # ---- questions
    Scenario("Q1 farmer knowledge question", "question", "sf1", "how should fresh cocoons be stored?", route="silkworm",
             tools_none=RECOVERY_TOOLS + ["disease_classifier[stub]"], terminal=("answered",), sequence=seq("silkworm")),
    Scenario("Q2 reeler knowledge question", "question", "reeler1", "how should raw silk yarn be stored?", route="reeler",
             tools_none=RECOVERY_TOOLS, terminal=("answered",), sequence=seq("reeler")),
    Scenario("Q3 out-of-scope question", "question", "sf2", "what is the capital of France?", route="silkworm",
             tools_none=RECOVERY_TOOLS, terminal=("answered",), abstain=True,
             sequence=seq("silkworm")),
]
