"""CP-SAT sourcing optimiser: the non-LLM benchmark AND a tool the agent may call.

Decides, for all open needs at once, how many kg each buyer takes from each seller, minimising
    purchase + transport + penalty x expected_unmet
subject to: seller's sellable stock (shared across buyers), buyer's need, truck capacity. Transport is linearised as
round trips x distance x cost/km (an upper-bound approximation of the real consolidated route); the plan is then scored
with the real vehicle-routing evaluator (calc/objective.evaluate_plan) so greedy / optimiser / agent are compared on
exactly the same numbers. CP-SAT proves optimality (or reports its bound) within the time limit."""
import math

from ortools.sat.python import cp_model

from app.agents.memory import acceptance, pair_declined_recently
from app.calc.objective import HEDGE, Offer, unmet_penalty
from app.config import settings
from app.db.models import Entity
from app.graph.recovery import find_candidates, order_candidates, select
from app.routing.vrp import cost_per_km

SCALE = 100  # money in 1/100 INR inside the model (CP-SAT needs integers)


def candidates_for(db, needs: dict, max_km: float) -> dict:
    out = {}
    for (b, product), need in needs.items():
        case = {"buyer_id": b, "product": product, "qty": need, "direction": "upstream", "exclude_ids": [], "deadline_days": 3}
        out[(b, product)] = find_candidates(db, case, max_km, {})
    return out


def optimize(db, needs: dict, max_km: float = 80.0, time_limit: float = 5.0, cands: dict | None = None) -> dict:
    cands = cands if cands is not None else candidates_for(db, needs, max_km)
    m = cp_model.CpModel()
    x, trips, seller_cap = {}, {}, {}
    cap = settings.vehicle_capacity_kg
    cost_terms = []
    for key, cs in cands.items():
        b, product = key
        need = int(needs[key])
        for c in cs:
            ub = int(min(c["offer"], need * HEDGE))
            if ub < 1:
                continue
            v = m.NewIntVar(0, ub, f"x_{b}_{c['entity_id']}_{product}")
            t = m.NewIntVar(0, math.ceil(ub / cap), f"t_{b}_{c['entity_id']}")
            m.Add(cap * t >= v)
            x[key, c["entity_id"]], trips[key, c["entity_id"]] = v, t
            seller_cap[(c["entity_id"], product)] = int(c["offer"])
            p = acceptance(db, c["entity_id"], "seller")["p"]
            cost_terms.append(int(round(p * c["unit_price"] * SCALE)) * v)                      # E[purchase]
            cost_terms.append(int(round(p * 2 * c["distance_km"] * cost_per_km() * SCALE)) * t)  # E[transport] (round trips, upper bound)
    for (s, product), cap_s in seller_cap.items():
        m.Add(sum(v for (k, sid), v in x.items() if sid == s and k[1] == product) <= cap_s)
    unmet = {}
    for key in needs:
        need = int(needs[key])
        terms = [(v, int(round(acceptance(db, sid, "seller")["p"] * 1000))) for (k, sid), v in x.items() if k == key]
        m.Add(sum(v for v, _ in terms) <= int(need * HEDGE))
        u = m.NewIntVar(0, need, f"u_{key[0]}")
        m.Add(1000 * u + sum(p * v for v, p in terms) >= 1000 * need)  # expected delivered + unmet >= need
        unmet[key] = u
        cost_terms.append(int(round(unmet_penalty(key[1]) * SCALE)) * u)
    m.Minimize(sum(cost_terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 4
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"status": solver.StatusName(status), "offers": [], "objective_inr": None}
    offers = []
    for (key, sid), v in x.items():
        q = solver.Value(v)
        if q >= 1:
            c = next(c for c in cands[key] if c["entity_id"] == sid)
            offers.append(Offer(key[0], sid, key[1], float(q)))
    return {"status": solver.StatusName(status), "offers": offers, "objective_inr": round(solver.ObjectiveValue() / SCALE),
            "bound_inr": round(solver.BestObjectiveBound() / SCALE), "seconds": round(solver.WallTime(), 2)}


def greedy(db, needs: dict, max_km: float = 80.0, cands: dict | None = None, strategy: str = "balanced") -> list[Offer]:
    """What the rules path does: each buyer independently takes the best-scored candidates (no shared stock, no joint view)."""
    cands = cands if cands is not None else candidates_for(db, needs, max_km)
    used: dict[tuple[int, str], float] = {}
    out = []
    for key in sorted(needs, key=lambda k: -needs[k]):
        chosen = select(order_candidates([{**c, "offer": c["offer"] - used.get((c["entity_id"], key[1]), 0.0)} for c in cands[key]
                                          if c["offer"] - used.get((c["entity_id"], key[1]), 0.0) >= 1], strategy), needs[key])
        for c in chosen:
            out.append(Offer(key[0], c["entity_id"], key[1], c["take"]))
            used[(c["entity_id"], key[1])] = used.get((c["entity_id"], key[1]), 0.0) + c["take"]
    return out
