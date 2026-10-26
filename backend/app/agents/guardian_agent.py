"""The guardian as a tool-using LLM agent (ReAct-style loop).

The model decides WHICH tool to call, in WHAT order, with WHAT arguments, observes the result and decides what to
do next, until it judges the situation handled (or the step limit is reached). Nothing in this file contains an
`if gap then source` rule: those decisions belong to the model. What the code owns is the world (stock, flow
solver, routing, ledger) and the safety envelope:

* tools are the only way to act; the only tool that changes anything is `propose_offer`, and it only creates a
  PENDING deal: stock and money move only after the seller AND the buyer approve (human in the loop);
* every quantity the model passes is clamped to what the database says is possible (seller's sellable stock,
  buyer's real need); a vendor that recently declined cannot be offered the same trade again;
* hard limits: steps and offers per episode; numbers in user-facing messages come from the solver, not the model;
* memory: vendor track record is derived from deal history; the model may also write short lessons.
If the LLM is unavailable the guardian falls back to its deterministic rules and says so (see guardian.py).
"""
import functools
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.agents.memory import acceptance, add_note, notes_for, pair_declined_recently, vendor_stats
from app.calc.flow import solve
from app.calc.needs import need_cap, open_needs, pending_in as _pending_in, pending_out as _pending_out
from app.calc.objective import HEDGE, Offer, depot_of, evaluate_plan
from app.calc.impact import INPUT_PRODUCT, OUTPUT_PRODUCT, get_inv
from app.calc.supply import stock_status, surplus_qty
from app.config import settings
from app.db.models import Deal, Entity, Inventory, Notification
from app.db.session import session_scope
from app.graph.recovery import BUYER_KIND, DEAL_TYPE, RADII_KM, SUPPLIER_KIND, find_candidates
from app.agents.planner import order_candidates
from app.llm.provider import LLMUnavailable, get_llm, reset_budget, start_budget
from app.routing.vrp import Stop, plan_route

log = logging.getLogger("ariadne.guardian_agent")
STRATEGIES = ("balanced", "cheapest", "nearest", "fewest_sources")

SYSTEM = """You are Ariadne's guardian agent for a sericulture supply chain (mulberry farm -> silkworm farm -> reeler -> spinner).
OBJECTIVE: minimise expected cost = E[purchase] + E[transport] + penalty x E[unmet kg of input]. Each offer counts only with the seller's
learned acceptance probability (a human must approve). Constraints: seller's sellable stock, buyer's real need, feasible truck routes.
Also: perishable surplus should be sold to someone who needs it, and you must never promise what you cannot cover.
You have tools to measure this objective: score_plan prices any candidate set of offers; optimize_sourcing returns the exact optimum for
all open needs (it does not send anything). They are advice, not orders: follow them, adjust them, or override them with a stated reason
(for example memory about a vendor that the numbers miss). Compare alternatives with score_plan before committing when the choice is not obvious.
You work by calling tools. You decide the order. A change just happened (see EVENTS). Typical good behaviour: look at the
network status (it lists open shortfalls, raw-input stock at reorder point, and surplus only for the participants the events concern), pick the most urgent problem, inspect/recall what is relevant, find vendors, send offers sized to the real need,
then verify coverage and keep going until the problems you can fix are fixed. Perishable goods (leaves keep 3 days, cocoon 8): prefer 'nearest'.
Big quantities: 'fewest_sources'. Cost-driven with time to spare: 'cheapest'. If a vendor declined before, read the reason in recall_memory
and choose differently (another vendor, a different strategy, a wider max_km). If after trying you cannot cover a shortfall, call
report_unresolved so the affected person is told honestly; do not leave it silent.
RULES: you can only PROPOSE: every deal needs the seller's and the buyer's approval; nothing you do moves stock or money. Never invent
numbers: quantities come from tools. Use as few steps as needed (limit {steps}); several independent calls may be made in one turn. When done,
reply with 2-4 plain sentences: what you saw, what you did, what remains."""


@dataclass
class Episode:
    event_ids: list[int]
    log: list[dict] = field(default_factory=list)
    offers: list[int] = field(default_factory=list)
    reported: list[dict] = field(default_factory=list)
    invalid: int = 0
    flow: dict | None = None
    focus: set[int] = field(default_factory=set)  # participants the triggering events are about

    def solved(self, db, refresh: bool = False) -> dict:
        if self.flow is None or refresh:
            self.flow = solve(db)
        return self.flow


