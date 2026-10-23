"""Reeler and Spinner specialist agents: stock-driven severity/urgency and supply impact.

All figures come from calc/ + PostgreSQL. Output `finding["impact"]` has the same shape as the
farmer impact so the shared recovery pipeline can consume it (`cases`).
"""
import re

from app.calc.impact import buyers, exposure_for_buyer, get_inv, latest_target, suppliers
from app.calc.supply import stock_status
from app.db.models import Entity, Target
from app.db.session import session_scope
from app.graph.common import traced
from app.graph.profiles import COCOON_PER_YARN, HORIZON_DAYS, SEVERITY, URGENCY
from app.llm.schemas import Advisory
from app.agents.advisor import produce

REELER_KINDS = {"low_yarn_output": "low_yarn", "cocoon_shortage": "cocoon_shortage", "delivery_delay": "delay"}


def _num(rx: str, text: str, default=None):
    m = re.search(rx, text, re.I)
    return float(m.group(1)) if m else default


def infer_reeler_type(fields: dict, msg: str) -> str:
    t = fields.get("incident_type")
    if t in REELER_KINDS:
        return t
    low = msg.lower()
    if re.search(r"delay|late|stuck|transport", low):
        return "delivery_delay"
    if "cocoon" in low and re.search(r"short|low|less|not enough|scarce", low):
        return "cocoon_shortage"
    return "low_yarn_output"


def _sev_urg(shortfall: float, need: float, min_cover: float) -> tuple[int, int]:
    frac = shortfall / need if need > 0 else 0
    sev = 3 if frac >= 0.5 else 2 if frac >= 0.25 else 1 if frac > 0 else 0
    urg = 2 if min_cover <= 2 else 1 if min_cover <= 5 else 0
    return sev, urg


