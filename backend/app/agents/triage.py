"""LLM triage of a free-text message: classify the intent and extract only the numbers the user stated.

Replaces keyword matching when an LLM is available. Anything the model extracts is verified against the
message (a number must literally appear in it), and a vague message becomes a follow-up question instead of
a guessed incident."""
import re

from app.calc.impact import INPUT_PRODUCT, OUTPUT_PRODUCT
from app.llm.provider import LLMUnavailable, get_llm
from app.llm.schemas import DiagnosisOut, TriageOut

CAPS = {
    "mulberry_farm": "reports leaf disease or pests on the mulberry plot (affected_pct = share of the plot affected), reports low leaf stock (low_stock, product=leaves), or asks a question",
    "silkworm_farm": "reports silkworm disease (affected_pct = share of trays/larvae affected), reports low cocoon or leaf stock (low_stock, product=cocoon|leaves), or asks a question",
    "reeler": ("reports low yarn output / a factory problem (supply_problem, incident_type=low_yarn_output, reduction_pct, duration_days), "
               "a cocoon supply shortage (supply_problem, incident_type=cocoon_shortage, quantity_kg, duration_days), a delivery delay "
               "(supply_problem, incident_type=delivery_delay, delay_days, quantity_kg), low stock (low_stock, product=cocoon|yarn), or asks a question"),
    "spinner": ("raises a yarn target / demand surge (demand_request, target_qty in kg, horizon_days), reports low stock "
                "(low_stock, product=yarn|thread), or asks a question"),
}
SYSTEM = """You triage messages for Ariadne, a sericulture supply-chain assistant. The sender is a {role} who {caps}.
Classify the message:
- question: asks for general information or advice (how/what/why...), and says nothing is wrong at their own business
- disease_report | supply_problem | demand_request | low_stock: as described above
- unclear: you cannot tell what they want. A vague complaint with no detail ("something is wrong", "we have a problem", "help") is
  ALWAYS unclear, never a question. Then write ONE short clarifying question in `clarification` that asks for what is missing
  (which product/crop, what happened, roughly how much).
Examples: "how should I store cocoons?" -> question. "something is wrong here" -> unclear. "we are nearly out of cocoons" -> low_stock (product cocoon).
If the user states how much stock they have now ("only 200 kg left"), put it in `stock_now_kg`.
Extract ONLY numbers the user actually wrote (percentages, kg, days). Never invent a number: leave it null.
Return JSON for the schema."""
ALLOWED = {
    "mulberry_farm": {"question", "disease_report", "low_stock", "unclear"},
    "silkworm_farm": {"question", "disease_report", "low_stock", "unclear"},
    "reeler": {"question", "supply_problem", "low_stock", "unclear"},
    "spinner": {"question", "demand_request", "low_stock", "unclear"},
}
NUM_FIELDS = ("affected_pct", "reduction_pct", "duration_days", "delay_days", "quantity_kg", "target_qty", "horizon_days", "stock_now_kg")


def _stated(x: float, msg: str) -> bool:
    nums = {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*\.?\d*", msg)}
    return any(abs(x - n) < 1e-6 for n in nums)


def triage(state: dict) -> dict | None:
    """Return {'mode', 'fields', 'clarify', 'summary'} or None when the LLM is unavailable (caller falls back)."""
    llm = get_llm()
    msg = (state.get("message") or "").strip()
    role = state["role"]
    if llm is None or not msg or role not in CAPS:
        return None
    try:
        out = llm.generate_json(TriageOut, SYSTEM.format(role=role.replace("_", " "), caps=CAPS[role]),
                                f"Message: {msg}", "triage")
    except LLMUnavailable:
        return None
    intent = out.intent if out.intent in ALLOWED[role] else "unclear"
    fields = dict(state.get("fields") or {})
    for k in NUM_FIELDS:                      # only numbers literally present in the message survive
        v = getattr(out, k)
        if v is not None and _stated(v, msg):
            fields.setdefault(k, v)
    if intent == "unclear" and out.clarification:  # `confidence` is certainty in the classification, so no threshold here
        return {"mode": "query", "fields": fields, "clarify": out.clarification, "summary": "unclear -> asked a follow-up"}
    if intent in ("question", "unclear"):
        return {"mode": "query", "fields": fields, "clarify": None, "summary": f"question ({out.confidence:.0%})"}
    if intent == "disease_report":
        fields.setdefault("incident_type", "disease")
    elif intent == "low_stock":
        product = out.product if out.product in {INPUT_PRODUCT.get(role), OUTPUT_PRODUCT.get(role)} else None
        fields.update({"incident_type": "low_stock", **({"product": product} if product else {})})
    elif intent == "supply_problem" and role == "reeler":
        it = out.incident_type if out.incident_type in ("low_yarn_output", "cocoon_shortage", "delivery_delay") else None
        if it:
            fields.setdefault("incident_type", it)
    # demand_request: the spinner agent reads target_qty / horizon_days straight from the fields
    return {"mode": "incident", "fields": fields, "clarify": None,
            "summary": f"{intent}" + (f"/{fields.get('incident_type')}" if fields.get("incident_type") else "") + f" ({out.confidence:.0%})"}


DIAG_SYSTEM = """You help identify a {crop} problem from a farmer's written description only (no photo).
Choose the single best label from this list, or "unknown" if the description does not clearly match one:
{labels}
Be conservative: confidence above 0.7 is not justified without a photo. Return JSON."""


def diagnose_text(crop: str, message: str, labels: list[str]) -> tuple[str | None, float, str] | None:
    """Symptom text -> (label, confidence, rationale), or None when the LLM is unavailable."""
    llm = get_llm()
    if llm is None or not message.strip():
        return None
    try:
        out = llm.generate_json(DiagnosisOut, DIAG_SYSTEM.format(crop=crop, labels=", ".join(labels)), f"Description: {message}", "diagnose.text")
    except LLMUnavailable:
        return None
    if out.label not in labels:
        return None, 0.0, out.rationale
    return out.label, min(max(out.confidence, 0.0), 0.7), out.rationale
