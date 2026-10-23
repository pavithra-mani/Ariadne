"""Recovery planning agent: choose a sourcing strategy per case from real candidate statistics.

The model decides *how to trade off* cost, distance and number of pick-ups given urgency and perishability;
the candidate set, capacity, time limits, the 5-search bound and the human approval stay deterministic."""
import json

from app.llm.provider import LLMUnavailable, get_llm
from app.llm.schemas import StrategyOut

STRATEGIES = ("cheapest", "nearest", "fewest_sources", "balanced")
SYSTEM = """You plan how to replace missing supply in a sericulture supply chain. For each case pick ONE strategy:
- cheapest: lowest price per kg first (when there is time and the product keeps)
- nearest: shortest distance first (perishable goods, little time left, or tiny quantities)
- fewest_sources: biggest suppliers first so fewer pick-ups are needed (large quantities, many trucks)
- balanced: a price/distance blend (default when unsure)
Use the candidate statistics given. Give a one-sentence reason that cites them. Return JSON."""


def order_candidates(cands: list[dict], strategy: str | None) -> list[dict]:
    if strategy == "cheapest":
        return sorted(cands, key=lambda c: (c["unit_price"], c["distance_km"]))
    if strategy == "nearest":
        return sorted(cands, key=lambda c: c["distance_km"])
    if strategy == "fewest_sources":
        return sorted(cands, key=lambda c: (-c["offer"], c["distance_km"]))
    return cands  # 'balanced' = the default score order


def choose_strategies(cases: list[dict], stats: dict[int, dict]) -> dict[int, tuple[str, str]]:
    """{case idx: (strategy, reason)}. Defaults to balanced when no LLM or it fails."""
    default = {c["idx"]: ("balanced", "default price/distance balance") for c in cases}
    llm = get_llm()
    open_cases = [c for c in cases if c["status"] == "open"]
    if llm is None or not open_cases:
        return default
    facts = [{"case": c["idx"], "product": c["product"], "qty_kg": c["qty"], "direction": c["direction"],
              "days_until_buyer_runs_short": c.get("deadline_days"), **stats.get(c["idx"], {})} for c in open_cases]
    try:
        out = llm.generate_json(StrategyOut, SYSTEM, json.dumps(facts, default=str), "recovery.strategy")
    except LLMUnavailable:
        return default
    for ch in out.choices:
        if ch.case in default and ch.strategy in STRATEGIES:
            default[ch.case] = (ch.strategy, ch.reason[:220])
    return default