@traced("reeler_agent", "specialist")
def reeler_agent(state):
    if state["mode"] == "query":
        return {"finding": {"query": True}, "incident_kind": "query", "_summary": "knowledge question (no incident)"}
    fields, msg = state.get("fields") or {}, state.get("message", "")
    itype = infer_reeler_type(fields, msg)
    red = float(fields.get("reduction_pct", _num(r"(\d+(?:\.\d+)?)\s*%", msg, 30))) / 100
    days = float(fields.get("duration_days", fields.get("delay_days", _num(r"(\d+(?:\.\d+)?)\s*days?", msg, 7))))
    qty = fields.get("quantity_kg", _num(r"(\d+(?:\.\d+)?)\s*kg", msg))
    with session_scope() as db:
        me = db.get(Entity, state["entity_id"])
        yarn = stock_status(get_inv(db, me.id, "yarn"))
        cocoon_inv = get_inv(db, me.id, "cocoon")
        cocoon = stock_status(cocoon_inv)
        thr = me.daily_throughput
        spinners = buyers(db, me.id)

        # --- lost / delayed yarn over the window
        if itype == "low_yarn_output":
            lost = thr * red * days
        elif itype == "cocoon_shortage":
            cocoon_short = float(qty) if qty else cocoon_inv.daily_demand * days * 0.3
            lost = cocoon_short / COCOON_PER_YARN
        else:  # delivery_delay: delayed stock cannot serve spinners inside the window
            lost = float(qty) if qty else sum(
                (get_inv(db, s.id, "yarn").daily_demand * sh) for s, sh in spinners) * days
        deliverable = max(yarn.available + thr * days - lost, 0.0)

        # --- spinner needs and urgency-ordered re-allocation of what remains
        rows = []
        for s, share in spinners:
            sinv = get_inv(db, s.id, "yarn")
            st = stock_status(sinv)
            rows.append({"entity_id": s.id, "name": s.name, "village": s.village, "kind": s.kind,
                         "product": "yarn", "need": round(sinv.daily_demand * share * days, 1),
                         "cover_days": round(st.days_of_cover, 1), "share": share})
        total_need = sum(r["need"] for r in rows)
        remaining = deliverable
        for r in sorted(rows, key=lambda r: r["cover_days"]):  # most urgent spinner first
            r["allocated"] = round(min(r["need"], remaining), 1)
            remaining -= r["allocated"]
            raw_short = r["need"] - r["allocated"]
            ex = exposure_for_buyer(db, db.get(Entity, r["entity_id"]), "yarn", raw_short)
            r.update({"exposure_qty": r["need"], "lost_exposure": round(raw_short, 1), "shortfall": ex["shortfall"],
                      "buffer": ex["buffer"], "at_risk": ex["shortfall"] > 0})
        total_short = round(sum(r["shortfall"] for r in rows), 1)
        cases = []  # spinners short of yarn get their OWN incident (graph/propagate.py), not a case here
        if itype == "cocoon_shortage":
            cases.append({"buyer_id": me.id, "buyer_name": me.name, "product": "cocoon",
                          "qty": round(cocoon_short, 1), "direction": "upstream",
                          "exclude_ids": [], "deadline_days": round(cocoon.days_of_cover, 1)})
        stranded = 0.0
        if itype == "low_yarn_output":  # input cocoons idle at reduced capacity -> sell downstream before they degrade
            reduced_use = thr * (1 - red) * COCOON_PER_YARN
            stranded = max(cocoon.available - reduced_use * cocoon.degrades_in_days, 0.0)
            stranded = round(stranded, 1) if stranded > cocoon.safety_stock else 0.0
            if stranded > 0:
                cases.append({"buyer_id": me.id, "buyer_name": me.name, "product": "cocoon", "qty": stranded,
                              "direction": "downstream", "exclude_ids": [me.id],
                              "deadline_days": round(cocoon.degrades_in_days, 1)})
        n_spinners = len(rows)
    sev, urg = _sev_urg(total_short, total_need, min([r["cover_days"] for r in rows if r["shortfall"] > 0] or [99]))
    impact = {
        "product": "yarn", "horizon_days": days, "lost_qty": round(lost, 1), "deliverable": round(deliverable, 1),
        "total_need": round(total_need, 1), "affected": rows, "n_affected": n_spinners,
        "n_at_risk": len([r for r in rows if r["at_risk"]]), "total_shortfall": total_short,
        "at_risk": bool(cases) or any(r["at_risk"] for r in rows), "stranded_cocoon": stranded, "cases": cases, "escalate": False,
        "direction": "upstream", "incident_type": itype,
    }
    queries = {"low_yarn_output": "reasons for low yarn output reeling raising falling yarn stock",
               "cocoon_shortage": "cocoon supply shortage alternative cocoon source reeling",
               "delivery_delay": "delivery delay notify spinner re-allocate yarn alternative source"}
    loss_fraction = round(min(lost / max(yarn.available + thr * days, 1.0), 1.0), 3)  # share of its yarn the reeler cannot deliver
    finding = {"incident_type": itype, "window_days": days, "loss_fraction": loss_fraction,
               "reduction_pct": round(red * 100) if itype == "low_yarn_output" else None,
               "impact": impact, "label": itype, "uncertain": False, "confidence": 1.0, "source": "stock_calculations"}
    return {"finding": finding, "rag_query": queries[itype], "incident_kind": REELER_KINDS[itype], "mode": "incident",
            "assessment": {"severity_level": sev, "urgency_level": urg, "rationale": [
                f"{total_short:.0f} kg of {total_need:.0f} kg spinner demand unmet over {days:.0f} days",
                f"{impact['n_at_risk']} of {n_spinners} spinners at risk"]},
            "_tools": ["postgres.stock", "calc.safety_stock", "calc.reallocate"],
            "_summary": f"{itype}: shortfall {total_short} kg, {impact['n_at_risk']}/{n_spinners} spinners at risk, {len(cases)} recovery case(s)"}


def _parse_spinner(fields: dict, msg: str, current: float) -> tuple[float, int, bool]:
    explicit = fields.get("target_qty") or _num(r"(\d+(?:\.\d+)?)\s*kg", msg)
    horizon = int(fields.get("horizon_days") or _num(r"(\d+)\s*days?", msg, 14))
    if explicit:
        return float(explicit), horizon, True
    pct = fields.get("surge_pct") or _num(r"(\d+(?:\.\d+)?)\s*%", msg, 50)
    return round(current * (1 + float(pct) / 100), 1), horizon, False


