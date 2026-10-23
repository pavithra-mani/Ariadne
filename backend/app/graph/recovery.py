"""Shared supply-chain recovery pipeline (Fig. 1, bottom band):
 1 Inventory DB check -> 2 Alternative Sources (bounded retry) -> 3 Routing/OR-Tools ->
 4 HITL approval -> 5 Deal / rerouting (ledger) -> 6 Notification.
Only the search direction differs between farmer, reeler and spinner incidents."""
from datetime import date

from langgraph.types import interrupt

from app.agents.planner import choose_strategies, order_candidates
from app.calc.impact import OUTPUT_PRODUCT, get_inv
from app.calc.supply import stock_status
from app.config import settings
from app.db.models import AuditLog, Deal, Entity, Inventory, Ledger, Notification
from app.db.session import session_scope
from app.graph.common import save_incident, traced
from app.graph.profiles import COCOON_PER_YARN
from app.routing.provider import road_km
from app.routing.vrp import MAX_TRANSIT_HOURS, Stop, plan_route

SUPPLIER_KIND = {"leaves": "mulberry_farm", "cocoon": "silkworm_farm", "yarn": "reeler"}
RADII_KM = [15, 30, 50, 80, 150]  # search k uses RADII_KM[k-1]: nearer sources first, widen on failure
TRANSPORT_RATE = {"leaves": 0.05, "cocoon": 0.3, "yarn": 1.0}  # INR per kg-km, used only for ranking
DEAL_TYPE = {("mulberry_farm", "silkworm_farm"): "farmer_farmer", ("silkworm_farm", "reeler"): "farmer_reeler",
             ("reeler", "spinner"): "reeler_spinner", ("reeler", "reeler"): "reeler_reeler"}


def _loc(e: Entity) -> tuple[float, float]:
    return (e.lat, e.lon)


# ------------------------------------------------------------------ gate
def recovery_gate(state) -> str:
    imp = state.get("supply_impact") or {}
    f = state.get("finding") or {}
    if state.get("mode") == "incident" and imp.get("cases") and not f.get("uncertain"):
        return "inventory_check"
    return "finalize"


# ------------------------------------------------------------------ 1 inventory check
@traced("inventory_check", "recovery")
def inventory_check(state):
    cases = []
    with session_scope() as db:
        for i, c in enumerate(state["supply_impact"]["cases"]):
            subj = db.get(Entity, c["buyer_id"])
            inv = get_inv(db, subj.id, c["product"])
            st = stock_status(inv) if inv else None
            case = {**c, "idx": i, "status": "open", "qty": round(c["qty"], 1), "covered": 0.0,
                    "subject_available": round(st.available, 1) if st else 0.0,
                    "subject_sellable": round(st.sellable, 1) if st else 0.0, "attempts": []}
            if c["direction"] == "downstream":  # can only offer what is really in stock
                case["qty"] = round(min(case["qty"], case["subject_available"]), 1)
            if case["qty"] <= 0.5:
                case["status"] = "no_need"
            cases.append(case)
    # planning agent: pick a sourcing strategy per case from real candidate statistics
    stats = {}
    with session_scope() as db:
        for c in cases:
            if c["status"] != "open":
                continue
            cands = find_candidates(db, c, RADII_KM[-1], {})
            stats[c["idx"]] = {"candidates_within_150km": len(cands), "nearest_km": min((x["distance_km"] for x in cands), default=None),
                               "cheapest_price_per_kg": min((x["unit_price"] for x in cands), default=None),
                               "largest_offer_kg": max((x["offer"] for x in cands), default=None),
                               "total_offered_kg": round(sum(x["offer"] for x in cands), 1),
                               "buyer_balance": round(db.get(Entity, c["buyer_id"]).balance)}
    plan = choose_strategies(cases, stats)
    for c in cases:
        c["strategy"], c["strategy_reason"] = plan[c["idx"]]
    open_n = len([c for c in cases if c["status"] == "open"])
    llm_planned = any(r != "default price/distance balance" for _, r in plan.values())
    return {"cases": cases, "search_count": 0, "plans": [], "_tools": ["postgres.stock"] + (["llm.planner"] if llm_planned else []),
            "_summary": f"{open_n} open recovery case(s) of {len(cases)}; strategy: "
                        + ", ".join(f"#{c['idx']} {c['strategy']}" for c in cases if c["status"] == "open")}


