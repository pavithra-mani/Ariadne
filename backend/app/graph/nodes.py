"""LangGraph nodes: intake, supervisor, specialists, RAG, risk, impact, advisory, finalize."""
import re

from app.agents.advisor import produce
from app.agents.triage import diagnose_text, triage
from app.calc.impact import farmer_impact
from app.db.models import Entity, Incident, Notification
from app.db.session import session_scope
from app.graph.common import save_incident, traced
from app.graph.ops_agents import ops_advisory, reeler_agent, spinner_agent  # noqa: F401
from app.graph.stock_agent import looks_like_low_stock, low_stock_agent, stock_advisory
from app.graph.profiles import (DISEASE_PROFILES, ESCALATE_LOSS, MIN_CONFIDENCE, SEVERITY, URGENCY,
                                priority)
from app.llm.schemas import Advisory, AnswerOut
from app.llm.provider import get_llm
from app.llm.structured import structure  # noqa: F401
from app.memory.incidents import recall, remember
from app.rag.agentic import agentic_rag
from app.vision.classifier import get_classifier, normalise_label

ISSUE_WORDS = re.compile(
    r"disease|spot|dying|dead|yellow|powder|milky|sick|outbreak|pest|infect|problem|issue|mildew|rust|"
    r"blight|worm|larva|vomit|shrivel|wilt|curl|shortfall|short|delay|late|breakdown|machine|factory|low |"
    r"less |demand|surge|target|increase|urgent|cannot|can't", re.I)
QUESTION = re.compile(r"^\s*(how|what|why|when|where|which|who|can|could|should|is|are|do|does|will|tell me)\b|\?\s*$", re.I)
OWN_PROBLEM = re.compile(r"\b(my|our)\b", re.I)


def is_question(msg: str) -> bool:
    """A general question ('How should cocoons be stored?') versus a report ('my larvae are dying')."""
    return bool(QUESTION.search(msg)) and not OWN_PROBLEM.search(msg)


ROUTE_BY_ROLE = {"mulberry_farm": "mulberry", "silkworm_farm": "silkworm", "reeler": "reeler", "spinner": "spinner"}
CROP_TOPIC = {"mulberry": "mulberry", "silkworm": "silkworm"}


def pretty(label: str) -> str:
    return label.replace("_", " ")


# ---------------------------------------------------------------- intake + supervisor
@traced("intake")
def intake(state):
    fields = state.get("fields") or {}
    msg = (state.get("message") or "").strip()
    role = state["role"]
    kind = fields.get("incident_type")
    structured_form = kind or any(k in fields for k in ("target_qty", "quantity_kg", "reduction_pct", "delay_days", "duration_days"))
    if msg and not state.get("image_path") and not structured_form:
        tri = triage(state)  # LLM reads the free text; None -> keyword rules below
        if tri:
            if tri["clarify"]:
                return {"mode": "query", "message": msg, "fields": tri["fields"], "clarify": tri["clarify"],
                        "advisory": {"type": "clarify", "question": tri["clarify"], "answer": tri["clarify"],
                                     "headline": "I need a bit more detail", "structured_by": "agent"},
                        "_tools": ["llm.triage"], "_summary": f"LLM triage: {tri['summary']}"}
            return {"mode": tri["mode"], "message": msg, "fields": tri["fields"], "_tools": ["llm.triage"],
                    "_summary": f"LLM triage: {tri['summary']}"}
    if kind != "low_stock" and not state.get("image_path") and looks_like_low_stock(msg):
        fields = {**fields, "incident_type": "low_stock"}  # "my cocoon stock is critical" -> stock incident
        kind = "low_stock"
    if kind in ("low_stock", "surplus"):
        return {"mode": "incident", "message": msg, "fields": fields, "_summary": f"role={role}, mode=incident ({kind.replace('_', ' ')})"}
    if role in ("mulberry_farm", "silkworm_farm"):
        issue = bool(state.get("image_path")) or kind in ("disease", "input_shortage") or \
            (bool(ISSUE_WORDS.search(msg)) and not is_question(msg))
    elif role in ("reeler", "spinner"):
        structured = any(k in fields for k in ("target_qty", "surge_pct", "quantity_kg", "reduction_pct",
                                                "delay_days", "duration_days"))
        issue = bool(kind and kind != "query") or structured or \
            (bool(ISSUE_WORDS.search(msg)) and not is_question(msg))
    else:
        issue = False
    return {"mode": "incident" if issue else "query", "message": msg, "fields": fields,
            "_summary": f"role={role}, mode={'incident' if issue else 'query'}, "
                        f"image={'yes' if state.get('image_path') else 'no'}"}


