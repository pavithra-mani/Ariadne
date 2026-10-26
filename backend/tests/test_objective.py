"""The objective, the exact optimiser, learning memory, consolidated routing and the routing optimality check."""
import itertools
import random

import pytest

from app import constants
from app.agents.memory import acceptance
from app.agents.optimizer import candidates_for, greedy, optimize
from app.calc.needs import open_needs
from app.calc.objective import Offer, evaluate_plan
from app.config import settings
from app.db.models import Deal, Entity, Inventory, Target, User
from app.db.seed import reseed_data
from app.db.session import session_scope
from app.routing.provider import road_km
from app.routing.vrp import Stop, plan_route


@pytest.fixture(autouse=True)
def fresh():
    reseed_data()
    constants.set_cache({})
    settings.memory_enabled = True
    yield
    settings.memory_enabled = True


def _surge(qty=900):
    with session_scope() as db:
        sp = db.query(User).filter_by(username="spinner1").one().entity_id
        db.add(Target(entity_id=sp, product="yarn", target_qty=qty, horizon_days=7))


# ------------------------------------------------------------------ routing
def test_router_is_near_optimal_vs_brute_force():
    rng = random.Random(1)
    with session_scope() as db:
        ents = [(e.id, e.name, e.lat, e.lon) for e in db.query(Entity).filter(Entity.kind == "silkworm_farm")]
        reel = [(e.lat, e.lon) for e in db.query(Entity).filter(Entity.kind == "reeler")]
    gaps = []
    for _ in range(6):
        sel, depot = rng.sample(ents, rng.choice([4, 5, 6])), rng.choice(reel)
        stops = [Stop(i, n, la, lo, 20.0) for i, n, la, lo in sel]
        p = plan_route(depot, depot, stops, "yarn")
        best = min(sum(road_km(a, b) for a, b in zip([depot] + [(s.lat, s.lon) for s in perm], [(s.lat, s.lon) for s in perm] + [depot])) for perm in itertools.permutations(stops))
        gaps.append((p["total_km"] - best) / best * 100)
    assert max(gaps) < 1.0, gaps   # measured 0.00-0.03% on 12 instances


def test_ranking_uses_the_same_cost_model_as_the_router():
    from app.graph.recovery import transport_rate
    assert abs(transport_rate() - constants.get("truck_cost_per_km") / settings.vehicle_capacity_kg) < 1e-9


# ------------------------------------------------------------------ memory learns
def test_acceptance_probability_is_learned_from_decisions_and_can_be_switched_off():
    with session_scope() as db:
        s, b = [e.id for e in db.query(Entity).filter(Entity.kind.in_(["silkworm_farm", "reeler"])).limit(2)]
        prior = acceptance(db, s)["p"]
        assert abs(prior - 2 / 3) < 0.01 and acceptance(db, s)["n"] == 0
        for i in range(8):
            db.add(Deal(seller_id=s, buyer_id=b, product="cocoon", quantity=10, unit_price=1, deal_type="x", status="rejected",
                        seller_decision="rejected", buyer_decision="pending", rejected_by=s))
        db.flush()
        assert acceptance(db, s)["p"] < 0.25 and acceptance(db, s)["declined"] == 8
        for i in range(30):
            db.add(Deal(seller_id=b, buyer_id=s, product="cocoon", quantity=10, unit_price=1, deal_type="x", status="executed", seller_decision="approved", buyer_decision="approved"))
        db.flush()
        assert acceptance(db, b)["p"] > 0.9
        settings.memory_enabled = False
        assert abs(acceptance(db, s)["p"] - prior) < 1e-9     # ablation: history ignored


# ------------------------------------------------------------------ objective + optimiser
def test_optimizer_is_never_worse_than_greedy_under_the_same_objective_and_respects_stock():
    _surge()
    with session_scope() as db:
        needs = open_needs(db)
        assert needs
        c = candidates_for(db, needs, 80)
        g = evaluate_plan(db, needs, greedy(db, needs, 80, c))
        o = optimize(db, needs, 80, 4.0, c)
        e = evaluate_plan(db, needs, o["offers"])
        assert o["status"] in ("OPTIMAL", "FEASIBLE") and e["cost_inr"] <= g["cost_inr"] * 1.001
        used = {}
        for off in o["offers"]:
            used[(off.seller_id, off.product)] = used.get((off.seller_id, off.product), 0) + off.qty
        offer_cap = {(cd["entity_id"], k[1]): cd["offer"] for k, cs in c.items() for cd in cs}
        assert all(q <= offer_cap[k] + 1 for k, q in used.items())               # shared seller stock respected across buyers