def _ent(db, eid: int) -> Entity | None:
    e = db.get(Entity, eid)
    return e if e and e.kind != "warehouse" else None


def _need_cap(db, ep: Episode, buyer: Entity, product: str) -> float:
    return need_cap(db, buyer, product, ep.solved(db))


def create_offer(ep: Episode, buyer_id: int, seller_id: int, product: str, qty_kg: float, reason: str = "") -> dict:
    """The ONLY place a deal is created by an automated decision-maker (LLM agent tool or the optimiser baseline).
    Validates against the database, clamps the quantity, builds a PENDING deal, notifies both parties, and re-plans the
    buyer's pick-ups as ONE consolidated route (separate trips per offer overpay by ~37%)."""
    if len(ep.offers) >= settings.agent_max_offers:
        return {"error": f"offer limit reached ({settings.agent_max_offers} per episode)"}
    with session_scope() as db:
        buyer, seller = _ent(db, buyer_id), _ent(db, seller_id)
        if not buyer or not seller:
            return {"error": "unknown buyer or seller"}
        if SUPPLIER_KIND.get(product) != seller.kind or BUYER_KIND.get(product) != buyer.kind:
            return {"error": f"a {seller.kind} cannot sell {product} to a {buyer.kind}"}
        if pair_declined_recently(db, seller.id, buyer.id, product):
            return {"error": f"{seller.name} declined this trade with {buyer.name} recently; choose another vendor"}
        inv = db.query(Inventory).filter_by(entity_id=seller.id, product=product).with_for_update().first()
        if not inv or not inv.is_finished:
            return {"error": f"{seller.name} has no {product} to sell"}
        cap_buyer = _need_cap(db, ep, buyer, product) * HEDGE
        qty = round(min(float(qty_kg), stock_status(inv).sellable, cap_buyer), 1)
        if qty < 1:
            return {"error": f"nothing to offer: seller can spare {stock_status(inv).sellable:.0f} kg, buyer can use {cap_buyer:.0f} kg more"}
        dep = depot_of(db, buyer)
        plan = plan_route((dep.lat, dep.lon), (buyer.lat, buyer.lon), [Stop(seller.id, seller.name, seller.lat, seller.lon, qty)], product)
        served = round(sum(plan["served"].values()), 1)
        if served < 1 or not plan["feasible"]:
            return {"error": "no feasible pick-up route for this trade (too far or too slow)"}
        qty = min(qty, served)
        d = Deal(incident_id=None, deal_type=DEAL_TYPE.get((seller.kind, buyer.kind), f"{seller.kind}_{buyer.kind}"), seller_id=seller.id, buyer_id=buyer.id, approver_id=buyer.id,
                 product=product, quantity=qty, unit_price=round(inv.unit_price, 2), transport_cost=round(plan["cost"], 2),
                 route={"depot": dep.name, "routes": plan["routes"], "distance_km": plan["total_km"], "duration_min": plan["total_min"]},
                 note=(reason or f"offer for {buyer.name}")[:300], status="pending", origin="agent", event_id=ep.event_ids[0] if ep.event_ids else None)
        db.add(d)
        db.flush()
        inv.reserved += qty
        db.add_all([
            Notification(entity_id=seller.id, deal_id=d.id, level="deal",
                         message=f"Offer request: {buyer.name} ({buyer.village}) would like to buy {qty:.0f} kg of {product} from you at ₹{d.unit_price:,.0f}/kg "
                                 f"(pick-up by the buyer's truck). Approve or decline in Approvals - nothing moves until both of you approve."),
            Notification(entity_id=buyer.id, deal_id=d.id, level="deal",
                         message=f"Ariadne found a source: {seller.name} ({seller.village}) can sell you {qty:.0f} kg of {product} at ₹{d.unit_price:,.0f}/kg. "
                                 f"The seller has been asked; approve or decline in Approvals (transport is shared across your pick-ups).")])
        ep.offers.append(d.id)
        _consolidate_routes(db, ep, buyer, product)
        return {"deal_id": d.id, "qty_kg": qty, "requested_kg": qty_kg, "unit_price_inr": d.unit_price,
                "distance_km": plan["total_km"], "status": "pending: waiting for seller and buyer approval"}