# ------------------------------------------------------------------ 2 alternative sources
def find_candidates(db, case: dict, radius: float, taken: dict) -> list[dict]:
    subj = db.get(Entity, case["buyer_id"])
    product, direction = case["product"], case["direction"]
    out = []
    if direction == "upstream":
        pool = db.query(Entity).filter(Entity.kind == SUPPLIER_KIND[product], Entity.active.is_(True)).all()
    else:  # downstream: other buyers of this product (same tier as the subject)
        pool = db.query(Entity).filter(Entity.kind == subj.kind, Entity.active.is_(True)).all()
    for e in pool:
        if e.id == subj.id or e.id in case.get("exclude_ids", []):
            continue
        km = road_km(_loc(subj), _loc(e))
        if km > radius:
            continue
        if direction == "upstream":
            inv = get_inv(db, e.id, product)
            if not inv or not inv.is_finished:
                continue
            offer = stock_status(inv).sellable - taken.get((e.id, product), 0.0)
            price = inv.unit_price
        else:
            spare_yarn = max(e.capacity_per_day - e.daily_throughput, 0.0)
            offer = spare_yarn * COCOON_PER_YARN * max(case.get("deadline_days", 1), 1) - taken.get((e.id, product), 0.0)
            ref = get_inv(db, subj.id, product)
            price = ref.unit_price * 0.95 if ref else 0.0  # resale slightly under market
        if offer < 1:
            continue
        out.append({"entity_id": e.id, "name": e.name, "kind": e.kind, "village": e.village, "lat": e.lat,
                    "lon": e.lon, "distance_km": round(km, 1), "offer": round(offer, 1), "unit_price": price,
                    "score": price + km * TRANSPORT_RATE.get(product, 0.1)})
    return sorted(out, key=lambda c: c["score"])


def select(candidates: list[dict], qty: float) -> list[dict]:
    chosen, left = [], qty
    for c in candidates:
        if left <= 0.5:
            break
        take = round(min(c["offer"], left), 1)
        chosen.append({**c, "take": take})
        left -= take
    return chosen


@traced("alternative_sources", "recovery")
def alt_sources(state):
    k = state.get("search_count", 0) + 1
    radius = 0
    cases = [dict(c) for c in state["cases"]]
    taken: dict = {}
    for c in cases:  # stock already promised to resolved cases in this run
        for p in c.get("best_plan", {}).get("selection", []) if c["status"] == "resolved" else []:
            taken[(p["entity_id"], c["product"])] = taken.get((p["entity_id"], c["product"]), 0) + p["take"]
    found = 0
    with session_scope() as db:
        for c in cases:
            if c["status"] != "open" or c.get("exhausted"):
                continue
            # widen the ring until it reveals a *new* candidate (a search is never spent on an identical set)
            prev_n, idx = c.get("prev_n", 0), c.get("radius_idx", -1) + 1
            while True:
                cands = find_candidates(db, c, RADII_KM[idx], taken)
                if len(cands) > prev_n or idx == len(RADII_KM) - 1:
                    break
                idx += 1
            if len(cands) <= prev_n:  # whole region exhausted, nothing new to try
                c["exhausted"] = True
                continue
            c["radius_idx"], c["prev_n"] = idx, len(cands)
            sel = select(order_candidates(cands, c.get("strategy")), c["qty"])
            c["current"] = {"attempt": k, "radius_km": RADII_KM[idx], "n_candidates": len(cands), "selection": sel,
                            "covered": round(sum(s["take"] for s in sel), 1)}
            radius = RADII_KM[idx]
            found += len(sel)
    return {"cases": cases, "search_count": k, "_tools": ["postgres.stock", "geo.distance"],
            "_summary": (f"search {k}/{settings.max_searches}: radius {radius} km, {found} source(s) selected" if radius
                         else f"search {k}/{settings.max_searches}: region exhausted, no new candidates")}