@traced("spinner_agent", "specialist")
def spinner_agent(state):
    if state["mode"] == "query":
        return {"finding": {"query": True}, "incident_kind": "query", "_summary": "knowledge question (no incident)"}
    fields, msg = state.get("fields") or {}, state.get("message", "")
    if fields.get("incident_type") == "yarn_shortfall":
        return _spinner_shortfall(state, fields)
    with session_scope() as db:
        me = db.get(Entity, state["entity_id"])
        t = latest_target(db, me.id)
        base = t.target_qty if t else me.daily_throughput * HORIZON_DAYS
        target, horizon, explicit = _parse_spinner(fields, msg, base)
        yarn = stock_status(get_inv(db, me.id, "yarn"))
        own_buffer = max(yarn.available - yarn.safety_stock, 0.0)
        linked = suppliers(db, me.id)
        linked_rows, supply = [], 0.0
        for r, share in linked:
            rst = stock_status(get_inv(db, r.id, "yarn"))
            spare = max(r.capacity_per_day - r.daily_throughput, 0.0) * horizon
            can = round(rst.sellable + spare, 1)
            supply += can
            linked_rows.append({"entity_id": r.id, "name": r.name, "village": r.village, "kind": r.kind,
                                "product": "yarn", "sellable": round(rst.sellable, 1),
                                "spare_capacity": round(spare, 1), "can_supply": can,
                                "exposure_qty": 0, "shortfall": 0, "cover_days": 0, "at_risk": False})
        gap = round(max(target - own_buffer - supply, 0.0), 1)
        db.add(Target(entity_id=me.id, product="yarn", target_qty=target, horizon_days=horizon))
        linked_ids = [r.id for r, _ in linked]
        cover = yarn.days_of_cover
        n_lk = len(linked_rows)
    frac = gap / target if target else 0
    sev = 3 if frac >= 0.5 else 2 if frac >= 0.25 else 1 if gap > 0 else 0
    urg = 2 if horizon <= 7 else 1 if horizon <= 14 else 0
    if cover < 5 and gap > 0:
        urg = min(urg + 1, 2)
    cases = [{"buyer_id": state["entity_id"], "buyer_name": me.name, "product": "yarn", "qty": gap,
              "direction": "upstream", "exclude_ids": linked_ids, "deadline_days": float(horizon)}] if gap > 0 else []
    impact = {"product": "yarn", "horizon_days": horizon, "target": target, "own_buffer": round(own_buffer, 1),
              "linked_supply": round(supply, 1), "gap": gap, "affected": linked_rows, "n_affected": n_lk,
              "n_at_risk": 0, "total_shortfall": gap, "at_risk": gap > 0, "cases": cases, "escalate": False,
              "direction": "upstream", "incident_type": "demand_surge"}
    finding = {"incident_type": "demand_surge", "label": "demand_surge", "target_qty": target, "window_days": horizon,
               "impact": impact, "uncertain": False, "confidence": 1.0, "source": "stock_calculations"}
    return {"finding": finding, "incident_kind": "demand_surge", "mode": "incident",
            "rag_query": "demand surge target gap alternative reelers spinner stock planning",
            "assessment": {"severity_level": sev, "urgency_level": urg, "rationale": [
                f"target {target:.0f} kg in {horizon} days vs own buffer {own_buffer:.0f} kg + linked reelers {supply:.0f} kg",
                f"gap {gap:.0f} kg"]},
            "_tools": ["postgres.stock", "calc.capacity", "calc.gap"],
            "_summary": f"target {target:.0f} kg/{horizon}d; gap {gap} kg; {len(cases)} recovery case(s)"}