@traced("triage_supervisor", "supervisor")
def supervisor(state):
    route = ROUTE_BY_ROLE[state["role"]]
    with session_scope() as db:
        ent = db.get(Entity, state["entity_id"])
        village = ent.village
    from app.graph.ops_agents import REELER_KINDS, infer_reeler_type
    kind = {"mulberry": "disease", "silkworm": "disease", "spinner": "demand_surge"}.get(route)
    if (state.get("fields") or {}).get("incident_type") == "yarn_shortfall":
        kind = "yarn_shortfall"
    if (state.get("fields") or {}).get("incident_type") in ("low_stock", "surplus"):
        kind = state["fields"]["incident_type"]
    if route == "reeler":
        kind = REELER_KINDS[infer_reeler_type(state.get("fields") or {}, state.get("message", ""))]
    mem = recall(state["entity_id"], kind or "query", None, village) if state["mode"] == "incident" else \
        {"recurring": False, "count": 0, "similar": []}
    return {"route": route, "memory": mem,
            "_tools": ["incident_memory.recall"],
            "_summary": f"route={route}; recurring={mem['recurring']} ({mem['count']} earlier)"}


def route_after_supervisor(state) -> str:
    if (state.get("fields") or {}).get("incident_type") in ("low_stock", "surplus"):
        return "stock_monitor_agent"
    return {"mulberry": "mulberry_agent", "silkworm": "silkworm_agent",
            "reeler": "reeler_agent", "spinner": "spinner_agent"}[state["route"]]


# ---------------------------------------------------------------- specialists
def match_symptoms(crop: str, text: str) -> tuple[str | None, float]:
    best, score = None, 0
    for label, prof in DISEASE_PROFILES.items():
        if prof.get("crop") != crop:
            continue
        hits = sum(1 for k in prof["keywords"] if k in text.lower())
        if hits > score:
            best, score = label, hits
    return best, (min(0.35 + 0.1 * score, 0.6) if best else 0.0)


SILKWORM_DISCRIMINATOR = ("Which of these do you see? (1) milky fluid, swollen shiny skin, larvae climbing the tray edge; "
                          "(2) black pepper-like spots, uneven growth; (3) chalky white, hard, mummified larvae; "
                          "(4) sluggish larvae that vomit, have diarrhoea or have stopped feeding.")


def _specific_from_symptoms(crop: str, message: str, tools: list) -> tuple[str, float] | None:
    """A specific disease label from the farmer's written symptoms (>= MIN_CONFIDENCE), or None."""
    if not (message or "").strip():
        return None
    labels = [l for l, pr in DISEASE_PROFILES.items() if pr.get("crop") == crop and not pr.get("provisional") and pr.get("keywords")]
    dx = diagnose_text(crop, message, labels)
    if dx is not None and dx[0] in labels and dx[1] >= MIN_CONFIDENCE:
        tools.append("llm.diagnose")
        return dx[0], dx[1]
    label, conf = match_symptoms(crop, message)
    if label in labels and conf >= MIN_CONFIDENCE:
        return label, conf
    return None


