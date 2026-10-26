"""Stock-triggered incidents: a product falling to its reorder point / safety stock opens an incident
by itself (on a stock update, or when the user asks Ariadne to fix a low product).

Raw inputs (cocoon for a reeler, leaves for a silkworm farm, yarn for a spinner) -> buy replacement
stock upstream. Finished goods (yarn, cocoon, leaves, thread) -> buyers who depend on it are
exposed; their shortfall is re-sourced from alternative suppliers, exactly as in a reported incident.
"""
import re

from app.calc.impact import buyers, exposure_for_buyer, get_inv
from app.calc.supply import stock_status, surplus_qty
from app.db.models import Entity, Inventory
from app.db.session import session_scope
from app.graph.common import traced
from app.llm.schemas import Advisory
from app.agents.advisor import produce

LOW_STOCK_RX = re.compile(r"(stock|inventory).{0,40}(low|critical|running out|run out|depleted|empty|finished)|"
                          r"(low|critical|running out|out of).{0,40}(stock|inventory)", re.I)
PRODUCT_WORDS = {"cocoon": "cocoon", "cocoons": "cocoon", "yarn": "yarn", "leaves": "leaves", "leaf": "leaves", "thread": "thread"}
RAG_QUERY = {"cocoon": "cocoon storage stock planning safety stock", "leaves": "mulberry leaf freshness storage feeding schedule",
             "yarn": "raise falling yarn stock reeling", "thread": "twisting spinner stock planning safety stock"}
HORIZON = 7


def looks_like_low_stock(msg: str) -> bool:
    return bool(LOW_STOCK_RX.search(msg or ""))


def pick_product(db, entity_id: int, fields: dict, msg: str) -> str | None:
    invs = {i.product: i for i in db.query(Inventory).filter_by(entity_id=entity_id)}
    if fields.get("product") in invs:
        return fields["product"]
    for w in re.findall(r"[a-z]+", (msg or "").lower()):
        if PRODUCT_WORDS.get(w) in invs:
            return PRODUCT_WORDS[w]
    worst = sorted(invs.values(), key=lambda i: stock_status(i).days_of_cover)  # lowest cover first
    return worst[0].product if worst else None


def apply_stated_stock(db, me: Entity, product: str, kg: float) -> dict | None:
    """The owner told Ariadne how much they really hold: record it as an audited stock correction
    (same authority as the dashboard's Update stock form)."""
    from app.db.models import AuditLog, Ledger
    inv = get_inv(db, me.id, product)
    if inv is None or abs(inv.on_hand - kg) <= max(0.1 * inv.on_hand, 5):
        return None
    before = inv.on_hand
    inv.on_hand = max(kg, 0.0)
    db.add(Ledger(entity_id=me.id, product=product, delta_qty=inv.on_hand - before, memo="stock stated in chat"))
    db.add(AuditLog(actor=f"entity:{me.id}", action="stock_stated_in_chat", ref=product, details={"before": before, "after": inv.on_hand}))
    return {"product": product, "from": round(before, 1), "to": round(inv.on_hand, 1)}