def _spinner_shortfall(state, fields):
    """Cascaded from a reeler incident: a known yarn shortfall (kg) the spinner must source elsewhere."""
    gap, horizon = float(fields["shortfall_kg"]), int(fields.get("horizon_days", 14))
    with session_scope() as db:
        me = db.get(Entity, state["entity_id"])
        yarn = stock_status(get_inv(db, me.id, "yarn"))
        # the reeler that failed is the parent incident's entity: exclude it and keep the rest
        parent_entity = None
        from app.db.models import Incident
        inc = db.get(Incident, state["incident_id"])
        if inc and inc.parent_id:
            parent_entity = db.get(Incident, inc.parent_id).entity_id
        excl = [parent_entity] if parent_entity else []
        name, cover = me.name, yarn.days_of_cover
    frac = 1.0 if gap > 0 else 0
    sev = 2 if gap > yarn.sellable else 1
    urg = 2 if cover < 5 else 1
    case = {"buyer_id": state["entity_id"], "buyer_name": name, "product": "yarn", "qty": gap,
            "direction": "upstream", "exclude_ids": excl, "deadline_days": float(horizon)}
    impact = {"product": "yarn", "horizon_days": horizon, "target": gap, "own_buffer": round(max(yarn.available - yarn.safety_stock, 0), 1),
              "linked_supply": 0.0, "gap": gap, "affected": [], "n_affected": 0, "n_at_risk": 0, "total_shortfall": gap,
              "at_risk": True, "cases": [case], "escalate": False, "direction": "upstream", "incident_type": "demand_surge"}
    finding = {"incident_type": "demand_surge", "label": "yarn_shortfall", "target_qty": gap, "window_days": horizon,
               "impact": impact, "uncertain": False, "confidence": 1.0, "source": "cascade"}
    return {"finding": finding, "incident_kind": "yarn_shortfall", "mode": "incident",
            "rag_query": "yarn shortfall alternative reelers raising stock", "assessment": {
                "severity_level": sev, "urgency_level": urg,
                "rationale": [f"upstream reeler cannot deliver {gap:.0f} kg yarn", f"stock cover {cover:.1f} days"]},
            "_tools": ["postgres.stock"], "_summary": f"cascaded yarn shortfall {gap:.0f} kg; 1 recovery case"}


# ------------------------------------------------------------------ advisory for ops roles
def ops_advisory(state):
    f, imp, risk, rag = state["finding"], state["supply_impact"], state.get("risk") or {}, state.get("rag") or {}
    points = [p["text"] for p in rag.get("points", [])][:3]
    steps: list[str] = []
    if f["incident_type"] == "demand_surge":
        if imp["gap"] <= 0:
            steps.append(f"Target of {imp['target']:.0f} kg can be met: own buffer {imp['own_buffer']:.0f} kg plus "
                         f"{imp['linked_supply']:.0f} kg available from your reelers. Place orders with them.")
        else:
            steps.append(f"Gap of {imp['gap']:.0f} kg after counting your stock and your reelers' spare supply "
                         f"({imp['linked_supply']:.0f} kg). Ariadne will search alternative reelers.")
    else:
        for r in sorted(imp["affected"], key=lambda r: r["cover_days"]):
            if r["need"] > 0:
                steps.append(f"Allocate {r['allocated']:.0f} of {r['need']:.0f} kg to {r['name']} "
                             f"(cover {r['cover_days']:.1f} days)" + (f" - shortfall {r['shortfall']:.0f} kg" if r["shortfall"] else "") + ".")
        if imp["total_shortfall"] > 0:
            steps.append(f"Shortfall of {imp['total_shortfall']:.0f} kg: Ariadne will search alternative sources and propose a deal for approval.")
        if imp.get("stranded_cocoon"):
            steps.append(f"{imp['stranded_cocoon']:.0f} kg of cocoons will degrade before use at reduced capacity: sell to another reeler.")
        if f["incident_type"] == "delivery_delay":
            steps.append("Notify affected spinners now with an honest revised delivery date.")
    steps += [s[:200] for s in points[:2]]
    headline = {"low_yarn_output": "Low yarn output", "cocoon_shortage": "Cocoon supply shortage",
                "delivery_delay": "Delivery delay", "demand_surge": "Demand surge"}[f["incident_type"]] + \
               f" - priority {risk.get('priority')}"
    diagnosis = (f"{imp['n_at_risk']} of {imp['n_affected']} buyers face a shortfall (total {imp['total_shortfall']:.0f} kg). "
                 if f["incident_type"] != "demand_surge" else
                 f"Target {imp['target']:.0f} kg in {imp['horizon_days']} days; gap {imp['gap']:.0f} kg. ") + \
                f"Severity {risk.get('severity')}, urgency {risk.get('urgency')}."
    facts = {"incident": f["incident_type"], "headline": headline, "diagnosis": diagnosis, "steps": steps,
             "risk": risk, "evidence": rag.get("points", [])}
    fb = lambda: Advisory(headline=headline, diagnosis=diagnosis, mitigation_steps=steps,
                          citations=sorted({p["citation"] for p in rag.get("points", [])}))
    return produce(state, Advisory, "Write the operational advisory using the given steps verbatim in meaning.", facts, fb,
                   locked={"escalate": False, "escalation_reason": ""})