def farmer_agent(crop: str):
    @traced(f"{crop}_agent", "specialist")
    def node(state):
        if state["mode"] == "query":  # knowledge question: specialist hands straight to RAG
            return {"finding": {"query": True, "crop": crop}, "incident_kind": "query",
                    "_summary": "knowledge question (no incident)"}
        fields, tools = state.get("fields") or {}, []
        affected_pct = float(fields.get("affected_pct", 20))
        days_to_harvest = fields.get("days_to_harvest")
        pred, image_note = None, {}
        if fields.get("incident_type") == "input_shortage":  # cascaded from an upstream mulberry incident
            label, conf, source = "leaf_shortage", 1.0, "cascade"
        elif state.get("image_path"):
            pred = get_classifier(crop).predict(state["image_path"])
            tools.append(f"disease_classifier[{pred.source}]")
            label, conf, source = normalise_label(pred.label), pred.confidence, pred.source
            if DISEASE_PROFILES.get(label, {}).get("provisional"):
                # the image says "diseased, type unknown": a farmer's symptom text may name the disease
                specific = _specific_from_symptoms(crop, state.get("message", ""), tools)
                if specific:
                    image_label, image_conf = label, conf
                    label, conf, source = specific[0], specific[1], "image+symptoms"
                    image_note = {"image_label": image_label, "image_confidence": round(image_conf, 3)}
        else:
            label, conf = match_symptoms(crop, state.get("message", ""))
            source = "text_symptoms"
            labels = [l for l, pr in DISEASE_PROFILES.items() if pr.get("crop") == crop and not pr.get("provisional")]
            dx = diagnose_text(crop, state.get("message", ""), labels)  # LLM reads the symptom description
            if dx is not None:
                label, conf, source = dx[0], dx[1], "llm_symptoms"
                tools.append("llm.diagnose")
        prof = DISEASE_PROFILES.get(label or "")
        known = prof is not None
        uncertain = (not known) or conf < MIN_CONFIDENCE
        healthy = bool(prof and prof.get("healthy"))
        finding = {"crop": crop, "label": label, "confidence": round(conf, 3), "source": source,
                   "is_stub": bool(pred and pred.is_stub), "healthy": healthy, "uncertain": uncertain and not healthy,
                   "affected_pct": affected_pct, "top_k": pred.top_k if pred else [],
                   "infectious": bool(prof and prof.get("infectious")),
                   "loss_fraction": 0.0}
        assessment = None
        if known and not healthy:
            sev = prof["base_severity"] + (1 if affected_pct >= 40 else -1 if affected_pct <= 10 else 0)
            urg = prof["spread"] + (1 if affected_pct >= 40 or (days_to_harvest is not None and float(days_to_harvest) <= 5) else 0)
            if prof["infectious"] and crop == "silkworm":
                urg = 2
            finding["loss_fraction"] = round(prof["loss"] * affected_pct / 100, 3)
            assessment = {"severity_level": max(0, min(3, sev)), "urgency_level": max(0, min(2, urg)),
                          "rationale": [f"{pretty(label)} base severity {SEVERITY[prof['base_severity']]}",
                                        f"{affected_pct:.0f}% of crop affected",
                                        f"spread: {['slow', 'medium', 'fast'][prof['spread']]}"]}
        finding.update(image_note)
        extra = {}
        if prof and prof.get("provisional"):  # disease present, type unknown: ask questions, hygiene steps, expert confirmation
            finding["provisional"] = True
            finding["follow_up_question"] = SILKWORM_DISCRIMINATOR
            extra["rag_query"] = "silkworm disease isolate disinfect remove dead larvae hygiene"
        if healthy:
            finding["healthy"] = True
        mode = "query" if healthy else "incident"
        return {"finding": finding, "assessment": assessment, "incident_kind": "disease", "mode": mode, **extra,
                "_tools": tools,
                "_summary": f"{label or 'no diagnosis'} ({conf:.0%}, {source})" + (" - UNCERTAIN" if finding["uncertain"] else "")}
    return node


mulberry_agent = farmer_agent("mulberry")
silkworm_agent = farmer_agent("silkworm")


# ---------------------------------------------------------------- agentic RAG
@traced("agentic_rag", "rag")
def rag_node(state):
    f = state.get("finding") or {}
    route = state.get("route")
    intent = ""
    if state.get("rag_query"):
        query, topics, hint = state["rag_query"], None, ""
    elif state["mode"] == "query" or not f.get("label"):
        query, topics, hint = state.get("message") or "sericulture", None, ""
    elif route in ("mulberry", "silkworm"):
        query, intent = f"{pretty(f['label'])} {route}", "management mitigation"
        topics, hint = [CROP_TOPIC[route]], route
    else:
        query, topics, hint = state.get("rag_query") or state.get("message"), None, ""
    if state.get("fields", {}).get("rag_query"):
        query = state["fields"]["rag_query"]
    llm_rag = state.get("mode") == "incident" and state.get("user_id") is not None and get_llm() is not None
    res = agentic_rag(query, topics=topics, hint=hint, intent=intent, use_llm=llm_rag)
    return {"rag": res.dict(), "_tools": ["chroma.retrieve", "llm.rag_grade" if res.graded_by == "llm" else "rag.grade"],
            "_summary": ("ABSTAINED" if res.abstained else f"{len(res.passages)} passages, conf {res.confidence:.2f}")
                        + f"; {len(res.queries_tried)} quer{'y' if len(res.queries_tried) == 1 else 'ies'}"}