def _consolidate_routes(db, ep: Episode, buyer: Entity, product: str) -> None:
    """All of this episode's pending offers to one buyer share one pick-up plan: re-route jointly and split the cost pro rata."""
    deals = db.query(Deal).filter(Deal.id.in_(ep.offers), Deal.buyer_id == buyer.id, Deal.product == product, Deal.status == "pending").all()
    if len(deals) < 2:
        return
    dep = depot_of(db, buyer)
    stops = [Stop(d.seller_id, db.get(Entity, d.seller_id).name, db.get(Entity, d.seller_id).lat, db.get(Entity, d.seller_id).lon, d.quantity) for d in deals]
    plan = plan_route((dep.lat, dep.lon), (buyer.lat, buyer.lon), stops, product)
    if not plan["feasible"]:
        return  # keep the individual routes
    total = sum(d.quantity for d in deals)
    for d in deals:
        d.transport_cost = round(plan["cost"] * d.quantity / total, 2)
        d.route = {"depot": dep.name, "routes": plan["routes"], "distance_km": plan["total_km"], "duration_min": plan["total_min"], "consolidated_with": [x.id for x in deals if x.id != d.id]}


def build_tools(ep: Episode) -> list:
    def logged(fn):
        @functools.wraps(fn)
        def wrapper(*a, **k):
            try:
                out = fn(*a, **k)
            except Exception as exc:  # a bad call is information for the model, never a crash
                out = {"error": f"{type(exc).__name__}: {exc}"}
            if isinstance(out, dict) and out.get("error"):
                ep.invalid += 1
            ep.log.append({"tool": fn.__name__, "args": k or list(a), "result": json.loads(json.dumps(out, default=str))})
            return out
        return wrapper

    @logged
    def get_network_status() -> dict:
        """Whole-chain snapshot from the flow solver: per tier the requested/deliverable amounts, the entities that their
        current suppliers cannot serve (gaps, kg short over the planning horizon), entities at or below reorder point, finished
        stock that will spoil unused (surplus), and offers already pending. Call this first."""
        with session_scope() as db:
            f = ep.solved(db, refresh=True)
            low, surplus = [], []
            for e in db.query(Entity).filter(Entity.kind != "warehouse", Entity.active.is_(True)):
                for inv in db.query(Inventory).filter_by(entity_id=e.id):
                    st = stock_status(inv)
                    if st.status in ("reorder", "critical") and not inv.is_finished:  # raw inputs: the actionable kind (buy more)
                        low.append({"entity_id": e.id, "name": e.name, "product": inv.product, "status": st.status,
                                    "available_kg": round(st.available), "reorder_point_kg": round(st.reorder_point), "days_of_cover": round(st.days_of_cover, 1)})
                    if inv.is_finished and e.id in ep.focus and (q := surplus_qty(inv, st)) > 0:  # only where something just changed
                        surplus.append({"entity_id": e.id, "name": e.name, "product": inv.product, "surplus_kg": q, "spoils_in_days": round(st.degrades_in_days, 1)})
            gaps = [{**g, "already_offered_kg": round(_pending_in(db, g["entity_id"], g["product"]), 1)} for g in f["gaps"][:12]]
            return {"horizon_days": f["horizon_days"], "chain_balanced": f["ok"],
                    "tiers": [{k: t[k] for k in ("kind", "requested_out", "feasible_out", "short_linked", "short_final")} for t in f["tiers"]],
                    "gaps": gaps, "low_stock": low[:12], "surplus": surplus[:8]}

    @logged
    def inspect_entity(entity_id: int) -> dict:
        """Details of one participant: kind, village, balance, each product's stock status, offers pending for or from it."""
        with session_scope() as db:
            e = _ent(db, entity_id)
            if not e:
                return {"error": f"no participant {entity_id}"}
            return {"entity_id": e.id, "name": e.name, "kind": e.kind, "village": e.village, "balance_inr": round(e.balance),
                    "capacity_kg_per_day": e.capacity_per_day, "load_kg_per_day": e.daily_throughput,
                    "stock": [{k: v for k, v in stock_status(i).dict().items() if k in ("product", "on_hand", "available", "sellable", "reorder_point", "days_of_cover", "degrades_in_days", "status", "unit_price", "is_finished")}
                              for i in db.query(Inventory).filter_by(entity_id=e.id)],
                    "pending_offers": [{"deal": d.id, "product": d.product, "kg": d.quantity, "role": "seller" if d.seller_id == e.id else "buyer"}
                                       for d in db.query(Deal).filter(Deal.status == "pending", (Deal.seller_id == e.id) | (Deal.buyer_id == e.id)).limit(8)]}

    @logged
    def simulate_demand(entity_id: int, extra_kg: float) -> dict:
        """What-if (changes nothing): how would the chain cope if this participant's demand rose by extra_kg
        (spinner: yarn wanted; others: extra orders for their output)? Returns the shortfalls per tier."""
        with session_scope() as db:
            if not _ent(db, entity_id):
                return {"error": f"no participant {entity_id}"}
            sim = solve(db, extra_demand={entity_id: float(extra_kg)})
            return {"chain_balanced": sim["ok"], "rounds": len(sim["rounds"]),
                    "tiers": [{k: t[k] for k in ("kind", "requested_out", "feasible_out", "short_linked", "short_final")} for t in sim["tiers"]],
                    "worst_gaps": sim["gaps"][:5]}

    @logged
    def recall_memory(entity_id: int) -> dict:
        """What is remembered about a participant: its track record as seller and buyer (offers, executed, declined, recent
        decline reasons), its learned acceptance probability (Beta posterior with a credible interval) and lessons written down earlier."""
        with session_scope() as db:
            if not _ent(db, entity_id):
                return {"error": f"no participant {entity_id}"}
            return {**vendor_stats(db, entity_id), "notes": notes_for(db, [entity_id], 5)}

    @logged
    def find_vendors(entity_id: int, product: str, direction: str, qty_kg: float, strategy: str = "balanced", max_km: float = 50) -> dict:
        """Candidate counterparties for a trade, nearest rings first. direction='buy': entity_id needs `product` and these are
        sellers; direction='sell': entity_id has surplus finished `product` and these are buyers who need it. strategy: balanced |
        cheapest | nearest | fewest_sources. max_km widens the search (15, 30, 50, 80, 150). Vendors that recently declined this
        trade are excluded. Each candidate has its price, distance, how much it can take/offer, acceptance_prob (learned from its past approvals/declines) and past_decisions (evidence count)."""
        if strategy not in STRATEGIES:
            return {"error": f"strategy must be one of {STRATEGIES}"}
        if direction not in ("buy", "sell"):
            return {"error": "direction must be 'buy' or 'sell'"}
        with session_scope() as db:
            e = _ent(db, entity_id)
            if not e:
                return {"error": f"no participant {entity_id}"}
            if direction == "buy" and e.kind != BUYER_KIND.get(product):
                return {"error": f"{e.kind} does not buy {product}"}
            if direction == "sell" and OUTPUT_PRODUCT.get(e.kind) != product:
                return {"error": f"{e.kind} does not sell {product}"}
            case = {"buyer_id": e.id, "product": product, "qty": qty_kg, "direction": "upstream" if direction == "buy" else "outbound", "exclude_ids": [], "deadline_days": 3}
            cands = order_candidates(find_candidates(db, case, float(max_km), {}), strategy)[:8]
            return {"entity": e.name, "need_kg": qty_kg, "searched_km": max_km, "n_found": len(cands), "vendors": [
                {"entity_id": c["entity_id"], "name": c["name"], "village": c["village"], "distance_km": c["distance_km"], "can_trade_kg": c["offer"],
                 "unit_price_inr": c["unit_price"], "acceptance_prob": acceptance(db, c["entity_id"], "seller")["p"] if direction == "buy" else None,
                 "past_decisions": acceptance(db, c["entity_id"], "seller")["n"] if direction == "buy" else None}
                for c in cands]}

    @logged
    def propose_offer(buyer_id: int, seller_id: int, product: str, qty_kg: float, reason: str = "") -> dict:
        """Send an offer: ask seller_id to sell qty_kg of product to buyer_id. This only creates a PENDING deal; both the seller and
        the buyer are notified and must approve before anything moves. The quantity is clamped to the seller's sellable stock and
        to the buyer's real need (with a small allowance to hedge against declines), so the returned qty_kg may be smaller than
        requested. Offers to the same buyer are re-planned as one shared pick-up route."""
        return create_offer(ep, buyer_id, seller_id, product, qty_kg, reason)

    @logged
    def score_plan(offers_json: str) -> dict:
        """Score a candidate set of offers WITHOUT sending anything. offers_json is a JSON list of
        {"buyer_id": int, "seller_id": int, "product": str, "qty_kg": number}. Returns the expected cost (INR) = E[purchase] +
        E[transport: real consolidated route] + penalty x E[unmet kg], each offer weighted by the seller's learned acceptance
        probability, plus per-buyer coverage. Lower cost_inr is better. Use it to compare alternatives before proposing."""
        try:
            raw = json.loads(offers_json)
            offers = [Offer(int(o["buyer_id"]), int(o["seller_id"]), str(o["product"]), float(o["qty_kg"])) for o in raw]
        except Exception as exc:
            return {"error": f"offers_json must be a JSON list of buyer_id/seller_id/product/qty_kg objects ({exc})"}
        if len(offers) > 40:
            return {"error": "at most 40 offers"}
        with session_scope() as db:
            needs = open_needs(db, ep.solved(db))
            res = evaluate_plan(db, needs, offers)
            return {k: res[k] for k in ("cost_inr", "purchase_inr", "transport_inr", "unmet_penalty_inr", "expected_unmet_kg", "per_buyer")}

    @logged
    def optimize_sourcing(max_km: float = 80, buyer_ids_json: str = "") -> dict:
        """Run the exact optimiser (CP-SAT) over ALL open needs (or only the buyers listed in buyer_ids_json, a JSON list of ids)
        at once. It minimises expected cost (purchase + transport + shortfall penalty) with shared seller stock, truck capacity and
        learned acceptance probabilities. Returns the recommended offers and their cost; it does NOT send anything: you decide whether
        to follow it (use propose_offer), adjust it, or override it (for example because memory says a vendor is unreliable for a reason
        the numbers miss)."""
        from app.agents.optimizer import optimize
        with session_scope() as db:
            needs = open_needs(db, ep.solved(db, refresh=True))
            if buyer_ids_json:
                keep = {int(x) for x in json.loads(buyer_ids_json)}
                needs = {k: v for k, v in needs.items() if k[0] in keep}
            if not needs:
                return {"note": "no open needs"}
            r = optimize(db, needs, float(max_km), time_limit=4.0)
            ev = evaluate_plan(db, needs, r["offers"])
            names = {k: db.get(Entity, k).name for o in r["offers"] for k in (o.buyer_id, o.seller_id)}
            return {"status": r["status"], "cost_inr": ev["cost_inr"], "expected_unmet_kg": ev["expected_unmet_kg"], "n_needs": len(needs),
                    "offers": [{"buyer_id": o.buyer_id, "buyer": names[o.buyer_id], "seller_id": o.seller_id, "seller": names[o.seller_id], "product": o.product, "qty_kg": o.qty} for o in r["offers"]][:40],
                    "n_offers": len(r["offers"]), "truncated": len(r["offers"]) > 40}

    @logged
    def verify_coverage(entity_id: int, product: str) -> dict:
        """Reflection check: after your offers, how much of this participant's shortfall is still uncovered? Uses a fresh
        flow solve and counts pending offers as expected supply. remaining_kg == 0 means the goal is met if the offers are accepted."""
        with session_scope() as db:
            e = _ent(db, entity_id)
            if not e:
                return {"error": f"no participant {entity_id}"}
            f = ep.solved(db, refresh=True)
            gap = next((g["short_linked"] for g in f["gaps"] if g["entity_id"] == entity_id and g["product"] == product), 0.0)
            inv = get_inv(db, entity_id, product)
            st = stock_status(inv) if inv else None
            stock_gap = max(st.reorder_point + inv.daily_demand * 3 - st.available, 0.0) if st and not inv.is_finished else 0.0
            offered = _pending_in(db, entity_id, product)
            out_offered = _pending_out(db, entity_id, product)
            surplus = surplus_qty(inv, st) if inv and inv.is_finished else 0.0
            return {"entity": e.name, "product": product, "shortfall_kg": round(max(gap, stock_gap), 1), "offered_kg_pending": round(offered, 1),
                    "remaining_kg": round(max(max(gap, stock_gap) - offered, 0.0), 1),
                    "surplus_kg": surplus, "surplus_offered_kg_pending": round(out_offered, 1), "surplus_remaining_kg": round(max(surplus - out_offered, 0.0), 1)}

    @logged
    def report_unresolved(entity_id: int, product: str, reason: str) -> dict:
        """Tell the affected participant honestly that a shortfall could not be covered. The message states the real remaining
        amount (computed, not taken from you) plus your short reason. Use only after trying."""
        with session_scope() as db:
            e = _ent(db, entity_id)
            if not e:
                return {"error": f"no participant {entity_id}"}
            f = ep.solved(db, refresh=True)
            gap = next((g["short_linked"] for g in f["gaps"] if g["entity_id"] == entity_id and g["product"] == product), 0.0)
            remaining = round(max(gap - _pending_in(db, entity_id, product), 0.0), 1)
            if remaining < 1:
                return {"note": "nothing remains uncovered; no message sent"}
            db.add(Notification(entity_id=entity_id, level="alert",
                                message=f"Manual action needed: about {remaining:.0f} kg of {product} is still uncovered after Ariadne's search. {reason[:160]}"))
            ep.reported.append({"entity_id": entity_id, "product": product, "remaining_kg": remaining})
            return {"sent": True, "remaining_kg": remaining}

    @logged
    def save_note(entity_id: int, note: str) -> dict:
        """Write a short lesson to long-term memory about a participant (for example why a vendor declined or which source is dependable)."""
        with session_scope() as db:
            if not _ent(db, entity_id):
                return {"error": f"no participant {entity_id}"}
            add_note(db, entity_id, note, ep.event_ids[0] if ep.event_ids else None)
        return {"saved": True}

    tools = [get_network_status, inspect_entity, simulate_demand, recall_memory, find_vendors, propose_offer, verify_coverage, report_unresolved, save_note]
    if settings.agent_tools == "full":  # ablation: 'no_optimizer' withholds the objective-aware tools
        tools += [score_plan, optimize_sourcing]
    return tools