# ------------------------------------------------------------------ 3 routing
@traced("routing_ortools", "recovery")
def routing(state):
    cases = [dict(c) for c in state["cases"]]
    resolved_now = 0
    with session_scope() as db:
        for c in cases:
            cur = c.get("current")
            if c["status"] != "open" or not cur:
                continue
            subj = db.get(Entity, c["buyer_id"])
            depot = db.get(Entity, subj.warehouse_id) if (subj.warehouse_id and c["direction"] == "upstream") else subj
            sel = cur["selection"]
            stops = [Stop(s["entity_id"], s["name"], s["lat"], s["lon"], s["take"]) for s in sel]
            if c["direction"] == "upstream":
                plan = plan_route(_loc(depot), _loc(subj), stops, c["product"])
            else:  # deliver from the stranded stock back to a return point
                plan = plan_route(_loc(subj), _loc(subj), stops, c["product"])
            served_qty = round(sum(plan["served"].values()), 1)
            attempt = {**cur, "routes": plan["routes"], "served": plan["served"], "dropped": plan["dropped"],
                       "total_km": plan["total_km"], "total_min": plan["total_min"], "transport_cost": plan["cost"],
                       "covered_routed": served_qty, "feasible": plan["feasible"],
                       "depot": depot.name, "max_transit_min": plan.get("max_transit_min")}
            c["attempts"] = c["attempts"] + [{k: attempt[k] for k in ("attempt", "radius_km", "n_candidates",
                                                                       "covered_routed", "feasible", "total_km")}]
            best = c.get("best_plan")
            if not best or attempt["covered_routed"] > best["covered_routed"] + 0.5:
                c["best_plan"] = attempt
            if attempt["feasible"] and attempt["covered_routed"] >= c["qty"] - 0.5:
                c["status"] = "resolved"
                resolved_now += 1
            c["covered"] = c["best_plan"]["covered_routed"]
            c.pop("current", None)
    open_left = len([c for c in cases if c["status"] == "open"])
    return {"cases": cases, "_tools": ["ortools.vrp"],
            "_summary": f"{resolved_now} case(s) routed & covered, {open_left} still open"}


def after_routing(state) -> str:
    still_open = any(c["status"] == "open" and not c.get("exhausted") for c in state["cases"])
    if still_open and state.get("search_count", 0) < settings.max_searches:
        return "alt_sources"
    return "propose"