# ---------------------------------------------------------------- risk assessment (severity x urgency)
@traced("risk_assessment", "risk")
def risk_node(state):
    a = state.get("assessment")
    if not a:
        return {"risk": {"severity": None, "urgency": None, "priority": None, "rationale": []},
                "_summary": "no incident risk (query or healthy)"}
    sev, urg = a["severity_level"], a["urgency_level"]
    risk = {"severity": SEVERITY[sev], "urgency": URGENCY[urg], "priority": priority(sev, urg),
            "rationale": a.get("rationale", [])}
    return {"risk": risk, "_summary": f"{risk['severity']} x {risk['urgency']} -> {risk['priority']}"}


# ---------------------------------------------------------------- supply impact branch
@traced("supply_impact", "impact")
def supply_impact_node(state):
    route, f, risk = state.get("route"), state.get("finding") or {}, state.get("risk") or {}
    if f.get("incident_type") in ("low_stock", "surplus"):
        imp = f["impact"]
        return {"supply_impact": imp, "_tools": ["postgres.stock", "calc.exposure"],
                "_summary": f"{imp['product']} stock: order {imp['order_qty']:.0f} kg, {imp['n_at_risk']}/{imp['n_affected']} buyers at risk, "
                            f"{len(imp['cases'])} recovery case(s)"}
    if route in ("mulberry", "silkworm") and state["mode"] == "incident" and not f.get("uncertain"):
        with session_scope() as db:
            farm = db.get(Entity, state["entity_id"])
            imp = farmer_impact(db, farm, f.get("loss_fraction", 0))
        escalate = f.get("loss_fraction", 0) >= ESCALATE_LOSS or risk.get("priority") == "P1" or \
            (f.get("infectious") and f.get("affected_pct", 0) >= 20)
        imp["escalate"] = bool(escalate)
        imp["direction"] = "upstream"
        imp["cases"] = []  # at-risk buyers get their own incident (graph/propagate.py)
        return {"supply_impact": imp, "_tools": ["postgres.stock", "calc.safety_stock", "calc.exposure"],
                "_summary": f"{imp['n_affected']} buyers exposed, {imp['n_at_risk']} at risk, "
                            f"shortfall {imp['total_shortfall']} kg, escalate={escalate}"}
    if route in ("reeler", "spinner") and f.get("impact"):
        imp = f["impact"]
        return {"supply_impact": imp, "_tools": ["postgres.stock", "calc.exposure"],
                "_summary": f"{imp['n_at_risk']}/{imp['n_affected']} at risk, shortfall {imp['total_shortfall']} kg, "
                            f"{len(imp.get('cases', []))} recovery case(s)"}
    return {"supply_impact": {"at_risk": False, "n_affected": 0, "escalate": False},
            "_summary": "no supply impact assessed"}


# ---------------------------------------------------------------- health / operational branch + advisory

@traced("health_operational_impact", "impact")
def health_node(state):
    """Health / operational branch: diagnosis + corrective evidence (independent of supply branch)."""
    f, rag, risk = state.get("finding") or {}, state.get("rag") or {}, state.get("risk") or {}
    hi = {"diagnosis": f.get("label"), "crop": f.get("crop"), "severity": risk.get("severity"),
          "urgency": risk.get("urgency"), "corrective_points": [p["text"] for p in rag.get("points", [])][:4],
          "evidence_found": not rag.get("abstained", True)}
    return {"health_impact": hi, "_summary": f"{hi['diagnosis'] or 'query'}; evidence={'yes' if hi['evidence_found'] else 'none'}"}


def _short(s: str, n: int = 220) -> str:
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


EXPERT_STEP = "Contact your nearest sericulture extension officer or a veterinarian-level expert to confirm before acting."