def describe_events(batch: list[tuple]) -> str:
    lines = []
    with session_scope() as db:
        names = lambda i: (db.get(Entity, i).name if i and db.get(Entity, i) else "?")
        for _, eid, product, reason, data in batch:
            if reason == "stock_changed":
                lines.append(f"- {names(eid)}'s {product} stock changed (was '{data.get('before_status')}', sellable fell by {data.get('sellable_drop', 0):.0f} kg).")
            elif reason == "target_set":
                lines.append(f"- {names(eid)} set a demand target of {data.get('target_qty')} kg over {data.get('horizon_days')} days.")
            elif reason == "deal_executed":
                lines.append(f"- A deal executed (deal {data.get('deal_id')}); stock changed for {[names(p[0]) for p in data.get('parties', [])]}.")
            elif reason == "deal_rejected":
                d = db.get(Deal, data.get("deal_id")) if data.get("deal_id") else None
                who = names(d.rejected_by) if d and d.rejected_by else "a party"
                why = f" Reason given: '{d.decline_reason}'." if d and d.decline_reason else ""
                lines.append(f"- DECLINED: {who} declined deal {d.id if d else '?'} ({d.quantity:.0f} kg {d.product}, seller {names(d.seller_id)}, buyer {names(d.buyer_id)}).{why} Re-plan: the need is open again." if d
                             else "- A deal was declined; re-plan.")
            else:
                lines.append(f"- {reason}.")
        ids = [e for _, e, *_ in batch if e]
        notes = notes_for(db, ids, 5) if ids else []
    if notes:
        lines.append("Remembered lessons about those participants: " + json.dumps(notes))
    return "\n".join(lines)