# ------------------------------------------------------------------ build proposals (pending deals)
@traced("propose_deals", "recovery")
def propose(state):
    cases, deal_ids, unresolved = [dict(c) for c in state["cases"]], [], []
    with session_scope() as db:
        for c in cases:
            if c["status"] == "no_need":
                continue
            best = c.get("best_plan")
            if c["status"] == "open":
                c["status"] = "partial" if best and best["covered_routed"] > 0 else "unresolved"
            if not best or best["covered_routed"] <= 0:
                unresolved.append({"buyer_id": c["buyer_id"], "buyer_name": c["buyer_name"], "product": c["product"],
                                   "qty": c["qty"], "reason": f"no source found within {state.get('search_count', 0)} searches"})
                continue
            subj = db.get(Entity, c["buyer_id"])
            route_by_src = {}
            for r in best["routes"]:
                for s in r["stops"]:
                    route_by_src.setdefault(s["entity_id"], []).append(r["vehicle"])
            total_served = sum(best["served"].values()) or 1
            c["deals"] = []
            for s in best["selection"]:
                qty = best["served"].get(s["entity_id"], best["served"].get(str(s["entity_id"]), 0))
                if qty <= 0:
                    continue
                other = db.get(Entity, s["entity_id"])
                seller, buyer = (other, subj) if c["direction"] == "upstream" else (subj, other)
                share = qty / total_served
                d = Deal(incident_id=state["incident_id"], deal_type=DEAL_TYPE.get((seller.kind, buyer.kind), f"{seller.kind}_{buyer.kind}"),
                         seller_id=seller.id, buyer_id=buyer.id, approver_id=subj.id, product=c["product"], quantity=qty,
                         unit_price=round(s["unit_price"], 2), transport_cost=round(best["transport_cost"] * share, 2),
                         route={"depot": best["depot"], "vehicles": sorted(set(route_by_src.get(s["entity_id"], []))),
                                "routes": best["routes"], "distance_km": best["total_km"], "duration_min": best["total_min"],
                                "stop_distance_km": s["distance_km"], "search_attempt": best["attempt"],
                                "radius_km": best["radius_km"]},
                         note=f"{'Partial: ' if c['status'] == 'partial' else ''}replaces {c['qty']:.0f} kg {c['product']} shortfall for {subj.name}",
                         status="pending")
                db.add(d)
                db.flush()
                inv = get_inv(db, seller.id, c["product"])
                if inv:
                    inv.reserved += qty  # hold the stock while awaiting approval
                deal_ids.append(d.id)
                c["deals"].append(d.id)
            if c.get("deals"):
                srcs = [x["name"] for x in best["selection"] if best["served"].get(x["entity_id"], best["served"].get(str(x["entity_id"]), 0)) > 0]
                trucks, km = len(best["routes"]), best["total_km"]
                db.add(Notification(
                    entity_id=subj.id, incident_id=state["incident_id"], level="alert",
                    message=(f"Ariadne found {len(srcs)} alternative source(s) for {c['qty']:.0f} kg of {c['product']} "
                             f"({', '.join(srcs[:4])}{'…' if len(srcs) > 4 else ''}) - covering {best['covered_routed']:.0f} kg. "
                             f"Route: {trucks} truck(s), {km:.0f} km, about {best['total_min'] // 60}h {best['total_min'] % 60}m from {best['depot']}. "
                             f"{len(c['deals'])} deal proposal(s) await your approval in Approvals; nothing changes until you decide.")))
            if c["status"] == "partial":
                unresolved.append({"buyer_id": c["buyer_id"], "buyer_name": c["buyer_name"], "product": c["product"],
                                   "qty": round(c["qty"] - best["covered_routed"], 1),
                                   "reason": f"only {best['covered_routed']:.0f} of {c['qty']:.0f} kg could be sourced and routed in {state.get('search_count', 0)} searches"})
    summary = [{"idx": c["idx"], "buyer_name": c["buyer_name"], "product": c["product"], "qty": c["qty"], "direction": c["direction"],
                "status": c["status"], "covered": c.get("covered", 0), "attempts": c["attempts"], "deals": c.get("deals", []),
                "approver": c["buyer_name"], "strategy": c.get("strategy"), "strategy_reason": c.get("strategy_reason")}
               for c in cases]
    return {"cases": cases, "deal_ids": deal_ids, "plans": summary, "outcome": {**(state.get("outcome") or {}), "unresolved": unresolved},
            "_tools": ["postgres.deals"], "_summary": f"{len(deal_ids)} deal(s) proposed, {len(unresolved)} unresolved"}


def after_propose(state) -> str:
    return "hitl_approval" if state.get("deal_ids") else "notification"


# ------------------------------------------------------------------ 4 HITL approval
@traced("hitl_approval", "hitl")
def hitl_approval(state):
    save_incident(state, "awaiting_approval")
    decisions = interrupt({"deal_ids": state["deal_ids"], "message": "Human approval required before any ledger change."})
    return {"decisions": decisions, "_summary": f"human decided: {decisions}"}