@traced("advisory_action_plan", "advisory")
def advisory_node(state):
    rag, f, risk, imp = state.get("rag") or {}, state.get("finding") or {}, state.get("risk") or {}, state.get("supply_impact") or {}
    points = [p["text"] for p in rag.get("points", [])]
    cites = sorted({p["citation"] for p in rag.get("points", [])})
    if state["mode"] == "query":
        facts = {"question": state.get("message"), "evidence": rag.get("points", []), "abstained": rag.get("abstained", False)}

        def fb():
            if rag.get("abstained"):
                return AnswerOut(answer="I could not find reliable information on this in the knowledge base. "
                                        "Please ask an expert or your local sericulture office.", abstained=True)
            return AnswerOut(answer=_short(points[0], 400), key_points=[_short(p, 300) for p in points[1:5]], citations=cites)
        out, by, meta = produce(state, AnswerOut, "Answer the user's question. Search the knowledge base yourself if the evidence given is thin; if it cannot answer, abstain.",
                                facts, fb, locked={"abstained": bool(rag.get("abstained"))}, agent_locked={})
        res = {"type": "answer", **out.model_dump(), "structured_by": by}
        return _adv(res, by, meta, f"answer by {by}" + (" (abstained)" if res["abstained"] else ""))

    if f.get("incident_type") in ("low_stock", "surplus"):
        out, by, meta = stock_advisory(state)
        res = {"type": "advisory", **out.model_dump(), "structured_by": by}
        _remember(state, res["headline"])
        return _adv(res, by, meta, f"stock advisory by {by}")
    if state.get("route") in ("reeler", "spinner"):
        out, by, meta = ops_advisory(state)
        res = {"type": "advisory", **out.model_dump(), "structured_by": by}
        _remember(state, res["headline"])
        return _adv(res, by, meta, f"ops advisory by {by}")
    label = f.get("label")
    escalate = bool(imp.get("escalate"))
    uncertain = f.get("uncertain") or rag.get("abstained")
    reason = ""
    if escalate:
        reason = (f"Expected loss ~{f.get('loss_fraction', 0):.0%} of output"
                  + (f"; {imp.get('n_at_risk', 0)} downstream buyer(s) face a shortfall" if imp.get("n_at_risk") else "")
                  + ("; infectious disease" if f.get("infectious") else "") + ".")
    facts = {"crop": f.get("crop"), "diagnosis": label, "confidence": f.get("confidence"), "source": f.get("source"),
             "affected_pct": f.get("affected_pct"), "severity": risk.get("severity"), "urgency": risk.get("urgency"),
             "priority": risk.get("priority"), "evidence": rag.get("points", []), "escalate_to_reeler": escalate,
             "escalation_reason": reason, "uncertain": bool(uncertain), "memory": state.get("memory")}

    def fb():
        if f.get("provisional") and not f.get("uncertain"):
            return _provisional_advisory(f, risk, points, cites, escalate, reason)
        if f.get("uncertain") or not label:
            return Advisory(headline="Diagnosis uncertain - expert check needed",
                            diagnosis="The system is not confident enough to name the problem." +
                                      (f" Best guess: {pretty(label)} ({f.get('confidence', 0):.0%})." if label else ""),
                            mitigation_steps=[EXPERT_STEP, "Isolate affected plants/trays and take clearer photos in daylight."],
                            escalate=False, citations=cites)
        mit = [(lambda t: t[0].upper() + t[1:])(p.split(": ", 1)[1]) for p in points if p.lower().startswith("mitigation")]
        other = [p for p in points if not p.lower().startswith(("mitigation", "symptoms", "cause"))]
        steps = [_short(p) for p in (mit + other)[:4]] or [EXPERT_STEP]
        if imp.get("escalate"):
            follow = (["The silkworm farmers you supply have been alerted so they can arrange alternative leaves."]
                      if state.get("route") == "mulberry" else
                      ["Your reelers have been alerted to the expected shortfall so alternative cocoons can be arranged."])
        else:
            follow = ["Re-inspect in 2-3 days and report again if it spreads."]
        if state.get("memory", {}).get("recurring"):
            follow.append(f"This has happened before ({state['memory']['count']} earlier incident(s)) - review what caused it.")
        return Advisory(headline=f"{pretty(label).title()} - priority {risk.get('priority')}",
                        diagnosis=f"{pretty(label).title()} detected on {f['crop']} ({f['confidence']:.0%} confidence, "
                                  f"{f['affected_pct']:.0f}% affected). Severity {risk.get('severity')}, urgency {risk.get('urgency')}.",
                        mitigation_steps=steps, escalate=escalate, escalation_reason=reason, citations=cites, follow_up=follow)
    out, by, meta = produce(state, Advisory, "Write the farmer advisory: diagnosis, mitigation steps from evidence, whether to escalate to the reeler.",
                            facts, fb, locked={"escalate": escalate and not f.get("uncertain"), "escalation_reason": reason})
    if f.get("uncertain"):  # never let formatting hide the abstention
        out, by, meta = fb(), "template", None
    elif f.get("provisional"):  # type unknown: whatever the model wrote, the question and expert confirmation must be there
        base = _provisional_advisory(f, risk, points, cites, escalate, reason)
        out = out.model_copy(update={"escalate": True, "escalation_reason": base.escalation_reason,
                                     "follow_up": [SILKWORM_DISCRIMINATOR] + [x for x in out.follow_up if x != SILKWORM_DISCRIMINATOR],
                                     "mitigation_steps": out.mitigation_steps if EXPERT_STEP in out.mitigation_steps else out.mitigation_steps + [EXPERT_STEP]})
    res = {"type": "advisory", **out.model_dump(), "structured_by": by}
    _remember(state, res["headline"])
    return _adv(res, by, meta, f"advisory by {by}; escalate={res['escalate']}")