def run_episode(batch: list[tuple]) -> dict:
    """One agent episode for a batch of events. Raises LLMUnavailable if there is no LLM to decide with."""
    llm = get_llm()
    if llm is None:
        raise LLMUnavailable("no LLM configured")
    needs0 = None
    if settings.agent_log_regret:
        with session_scope() as db:
            needs0 = open_needs(db)
    ep = Episode(event_ids=[b[0] for b in batch], focus={e for _, eid, _, _, d in batch for e in ([eid] if eid else []) + [p[0] for p in d.get("parties", [])]})
    t0, interrupted = datetime.utcnow(), None
    reset_budget()
    start_budget(settings.agent_max_steps + 10)
    system = SYSTEM.format(steps=settings.agent_max_steps)
    try:
        run = llm.tool_loop(system, "EVENTS:\n" + describe_events(batch), build_tools(ep), "guardian", settings.agent_max_steps)
        summary, calls = run.text, run.calls
    except LLMUnavailable as exc:
        interrupted, summary, calls = str(exc), "", len(ep.log)
    res = {"mode": "agent", "summary": summary, "steps": ep.log, "llm_calls": calls, "offers": ep.offers, "reported": ep.reported,
           "invalid_tool_calls": ep.invalid, "interrupted": interrupted, "step_limit_hit": len(ep.log) >= settings.agent_max_steps,
           "seconds": round((datetime.utcnow() - t0).total_seconds(), 1)}
    if needs0 is not None:
        res["regret"] = regret(needs0, ep.offers)
    return res


