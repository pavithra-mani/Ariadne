"""Stock-triggered incidents: a product falling to its reorder point / safety stock opens an incident
by itself (on a stock update, or when the user asks Ariadne to fix a low product).

Raw inputs (cocoon for a reeler, leaves for a silkworm farm, yarn for a spinner) -> buy replacement
stock upstream. Finished goods (yarn, cocoon, leaves, thread) -> buyers who depend on it are
exposed; their shortfall is re-sourced from alternative suppliers, exactly as in a reported incident.
"""
import re

from app.calc.impact import buyers, exposure_for_buyer, get_inv
from app.calc.supply import stock_status
from app.db.models import Entity, Inventory
from app.db.session import session_scope
from app.graph.common import traced
from app.llm.schemas import Advisory
from app.llm.structured import structure

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


@traced("stock_monitor_agent", "specialist")
def low_stock_agent(state):
    fields, msg = state.get("fields") or {}, state.get("message", "")
    with session_scope() as db:
        me = db.get(Entity, state["entity_id"])
        product = pick_product(db, me.id, fields, msg)
        inv = get_inv(db, me.id, product)
        st = stock_status(inv)
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
               "cause": fields.get("cause_text")}
    return {"finding": finding, "incident_kind": "low_stock", "mode": "incident", "rag_query": RAG_QUERY[product],
            "assessment": {"severity_level": sev, "urgency_level": urg, "rationale": [
                f"{product} at {st.available:.0f} kg (≈{max(projected, 0):.0f} kg after the upstream loss): safety stock {st.safety_stock:.0f}, reorder point {st.reorder_point:.0f}",
                f"{max(cover_eff, 0):.1f} days of cover vs {inv.lead_time_days:.0f} days to resupply"]
            + ([fields["cause_text"], f"upstream loss will keep ≈{lost:.0f} kg from arriving"] if fields.get("cause_text") else [])},
            "_tools": ["postgres.stock", "calc.safety_stock", "calc.rop"],
            "_summary": f"{name}: {product} {st.status}, cover {st.days_of_cover:.1f} d; "
                        + (f"order {order_qty:.0f} kg" if not inv.is_finished else f"{impact['n_at_risk']}/{len(rows)} buyers at risk")}


def stock_advisory(state) -> tuple[Advisory, str]:
    f, imp, risk, rag = state["finding"], state["supply_impact"], state.get("risk") or {}, state.get("rag") or {}
    s, product = imp["stock"], f["product"]
    steps: list[str] = []
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
    return structure(Advisory, "Write a short stock advisory using the given steps in meaning.", facts, fb,
                     locked={"escalate": False, "escalation_reason": ""})