def _provisional_advisory(f: dict, risk: dict, points: list[str], cites: list, escalate: bool, reason: str) -> Advisory:
    """Image says 'diseased' but not which disease: generic hygiene from the KB, a discriminating question, expert confirmation."""
    hygiene = [_short(p) for p in points if not p.lower().startswith(("symptoms", "cause"))][:4]
    return Advisory(headline=f"Silkworm disease detected, type unknown - expert confirmation required (priority {risk.get('priority')})",
                    diagnosis=(f"The photo shows signs of disease ({f.get('confidence', 0):.0%} confidence) but the system cannot tell which one. "
                               f"Treat the batch as infectious until an expert confirms. Severity {risk.get('severity')}, urgency {risk.get('urgency')}."),
                    mitigation_steps=hygiene + [EXPERT_STEP], escalate=True,
                    escalation_reason="Disease type unknown; every silkworm disease is infectious and spreads fast: confirm with an expert and alert your reeler.",
                    citations=cites, follow_up=[SILKWORM_DISCRIMINATOR])


def _adv(res: dict, by: str, meta: dict | None, summary: str) -> dict:
    """Node return for any advisory: attaches the agent's tool steps and the evidence it actually cited."""
    tools = {"agent": ["llm.agent_loop", "llm.advisor"], "gemini": ["llm.grounded_answer[gemini]"], "groq": ["llm.structure[groq]"],
             "groq_repaired": ["llm.structure[groq]"]}.get(by, ["template.structure"])
    out = {"advisory": res, "_tools": tools + [f"agent.{s['tool']}" for s in (meta or {}).get("steps", [])], "_summary": summary}
    if meta:
        out["rag"] = meta["rag"]
        out["_agent"] = meta["steps"]
        out["_summary"] += f"; {len(meta['steps'])} tool call(s), {meta['searches']} KB search(es)"
    return out


def _remember(state, solution: str) -> None:
    """Incident memory is updated as soon as the incident has an advisory (not only at closure),
    so a recurrence is recognised even while an earlier incident awaits approval."""
    if state.get("mode") != "incident":
        return
    with session_scope() as db:
        village = db.get(Entity, state["entity_id"]).village
    with session_scope() as db:
        parent_id = db.get(Incident, state["incident_id"]).parent_id
    remember(state["incident_id"], state["entity_id"], state.get("incident_kind", "disease"),
             (state.get("finding") or {}).get("label"), village, solution, parent_id=parent_id)


# ---------------------------------------------------------------- join + finalize
@traced("finalize")
def finalize(state):
    imp, h = state.get("supply_impact") or {}, state.get("advisory") or {}
    solution = h.get("headline") or h.get("answer") or ""
    if h.get("mitigation_steps"):
        solution += " | " + " ".join(f"{i + 1}) {s}" for i, s in enumerate(h["mitigation_steps"][:4]))
    out = state.get("outcome") or {}
    if state.get("clarify"):
        status = "needs_info"
    elif state["mode"] == "query":
        status = "answered"
    elif state.get("deal_ids"):
        if out.get("executed"):
            status = "resolved" if not out.get("unresolved") and not out.get("rejected") else "partially_resolved"
        else:
            status = "rejected" if out.get("rejected") else "failed"
    elif (state.get("supply_impact") or {}).get("cases"):
        status = "escalated"  # supply at risk but nothing could be sourced -> human follow-up
    else:
        status = "advised"
    with session_scope() as db:
        ent = db.get(Entity, state["entity_id"])
        village = ent.village
    fin = {"node": "finalize", "kind": "node", "ms": 0, "at": "", "summary": f"status={status}", "tools": []}
    save_incident({**state, "trace": state.get("trace", []) + [fin]}, status, solution=solution[:2000])
    _remember(state, solution)
    return {"status": status, "_summary": f"status={status}"}
