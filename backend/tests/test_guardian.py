"""Guardian agent, network flow, two-sided approval, outbound surplus, live-data fallback, background runs."""
import json
import time

import pytest
from conftest import decide_deals

from app import constants
from app.calc.flow import solve
from app.calc.impact import get_inv
from app.db.models import AgentEvent, Constant, Deal, Entity, Incident, Inventory, User
from app.db.seed import reseed_data
from app.db.session import session_scope


@pytest.fixture(autouse=True)
def fresh():
    reseed_data()
    constants.set_cache({})


def eid(username):
    with session_scope() as db:
        return db.query(User).filter_by(username=username).one().entity_id


# ------------------------------------------------------------------ flow solver
def test_baseline_chain_is_balanced():
    with session_scope() as db:
        f = solve(db)
    assert f["ok"] and f["gaps"] == []


def test_extra_demand_travels_up_every_tier_and_converges():
    with session_scope() as db:
        base = solve(db)
        sp = eid("spinner1")
        sim = solve(db, extra_demand={sp: 1500})
    t0, t1 = {t["kind"]: t for t in base["tiers"]}, {t["kind"]: t for t in sim["tiers"]}
    for kind in ("reeler", "silkworm_farm", "mulberry_farm"):  # each tier is asked for more than before
        assert t1[kind]["requested_out"] > t0[kind]["requested_out"], kind
    assert t1["spinner"]["need_in"] > t0["spinner"]["need_in"]
    assert sim["gaps"] and sim["rounds"][-1]["spilled_kg"] <= 0.5     # settled: no more rerouting changes the numbers
    assert sim["rounds"][0]["spilled_kg"] > 0                         # shortfalls were re-asked from other suppliers first
    assert any(r["status"] in ("rerouted", "short") for r in sim["entities"])


def test_reeler_extra_orders_reach_farmers():
    with session_scope() as db:
        r = eid("reeler1")
        base = {t["kind"]: t for t in solve(db)["tiers"]}
        sim = {t["kind"]: t for t in solve(db, extra_demand={r: 600})["tiers"]}
    assert sim["silkworm_farm"]["requested_out"] > base["silkworm_farm"]["requested_out"]


def test_what_if_endpoint_saves_nothing(client, auth):
    sp = eid("spinner2")
    r = client.post("/api/flow/what-if", headers=auth("mf1"), json={"entity_id": sp, "qty": 800}).json()
    assert r["after"]["gaps"] and not r["before"]["gaps"]
    with session_scope() as db:
        assert db.query(Incident).count() == 0 and db.query(AgentEvent).count() == 0


# ------------------------------------------------------------------ the agent acts by itself
def test_new_demand_target_opens_incidents_without_anyone_pressing_a_button(client, auth):
    r = client.post("/api/target", headers=auth("spinner1"), json={"target_qty": 900, "horizon_days": 7})
    assert r.status_code == 200
    with session_scope() as db:
        ev = db.query(AgentEvent).filter_by(reason="target_set").one()
        assert ev.status == "done" and ev.result["opened"], ev.result
        kinds = {db.get(Entity, o["entity_id"]).kind for o in ev.result["opened"]}
    assert {"reeler", "silkworm_farm"} <= kinds or {"spinner", "reeler"} <= kinds
    act = client.get("/api/agent/activity", headers=auth("sf1")).json()
    assert act[0]["reason"] == "target_set" and act[0]["opened"]
    # offers went out to counterparties (they now have something to approve) - nothing executed
    with session_scope() as db:
        assert db.query(Deal).filter(Deal.status == "pending").count() > 0
        assert db.query(Deal).filter(Deal.status == "executed").count() == 0


def test_stock_drop_alerts_buyers_via_the_agent(client, auth):
    sf = auth("sf1")
    client.post("/api/stock", headers=sf, json={"product": "cocoon", "set_to": 5})
    with session_scope() as db:
        ev = db.query(AgentEvent).filter_by(reason="stock_changed").one()
        assert ev.status == "done"


# ------------------------------------------------------------------ both sides approve
def _pending(client, auth):
    r = client.post("/api/stock", headers=auth("reeler1"), json={"product": "cocoon", "set_to": 50}).json()
    return [d for d in client.get("/api/approvals", headers=auth("reeler1")).json()], r["incident"]["incident_id"]


def test_deal_needs_seller_and_buyer(client, auth):
    pend, iid = _pending(client, auth)
    d = pend[0]
    with session_scope() as db:
        row = db.get(Deal, d["id"])
        seller_user = db.query(User).filter_by(entity_id=row.seller_id).one().username
    # the seller was sent the offer by the agent and sees it in their own approvals
    assert any(x["id"] == d["id"] and x["my_side"] == "seller" for x in client.get("/api/approvals", headers=auth(seller_user)).json())
    # buyer approves first: still pending, nothing moves
    before = get_inv_of(d["seller"]["id"], "cocoon")
    r = client.post(f"/api/deals/{d['id']}/decision", headers=auth("reeler1"), json={"approve": True}).json()
    assert r["deal"]["status"] == "pending" and r["deal"]["buyer_decision"] == "approved" and not r["graph_resumed"]
    assert get_inv_of(d["seller"]["id"], "cocoon") == before
    # a second decision from the same side is refused
    assert client.post(f"/api/deals/{d['id']}/decision", headers=auth("reeler1"), json={"approve": False}).status_code == 409
    # seller approves: now it executes (once every deal of the incident is decided)
    ids = [x["id"] for x in pend]
    last = None
    for did in ids:
        with session_scope() as db:
            su = db.query(User).filter_by(entity_id=db.get(Deal, did).seller_id).one().username
        if did != d["id"]:
            client.post(f"/api/deals/{did}/decision", headers=auth("reeler1"), json={"approve": True})
        last = client.post(f"/api/deals/{did}/decision", headers=auth(su), json={"approve": True}).json()
    assert last["graph_resumed"] and last["deal"]["status"] == "executed"
    assert get_inv_of(d["seller"]["id"], "cocoon") < before