@traced("stock_monitor_agent", "specialist")
def low_stock_agent(state):
    fields, msg = state.get("fields") or {}, state.get("message", "")
    corrected = None
    with session_scope() as db:
        me = db.get(Entity, state["entity_id"])
        product = pick_product(db, me.id, fields, msg)
        if fields.get("stock_now_kg") is not None:
            corrected = apply_stated_stock(db, me, product, float(fields["stock_now_kg"]))
        inv = get_inv(db, me.id, product)
        st = stock_status(inv)
        if fields.get("incident_type") == "surplus":
            return _surplus_result(me, inv, st, product, float(fields.get("qty") or surplus_qty(inv, st)))
        target = st.reorder_point + inv.daily_demand * 3  # order-up-to level: ROP plus three days of use
        lost = float(fields.get("lost_exposure") or 0.0)  # stock an upstream problem will keep from arriving
        projected = st.available - lost
        rows, cases, order_qty = [], [], 0.0
        if not inv.is_finished:
            order_qty = round(max(target - projected, 0.0), 1)
            if order_qty >= 1:
                cases.append({"buyer_id": me.id, "buyer_name": me.name, "product": product, "qty": order_qty,
                              "direction": "upstream", "exclude_ids": [fields["cause_entity"]] if fields.get("cause_entity") else [],
                              "deadline_days": round(st.days_of_cover, 1)})
        else:  # buyers depending on this finished product are exposed; each gets its own incident (propagate)
            for b, share in buyers(db, me.id):
                exposure = inv.daily_demand * share * HORIZON
                allocated = min(exposure, st.available * share)
                ex = exposure_for_buyer(db, b, product, exposure - allocated)
                rows.append({"entity_id": b.id, "name": b.name, "village": b.village, "kind": b.kind, "product": product,
                             "exposure_qty": round(exposure, 1), "need": round(exposure, 1), "allocated": round(allocated, 1),
                             "lost_exposure": round(exposure - allocated, 1), "cover_days": ex["cover_days"],
                             "shortfall": ex["shortfall"], "buffer": ex["buffer"], "at_risk": ex["shortfall"] > 0})
        stock = st.dict()
        name = me.name
    eff = projected  # stock after any upstream loss: rate the situation the buyer is heading for
    sev = 3 if eff <= 0.5 * st.safety_stock else 2 if eff <= st.safety_stock else 1 if (eff < st.reorder_point or st.status == "degrading") else 0
    cover_eff = eff / inv.daily_demand if inv.daily_demand > 0 else 999.0
    urg = 2 if cover_eff <= inv.lead_time_days else 1 if cover_eff <= 2 * inv.lead_time_days else 0
    impact = {"product": product, "horizon_days": HORIZON, "lost_qty": 0.0, "affected": rows, "n_affected": len(rows),
              "n_at_risk": len([r for r in rows if r["at_risk"]]), "total_shortfall": round(sum(r["shortfall"] for r in rows) + order_qty, 1), "lost_exposure": lost,
              "at_risk": bool(cases) or any(r["at_risk"] for r in rows), "cases": cases, "escalate": False, "direction": "upstream", "incident_type": "low_stock",
              "stock": stock, "order_qty": order_qty, "target_level": round(target, 1), "finished": inv.is_finished}
    finding = {"incident_type": "low_stock", "label": "low_stock", "product": product, "confidence": 1.0, "uncertain": False,
               "source": "stock_calculations", "status": st.status, "impact": impact,
               "cause": fields.get("cause_text"), "stock_corrected": corrected}
    return {"finding": finding, "incident_kind": "low_stock", "mode": "incident", "rag_query": RAG_QUERY[product],
            "assessment": {"severity_level": sev, "urgency_level": urg, "rationale": [
                f"{product} at {st.available:.0f} kg (≈{max(projected, 0):.0f} kg after the upstream loss): safety stock {st.safety_stock:.0f}, reorder point {st.reorder_point:.0f}",
                f"{max(cover_eff, 0):.1f} days of cover vs {inv.lead_time_days:.0f} days to resupply"]
            + ([fields["cause_text"], f"upstream loss will keep ≈{lost:.0f} kg from arriving"] if fields.get("cause_text") else [])
            + ([f"Your {corrected['product']} stock record was updated from {corrected['from']:.0f} to {corrected['to']:.0f} kg as you stated"] if corrected else [])},
            "_tools": ["postgres.stock", "calc.safety_stock", "calc.rop"],
            "_summary": f"{name}: {product} {st.status}, cover {st.days_of_cover:.1f} d; "
                        + (f"order {order_qty:.0f} kg" if not inv.is_finished else f"{impact['n_at_risk']}/{len(rows)} buyers at risk")}


def _surplus_result(me: Entity, inv, st, product: str, qty: float) -> dict:
    """Finished stock that will not be used in time: look for buyers (outbound direction) before it spoils."""
    days = st.degrades_in_days
    cases = [{"buyer_id": me.id, "buyer_name": me.name, "product": product, "qty": round(qty, 1), "direction": "outbound",
              "exclude_ids": [], "deadline_days": round(days, 1)}] if qty > 0.5 else []
    impact = {"product": product, "horizon_days": HORIZON, "lost_qty": 0.0, "affected": [], "n_affected": 0, "n_at_risk": 0,
              "total_shortfall": 0.0, "lost_exposure": 0.0, "at_risk": bool(cases), "cases": cases, "escalate": False,
              "direction": "outbound", "incident_type": "surplus", "stock": st.dict(), "order_qty": 0.0,
              "target_level": 0.0, "finished": True, "surplus_qty": round(qty, 1)}
    finding = {"incident_type": "surplus", "label": "surplus", "product": product, "confidence": 1.0, "uncertain": False,
               "source": "stock_calculations", "status": st.status, "impact": impact, "cause": None, "stock_corrected": None}
    return {"finding": finding, "incident_kind": "surplus", "mode": "incident", "rag_query": RAG_QUERY[product],
            "assessment": {"severity_level": 1 if days <= 3 else 0, "urgency_level": 2 if days <= 2 else 1 if days <= 5 else 0,
                           "rationale": [f"{qty:.0f} kg of {product} will not be used before it degrades (in {days:.0f} days) or far exceeds demand",
                                         f"{st.days_of_cover:.0f} days of cover at the current draw"]},
            "_tools": ["postgres.stock", "calc.surplus"], "_summary": f"{me.name}: {qty:.0f} kg {product} surplus, {days:.0f} days to degrade"}