def regret(needs0: dict, offer_ids: list[int], max_km: float = 150.0) -> dict:
    """Cost of what an automated decision-maker offered vs the exact optimum for the same needs (same evaluator, same learned
    acceptance probabilities): the paper's optimality-gap measure. Recorded per episode when `agent_log_regret` is on."""
    from app.agents.optimizer import optimize
    if not needs0:
        return {"needs_kg": 0}
    with session_scope() as db:
        offers = [Offer(d.buyer_id, d.seller_id, d.product, d.quantity) for d in db.query(Deal).filter(Deal.id.in_(offer_ids))] if offer_ids else []
        mine = evaluate_plan(db, needs0, offers)
        opt = optimize(db, needs0, max_km, time_limit=4.0)
        best = evaluate_plan(db, needs0, opt["offers"])
    gap = (mine["cost_inr"] - best["cost_inr"]) / best["cost_inr"] * 100 if best["cost_inr"] else 0.0
    return {"needs_kg": round(sum(needs0.values())), "cost_inr": mine["cost_inr"], "oracle_cost_inr": best["cost_inr"], "regret_pct": round(gap, 2),
            "cost_parts": {k: mine[k] for k in ("purchase_inr", "transport_inr", "unmet_penalty_inr", "expected_unmet_kg")},
            "oracle_status": opt["status"], "oracle_bound_inr": opt.get("bound_inr")}


