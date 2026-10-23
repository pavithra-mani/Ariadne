"""A product pushed to its reorder point / safety stock makes Ariadne act by itself."""
import json

import pytest

from app.calc.impact import get_inv
from app.db.models import Deal, Entity, Notification, User
from app.db.seed import reseed_data
from app.db.session import session_scope


@pytest.fixture(autouse=True)
def fresh():
    reseed_data()


def inv_of(username, product):
    with session_scope() as db:
        eid = db.query(User).filter_by(username=username).one().entity_id
        i = get_inv(db, eid, product)
        return {"on_hand": i.on_hand, "balance": db.get(Entity, eid).balance, "eid": eid}


def test_reeler_cocoon_critical_opens_incident_with_deals_to_approve(client, auth):
    h = auth("reeler1")
    r = client.post("/api/stock", headers=h, json={"product": "cocoon", "set_to": 50}).json()
    assert r["status"] == "critical" and r["incident"]["status"] == "awaiting_approval"
    assert r["incident"]["pending_deals"] >= 1 and not r["incident"]["existing"]
    inc = client.get(f"/api/incidents/{r['incident']['incident_id']}", headers=h).json()
    assert inc["kind"] == "low_stock" and inc["priority"] in ("P1", "P2")
    imp = inc["payload"]["supply_impact"]
    assert imp["order_qty"] > 500 and imp["needs"][0]["product"] == "cocoon"
    names = [t["node"] for t in inc["trace"]]
    assert names[:3] == ["intake", "triage_supervisor", "stock_monitor_agent"] and "routing_ortools" in names
    # the reeler himself approves his own purchase from the silkworm farmers
    pend = client.get("/api/approvals", headers=h).json()
    assert pend and all(d["product"] == "cocoon" and d["can_decide"] and d["seller"]["name"].startswith("SF-") for d in pend)
    assert all(d["route"]["routes"] for d in pend)
    before = inv_of("reeler1", "cocoon")
    for d in pend:
        out = client.post(f"/api/deals/{d['id']}/decision", headers=h, json={"approve": True}).json()
    assert out["graph_resumed"]
    after = inv_of("reeler1", "cocoon")
    bought = sum(d["quantity"] for d in pend)
    assert abs(after["on_hand"] - before["on_hand"] - bought) < 0.01 and after["balance"] < before["balance"]
    assert client.get(f"/api/incidents/{inc['id']}", headers=h).json()["status"] in ("resolved", "partially_resolved")
    # the farmers who sold are told
    with session_scope() as db:
        sellers = {d.seller_id for d in db.query(Deal).filter(Deal.incident_id == inc["id"])}
        assert db.query(Notification).filter(Notification.entity_id.in_(sellers), Notification.level == "deal").count() >= len(sellers)


def test_no_duplicate_incident_while_one_is_open(client, auth):
    h = auth("reeler2")
    a = client.post("/api/stock", headers=h, json={"product": "cocoon", "set_to": 40}).json()
    again = client.post("/api/stock/cocoon/replenish", headers=h).json()
    assert again["existing"] is True and again["incident_id"] == a["incident"]["incident_id"]


def test_healthy_stock_has_nothing_to_fix(client, auth):
    r = client.post("/api/stock/cocoon/replenish", headers=auth("reeler3"))
    assert r.status_code == 400
    ok = client.post("/api/stock", headers=auth("reeler3"), json={"product": "cocoon", "delta": 10}).json()
    assert "incident" not in ok


def test_low_finished_goods_alerts_buyers_and_resources_their_shortfall(client, auth):
    h = auth("reeler1")
    r = client.post("/api/stock", headers=h, json={"product": "yarn", "set_to": 5}).json()
    assert r["status"] == "critical" and r["incident"]["incident_id"]
    inc = client.get(f"/api/incidents/{r['incident']['incident_id']}", headers=h).json()
    imp = inc["payload"]["supply_impact"]
    assert imp["finished"] and imp["n_affected"] >= 1
    with session_scope() as db:
        notes = db.query(Notification).filter_by(incident_id=inc["id"]).all()
        assert any("running low on yarn" in n.message for n in notes)


def test_free_text_low_stock_message_is_recognised(client, auth):
    r = client.post("/api/chat", headers=auth("reeler4"), data={"message": "my cocoon stock is critical", "fields": "{}"}).json()
    assert r["kind"] == "low_stock" and r["payload"]["finding"]["product"] == "cocoon"


def test_farmers_and_spinners_get_the_same_behaviour(client, auth):
    for user, product in (("sf2", "leaves"), ("spinner1", "yarn")):
        r = client.post("/api/stock", headers=auth(user), json={"product": product, "set_to": 3}).json()
        assert r["incident"]["incident_id"], user
        inc = client.get(f"/api/incidents/{r['incident']['incident_id']}", headers=auth(user)).json()
        assert inc["kind"] == "low_stock" and inc["payload"]["supply_impact"]["order_qty"] > 0