def stock_advisory(state):
    f, imp, risk, rag = state["finding"], state["supply_impact"], state.get("risk") or {}, state.get("rag") or {}
    s, product = imp["stock"], f["product"]
    steps: list[str] = []
    if f["incident_type"] == "surplus":
        steps = [f"About {imp['surplus_qty']:.0f} kg of your {product} will not be used before it degrades or far exceeds demand.",
                 "Ariadne is offering it to buyers who need it, nearest first. You approve each sale, and the buyer must approve too.",
                 "Until a sale is agreed, keep the stock cool and dry and sell the oldest first."] + [p["text"][:200] for p in rag.get("points", [])[:1]]
        headline = f"{imp['surplus_qty']:.0f} kg of {product} may go to waste"
        diag = (f"{s['on_hand']:.0f} kg on hand, {s['days_of_cover']:.1f} days of cover, degrades in {s['degrades_in_days']:.0f} days. "
                f"Severity {risk.get('severity')}, urgency {risk.get('urgency')}.")
        fb = lambda: Advisory(headline=f"{headline} - priority {risk.get('priority')}", diagnosis=diag, mitigation_steps=steps,
                              citations=sorted({p["citation"] for p in rag.get("points", [])}))
        return produce(state, Advisory, "Write a short advisory for a seller with surplus stock using the given steps in meaning.",
                       {"headline": headline, "diagnosis": diag, "steps": steps, "risk": risk, "evidence": rag.get("points", [])}, fb,
                       locked={"escalate": False, "escalation_reason": ""})
    if f.get("stock_corrected"):
        c = f["stock_corrected"]
        steps.append(f"As you said, your {c['product']} stock record was updated from {c['from']:.0f} kg to {c['to']:.0f} kg (logged in your ledger).")
    if imp["finished"]:
        for r in sorted(imp["affected"], key=lambda r: r["cover_days"]):
            steps.append(f"Serve {r['name']} first-come by urgency: it needs {r['need']:.0f} kg this week, you can allocate {r['allocated']:.0f} kg"
                         + (f" (short by {r['shortfall']:.0f} kg)." if r["shortfall"] else "."))
        if imp["total_shortfall"] > 0:
            steps.append(f"Ariadne is searching alternative suppliers for the {imp['total_shortfall']:.0f} kg your buyers cannot cover.")
        steps.append(f"Raise output of {product} within capacity and tell buyers an honest delivery date.")
    elif imp["order_qty"] >= 1:
        if f.get("cause"):
            steps.append(f"{f['cause']} About {imp['lost_exposure']:.0f} kg will not arrive, which would take you below your reorder point.")
        steps.append(f"Restock to about {imp['target_level']:.0f} kg: buy {imp['order_qty']:.0f} kg of {product}. Ariadne is now searching nearby suppliers, "
                     "routing pick-ups and will propose purchases for your approval.")
    else:
        steps.append("Stock is above the reorder point: no purchase is needed.")
    steps += [p["text"][:200] for p in rag.get("points", [])[:2]]
    headline = f"{product.capitalize()} stock {s['status'].replace('degrading', 'degrading soon')}"
    diag = (f"{s['on_hand']:.0f} kg on hand ({s['available']:.0f} available), {s['days_of_cover']:.1f} days of cover. "
            f"Safety stock {s['safety_stock']:.0f} kg, reorder point {s['reorder_point']:.0f} kg. "
            f"Severity {risk.get('severity')}, urgency {risk.get('urgency')}.")
    facts = {"headline": headline, "diagnosis": diag, "steps": steps, "risk": risk, "evidence": rag.get("points", [])}
    fb = lambda: Advisory(headline=f"{headline} - priority {risk.get('priority')}", diagnosis=diag, mitigation_steps=steps,
                          citations=sorted({p["citation"] for p in rag.get("points", [])}))
    return produce(state, Advisory, "Write a short stock advisory using the given steps in meaning.", facts, fb,
                   locked={"escalate": False, "escalation_reason": ""})