def get_inv_of(entity_id, product):
    with session_scope() as db:
        return get_inv(db, entity_id, product).on_hand


def test_either_side_can_decline_and_the_agent_finds_another_source(client, auth):
    pend, iid = _pending(client, auth)
    first_sellers = {d["seller"]["id"] for d in pend}
    victim = pend[0]
    with session_scope() as db:
        su = db.query(User).filter_by(entity_id=db.get(Deal, victim["id"]).seller_id).one().username
    # the seller declines; the other deals of the incident are declined by the buyer so the incident can finish
    out = None
    out = decide_deals(client, auth, [victim["id"]], approve=False, sides=("seller",))
    assert out["deal"]["status"] == "rejected"
    for d in pend[1:]:
        out = decide_deals(client, auth, [d["id"]], approve=False, sides=("buyer",))
    assert out["graph_resumed"]
    with session_scope() as db:
        assert get_inv(db, victim["seller"]["id"], "cocoon").reserved >= 0
        again = db.query(Deal).filter(Deal.id > max(d["id"] for d in pend), Deal.buyer_id == eid("reeler1"), Deal.product == "cocoon").all()
        evs = db.query(AgentEvent).filter_by(reason="deal_rejected").all()
    assert evs and all(e.status == "done" for e in evs)
    # the agent re-planned: new offers exist and none goes back to someone who already declined
    assert again and not ({d.seller_id for d in again} & first_sellers)
    notes = [n["message"] for n in client.get("/api/notifications", headers=auth("reeler1")).json()]
    assert any("declined" in m for m in notes)


# ------------------------------------------------------------------ the other direction: surplus -> buyers
def test_surplus_perishable_stock_is_offered_to_buyers_who_need_it(client, auth):
    mf, sf = eid("mf1"), eid("sf1")
    with session_scope() as db:  # a silkworm farm that is short of leaves, and a mulberry farm that holds far too many
        sinv = get_inv(db, sf, "leaves")
        sinv.on_hand, sinv.reserved = 150, 0
        minv = get_inv(db, mf, "leaves")
        minv.on_hand, minv.reserved = 4000, 0
        minv.daily_demand = 100
    client.post("/api/stock", headers=auth("mf1"), json={"product": "leaves", "set_to": 4100})
    with session_scope() as db:
        surplus = db.query(Incident).filter_by(entity_id=mf, kind="surplus").all()
        assert surplus, "the agent should offer spoiling leaves to buyers"
        deals = db.query(Deal).filter(Deal.incident_id.in_([i.id for i in surplus])).all()
    assert deals and all(d.seller_id == mf and d.status == "pending" for d in deals)
    assert all(d.seller_decision == d.buyer_decision == "pending" for d in deals)


# ------------------------------------------------------------------ live data with fallback
PAGE = """<table><tr><td>#</td><td>Markets</td><td>cb</td></tr>
<tr><td>1</td><td>Ramanagara</td><td>388</td><td>777</td><td>600</td></tr>
<tr><td>2</td><td>Kolara</td><td>488</td><td>683</td><td>640</td></tr></table>"""
RAW = """<table><tr><td>20/22</td><td>5540</td><td>5600</td><td>5600</td></tr>
<tr><td>Multiend Silk</td><td>15-10-2026</td><td>5580</td><td>5650</td><td>5700</td></tr></table>"""


def test_live_prices_update_and_fall_back(monkeypatch):
    from app.refresh import live_data as L
    monkeypatch.setattr(L, "_get", lambda url: PAGE if url == L.COCOON_URL else RAW)
    rep = L.refresh(force=True)
    assert constants.price("cocoon") == 620.0 and constants.price("yarn") == 5600.0 and constants.price("thread") == 5700.0
    assert rep["price_cocoon"].startswith("updated")
    with session_scope() as db:
        assert {i.unit_price for i in db.query(Inventory).filter_by(product="cocoon")} == {620.0}
    # the source goes down: last good values stay
    monkeypatch.setattr(L, "_get", lambda url: (_ for _ in ()).throw(RuntimeError("offline")))
    rep = L.refresh(force=True)
    assert all(v.startswith("kept last good") for v in rep.values()) and constants.price("cocoon") == 620.0
    # an absurd value is rejected, not stored
    monkeypatch.setattr(L, "_get", lambda url: PAGE.replace("600", "60000").replace("640", "60000") if url == L.COCOON_URL else RAW)
    rep = L.refresh(force=True)
    assert "rejected" in rep["price_cocoon"] and constants.price("cocoon") == 620.0


def test_defaults_apply_when_nothing_was_ever_fetched():
    assert constants.price("cocoon") == constants.DEFAULTS["price_cocoon"][0]
    snap = {c["name"]: c for c in constants.snapshot()}
    assert snap["price_cocoon"]["source"] == "built-in default" and not snap["price_cocoon"]["live"]


# ------------------------------------------------------------------ background run: the request returns at once
def test_chat_returns_immediately_and_finishes_in_the_background(client, auth, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "run_mode", "async")
    h = auth("sf2")
    r = client.post("/api/chat", headers=h, data={"message": "my larvae are restless with milky fluid"}).json()
    assert r["status"] == "running"
    for _ in range(120):
        cur = client.get(f"/api/incidents/{r['id']}", headers=h).json()
        if cur["status"] != "running":
            break
        time.sleep(0.5)
    assert cur["status"] != "running" and cur["trace"]
