"""The objective Ariadne's sourcing decisions are judged by: ONE utility function, used by the agent's `score_plan` tool, the
CP-SAT optimiser, the simulator's regret measure and the paper's tables.

    cost(plan) = E[purchase] + E[transport] + penalty * E[unmet kg]           (utility = -cost)

Every offer is weighted by the seller's learned acceptance probability p (agents/memory.acceptance), because a deal only happens if
the human seller and buyer approve:
* E[purchase]  : sum(p x qty x seller unit price)
* E[transport] : the REAL joint vehicle-routing cost of the buyer's pick-ups (consolidated), scaled by the qty-weighted mean p
* E[unmet]     : max(need - sum(p x qty), 0); penalty = unit price x `unmet_penalty_multiplier` (unmet input halts production)
Stops the router cannot serve (too far for the product's transit limit) count as not delivered.
Over-ordering to hedge against declines is allowed up to HEDGE x need; surplus that is accepted is paid for (inside E[purchase]).
Constraints (enforced by tools/optimiser, not by the model): seller's sellable stock, buyer's real need, route feasibility.
Deal approval is NOT in the objective's control: humans approve (human in the loop)."""
from dataclasses import dataclass

from app import constants
from app.agents.memory import acceptance
from app.db.models import Entity, Inventory
from app.routing.vrp import Stop, plan_route


HEDGE = 1.25


@dataclass
class Offer:
    buyer_id: int
    seller_id: int
    product: str
    qty: float


def unmet_penalty(product: str) -> float:
    return constants.price(product) * constants.get("unmet_penalty_multiplier")


def depot_of(db, buyer: Entity) -> Entity:
    return db.get(Entity, buyer.warehouse_id) if buyer.warehouse_id else buyer


def evaluate_plan(db, needs: dict[tuple[int, str], float], offers: list[Offer]) -> dict:
    """Cost components of a set of offers against the open needs. Lower cost is better; `utility` = -cost."""
    purchase = transport = penalty = expected_unmet = 0.0
    by_buyer: dict[tuple[int, str], list[Offer]] = {}
    for o in offers:
        by_buyer.setdefault((o.buyer_id, o.product), []).append(o)
    per_buyer = []
    for key in set(needs) | set(by_buyer):
        b_id, product = key
        offs = by_buyer.get(key, [])
        buyer = db.get(Entity, b_id)
        exp_delivered, trip_cost = 0.0, 0.0
        if offs:
            stops, ps = [], {}
            for o in offs:
                s = db.get(Entity, o.seller_id)
                ps[s.id] = acceptance(db, s.id, "seller")["p"]
                stops.append(Stop(s.id, s.name, s.lat, s.lon, o.qty))
            dep = depot_of(db, buyer)
            plan = plan_route((dep.lat, dep.lon), (buyer.lat, buyer.lon), stops, product)
            served = {k: v for k, v in plan["served"].items()}  # what the router can actually pick up
            wsum = 0.0
            for o in offs:
                q = min(o.qty, served.get(o.seller_id, 0.0))
                inv = db.query(Inventory).filter_by(entity_id=o.seller_id, product=product).first()
                purchase += ps[o.seller_id] * q * (inv.unit_price if inv else 0.0)
                exp_delivered += ps[o.seller_id] * q
                wsum += q
            mean_p = exp_delivered / wsum if wsum else 0.0
            trip_cost = plan["cost"] * mean_p
            transport += trip_cost
        unmet = max(needs.get(key, 0.0) - exp_delivered, 0.0)
        expected_unmet += unmet
        penalty += unmet * unmet_penalty(product)
        per_buyer.append({"buyer_id": b_id, "product": product, "need_kg": round(needs.get(key, 0.0), 1), "offered_kg": round(sum(o.qty for o in offs), 1),
                          "expected_delivered_kg": round(exp_delivered, 1), "transport_inr": round(trip_cost)})
    cost = purchase + transport + penalty
    return {"utility": round(-cost), "cost_inr": round(cost), "purchase_inr": round(purchase), "transport_inr": round(transport),
            "unmet_penalty_inr": round(penalty), "expected_unmet_kg": round(expected_unmet, 1), "per_buyer": per_buyer}