# ------------------------------------------------------------------ 5 deal / rerouting (ledger)
@traced("deal_rerouting", "recovery")
def deal_rerouting(state):
    """Execute approved deals in one transaction. The DB deal status is the source of truth
    (set by the human decision), so a replay of this node can never double-execute."""
    executed, rejected, failed = [], [], []
    with session_scope() as db:
        for did in state.get("deal_ids", []):
            d = db.get(Deal, did)
            if d.status == "rejected":
                rejected.append(did)
                continue
            if d.status == "executed":
                executed.append(did)
                continue
            if d.status != "approved":
                continue
            seller, buyer = db.get(Entity, d.seller_id), db.get(Entity, d.buyer_id)
            s_inv, b_inv = get_inv(db, seller.id, d.product), get_inv(db, buyer.id, d.product)
            total = d.quantity * d.unit_price + d.transport_cost
            if buyer.balance < total or not s_inv or s_inv.on_hand < d.quantity:
                d.status = "failed_funds"
                if s_inv:
                    s_inv.reserved = max(s_inv.reserved - d.quantity, 0)
                failed.append(did)
                db.add(AuditLog(actor="system", action="deal_failed", ref=str(did),
                                details={"balance": buyer.balance, "total": total}))
                continue
            s_inv.on_hand -= d.quantity
            s_inv.reserved = max(s_inv.reserved - d.quantity, 0)
            if b_inv is None:
                b_inv = Inventory(entity_id=buyer.id, product=d.product, on_hand=0, daily_demand=0, demand_std=0,
                                  shelf_life_days=s_inv.shelf_life_days, unit_price=d.unit_price, is_finished=False)
                db.add(b_inv)
            # blend stock age so degradation tracking stays honest
            old_age = (date.today() - b_inv.stocked_on).days if b_inv.on_hand > 0 else 0
            new_age = (date.today() - s_inv.stocked_on).days
            tot = b_inv.on_hand + d.quantity
            blended = (old_age * b_inv.on_hand + new_age * d.quantity) / tot if tot else 0
            b_inv.stocked_on = date.fromordinal(date.today().toordinal() - int(round(blended)))
            b_inv.on_hand = tot
            buyer.balance -= total
            seller.balance += d.quantity * d.unit_price
            memo = f"deal #{did} ({d.deal_type})"
            db.add_all([
                Ledger(deal_id=did, entity_id=seller.id, product=d.product, delta_qty=-d.quantity,
                       delta_money=d.quantity * d.unit_price, memo=memo + " sold"),
                Ledger(deal_id=did, entity_id=buyer.id, product=d.product, delta_qty=d.quantity,
                       delta_money=-total, memo=memo + " bought incl. transport"),
                AuditLog(actor=f"entity:{d.approver_id}", action="deal_executed", ref=str(did),
                         details={"qty": d.quantity, "total": total, "seller": seller.id, "buyer": buyer.id,
                                  "incident": d.incident_id}),
            ])
            d.status = "executed"
            executed.append(did)
    out = {**(state.get("outcome") or {}), "executed": executed, "rejected": rejected, "failed": failed}
    return {"outcome": out, "_tools": ["postgres.ledger"],
            "_summary": f"executed {len(executed)}, rejected {len(rejected)}, failed {len(failed)}"}


# ------------------------------------------------------------------ 6 notification
@traced("notification", "recovery")
def notification(state):
    out = state.get("outcome") or {}
    n = 0
    with session_scope() as db:
        subject = db.get(Entity, state["entity_id"])
        for did in out.get("executed", []):
            d = db.get(Deal, did)
            seller, buyer = db.get(Entity, d.seller_id), db.get(Entity, d.buyer_id)
            msg = f"Deal #{did} confirmed: {seller.name} -> {buyer.name}, {d.quantity:.0f} kg {d.product}"
            for t in {seller.id, buyer.id}:
                role = "Pick-up scheduled" if t == seller.id else "Delivery incoming"
                db.add(Notification(entity_id=t, incident_id=state["incident_id"], deal_id=did, level="deal",
                                    message=f"{role}. {msg} (₹{d.quantity * d.unit_price + d.transport_cost:,.0f} incl. transport)."))
                n += 1
        for u in out.get("unresolved", []):
            db.add(Notification(entity_id=u["buyer_id"], incident_id=state["incident_id"],
                                level="alert",
                                message=f"Manual action needed: {u['qty']:.0f} kg {u['product']} still unsourced - {u['reason']}."))
            n += 1
        if out.get("rejected"):
            db.add(Notification(entity_id=state["entity_id"], incident_id=state["incident_id"],
                                level="info",
                                message=f"{len(out['rejected'])} proposed deal(s) were rejected; no stock or balance changed."))
            n += 1
    return {"_summary": f"{n} notification(s) sent"}