def test_unreliable_sellers_are_avoided_once_the_memory_knows():
    _surge()
    with session_scope() as db:
        needs = open_needs(db)
        base = optimize(db, needs, 80, 4.0)["offers"]
        flaky = max(base, key=lambda o: o.qty).seller_id
        buyer = db.query(Entity).first().id
        for _ in range(12):
            db.add(Deal(seller_id=flaky, buyer_id=buyer, product="x", quantity=1, unit_price=1, deal_type="x", status="rejected", seller_decision="rejected", buyer_decision="pending", rejected_by=flaky))
        db.flush()
        after = optimize(db, needs, 80, 4.0)["offers"]
        qty = lambda offs: sum(o.qty for o in offs if o.seller_id == flaky)
        assert qty(after) < qty(base)                                             # the learned decline rate moved volume to other sellers


def test_consolidated_route_is_cheaper_than_separate_trips():
    with session_scope() as db:
        depot = db.query(Entity).filter_by(kind="reeler").first()
        ss = db.query(Entity).filter_by(kind="silkworm_farm").limit(4).all()
        stops = [Stop(s.id, s.name, s.lat, s.lon, q) for s, q in zip(ss, (100, 90, 80, 60))]
        sep = sum(plan_route((depot.lat, depot.lon), (depot.lat, depot.lon), [s], "cocoon")["cost"] for s in stops)
        joint = plan_route((depot.lat, depot.lon), (depot.lat, depot.lon), stops, "cocoon")
        assert joint["feasible"] and joint["cost"] < sep


def test_agent_offers_to_one_buyer_share_one_route(client, auth):
    from app.agents.guardian_agent import Episode, build_tools
    with session_scope() as db:
        r = db.query(User).filter_by(username="reeler1").one().entity_id
        inv = db.query(Inventory).filter_by(entity_id=r, product="cocoon").one()
        inv.on_hand, inv.reserved = 20, 0
    ep = Episode(event_ids=[])
    t = {f.__name__: f for f in build_tools(ep)}
    fv = t["find_vendors"](entity_id=r, product="cocoon", direction="buy", qty_kg=600, strategy="nearest", max_km=80)
    for v in fv["vendors"][:3]:
        t["propose_offer"](buyer_id=r, seller_id=v["entity_id"], product="cocoon", qty_kg=min(v["can_trade_kg"], 150))
    with session_scope() as db:
        ds = db.query(Deal).filter(Deal.id.in_(ep.offers)).all()
        assert len(ds) >= 2 and all(d.route.get("consolidated_with") is not None for d in ds)
        assert len({tuple(sorted(d.route["consolidated_with"] + [d.id])) for d in ds}) == 1       # one shared plan


def test_score_plan_and_optimize_tools_work_and_send_nothing(client, auth):
    from app.agents.guardian_agent import Episode, build_tools
    _surge()
    ep = Episode(event_ids=[])
    t = {f.__name__: f for f in build_tools(ep)}
    opt = t["optimize_sourcing"](max_km=80)
    assert opt["status"] in ("OPTIMAL", "FEASIBLE") and opt["offers"]
    import json
    sc = t["score_plan"](offers_json=json.dumps([{"buyer_id": o["buyer_id"], "seller_id": o["seller_id"], "product": o["product"], "qty_kg": o["qty_kg"]} for o in opt["offers"]]))
    assert not opt["truncated"] and abs(sc["cost_inr"] - opt["cost_inr"]) < 5   # one evaluator everywhere
    assert t["score_plan"](offers_json="not json")["error"]
    with session_scope() as db:
        assert db.query(Deal).count() == 0                                          # advice only


def test_ablation_hides_the_objective_tools():
    from app.agents.guardian_agent import Episode, build_tools
    settings.agent_tools = "no_optimizer"
    try:
        names = {f.__name__ for f in build_tools(Episode(event_ids=[]))}
    finally:
        settings.agent_tools = "full"
    assert "optimize_sourcing" not in names and "score_plan" not in names and "propose_offer" in names