def run_optimizer_episode(batch: list[tuple]) -> dict:
    """Non-LLM baseline: solve all open needs exactly and send the optimal offers. Same tools/guardrails, no model deciding."""
    from app.agents.optimizer import optimize
    ep = Episode(event_ids=[b[0] for b in batch])
    t0 = datetime.utcnow()
    with session_scope() as db:
        needs0 = open_needs(db, ep.solved(db))
        r = optimize(db, needs0, 150.0, time_limit=4.0) if needs0 else {"offers": [], "status": "none"}
    for o in r["offers"]:
        try:
            out = create_offer(ep, o.buyer_id, o.seller_id, o.product, o.qty, "optimiser (CP-SAT)")
        except Exception as exc:  # one bad offer must not lose the rest
            out = {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        ep.log.append({"tool": "create_offer", "args": {"buyer_id": o.buyer_id, "seller_id": o.seller_id, "qty_kg": o.qty}, "result": out})
        if "error" in out:
            ep.invalid += 1
    res = {"mode": "optimizer", "summary": f"CP-SAT {r['status']}: {len(ep.offers)} offers for {len(needs0)} needs", "steps": ep.log, "llm_calls": 0,
           "offers": ep.offers, "reported": [], "invalid_tool_calls": ep.invalid, "interrupted": None, "step_limit_hit": False,
           "seconds": round((datetime.utcnow() - t0).total_seconds(), 1)}
    if settings.agent_log_regret:
        res["regret"] = regret(needs0, ep.offers)
    return res
