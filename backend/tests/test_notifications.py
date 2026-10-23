"""Affected partners are alerted the moment an incident is assessed - at every tier."""
import json
from pathlib import Path

import pytest

from app.db.seed import reseed_data
from app.db.models import Entity, Incident, Notification, User
from app.db.session import session_scope

IMG = Path(__file__).resolve().parents[2] / "data" / "images"


@pytest.fixture(autouse=True)
def fresh():
    reseed_data()


def notes_for(username):
    with session_scope() as db:
        eid = db.query(User).filter_by(username=username).one().entity_id
        return [(n.level, n.message, n.incident_id) for n in db.query(Notification).filter_by(entity_id=eid)]


def users_of(kind, names):
    with session_scope() as db:
        return [db.query(User).filter_by(entity_id=e.id).one().username
                for e in db.query(Entity).filter(Entity.kind == kind, Entity.name.in_(names))]


def user_of(entity_id):
    with session_scope() as db:
        return db.query(User).filter_by(entity_id=entity_id).one().username


def photo(client, auth, user, image, pct):
    return client.post("/api/chat", headers=auth(user), data={"message": "x", "fields": json.dumps({"affected_pct": pct})},
                       files={"image": (image, open(IMG / image, "rb"), "image/jpeg")}).json()


def test_mulberry_issue_alerts_the_silkworm_farmers_it_supplies(client, auth):
    inc = photo(client, auth, "mf2", "leaf_blight_sample.jpg", 100)
    buyers = [a["entity_id"] for a in inc["payload"]["supply_impact"]["affected"]]
    assert buyers
    for u in map(user_of, buyers):
        got = notes_for(u)
        assert got and got[0][0] in ("alert", "warning") and "Upstream alert" in got[0][1] and "leaf blight" in got[0][1]
        assert got[0][2] == inc["id"]


def test_mild_issue_still_alerts_with_a_warning_not_silence(client, auth):
    inc = photo(client, auth, "mf1", "powdery_mildew_sample.jpg", 8)
    for a in inc["payload"]["supply_impact"]["affected"]:
        u = user_of(a["entity_id"])
        assert any("powdery mildew" in m for _, m, _ in notes_for(u))


def test_silkworm_issue_alerts_reelers(client, auth):
    inc = photo(client, auth, "sf1", "grasserie_sample.jpg", 90)
    for a in inc["payload"]["supply_impact"]["affected"]:
        u = user_of(a["entity_id"])
        assert any("grasserie" in m and "Upstream alert" in m for _, m, _ in notes_for(u))


def test_reeler_incident_alerts_its_spinners(client, auth):
    inc = client.post("/api/chat", headers=auth("reeler1"), data={"message": "breakdown", "fields": json.dumps(
        {"incident_type": "low_yarn_output", "reduction_pct": 90, "duration_days": 14})}).json()
    ids = [a["entity_id"] for a in inc["payload"]["supply_impact"]["affected"]]
    assert ids
    for u in map(user_of, ids):
        assert any("low yarn output" in m for _, m, _ in notes_for(u))


def test_spinner_request_alerts_the_reelers_it_would_buy_from(client, auth):
    inc = client.post("/api/chat", headers=auth("spinner1"), data={"message": "surge", "fields": json.dumps(
        {"target_qty": 800, "horizon_days": 7})}).json()
    for a in inc["payload"]["supply_impact"]["affected"]:
        u = user_of(a["entity_id"])
        assert any("Incoming request" in m for _, m, _ in notes_for(u))


def test_no_alert_for_healthy_or_questions(client, auth):
    photo(client, auth, "mf1", "healthy_leaf.jpg", 20)
    client.post("/api/chat", headers=auth("sf1"), data={"message": "how should cocoons be stored?"})
    with session_scope() as db:
        assert db.query(Notification).count() == 0


def test_silkworm_farmer_sees_his_reelers_by_name(client, auth):
    inc = photo(client, auth, "sf1", "grasserie_sample.jpg", 90)
    assert all(a["name"].startswith("Reeling Unit") for a in inc["payload"]["supply_impact"]["affected"])


def test_mulberry_farmer_cannot_learn_downstream_identities(client, auth):
    """Data visibility: a mulberry farmer sees only his own farm, so partners in his incident are anonymised."""
    inc = photo(client, auth, "mf2", "leaf_blight_sample.jpg", 100)
    blob = json.dumps(inc["payload"])
    with session_scope() as db:
        names = [e.name for e in db.query(Entity).filter(Entity.kind.in_(["silkworm_farm", "reeler", "spinner"]))]
        other_mf = [e.name for e in db.query(Entity).filter(Entity.kind == "mulberry_farm") if e.id != inc["entity_id"]]
    for n in names + other_mf:
        assert f'"{n}"' not in blob, f"{n} leaked to the mulberry farmer"
    assert inc["payload"]["hidden_partners"] >= 1
    assert client.get("/api/deals", headers=auth("mf2")).json() == []   # the buyers' deals belong to the buyers
    lin = client.get(f"/api/incidents/{inc['id']}", headers=auth("mf2")).json()["lineage"]
    assert lin["children"] == [] and lin["hidden_children"] >= 1


def test_supplier_issue_opens_a_full_incident_for_each_buyer(client, auth):
    """1 alert, 2 alternatives calculated, 3 deals proposed, 4 buyer approves - without the buyer doing anything."""
    from app.calc.impact import get_inv
    inc = photo(client, auth, "mf3", "leaf_blight_sample.jpg", 100)
    assert inc["status"] == "advised"  # the supplier's own incident needs no approvals
    with session_scope() as db:
        kids = db.query(Incident).filter(Incident.parent_id == inc["id"]).all()
        kid_info = [(k.id, db.query(User).filter_by(entity_id=k.entity_id).one().username, k.kind, k.status, k.priority) for k in kids]
    assert len(kid_info) >= 2
    for cid, buyer, kind, status, prio in kid_info:
        assert kind == "low_stock" and status == "awaiting_approval" and prio in ("P1", "P2", "P3")
        h = auth(buyer)
        msgs = [n["message"] for n in client.get("/api/notifications", headers=h).json()]
        assert any("Upstream alert" in m for m in msgs)                                          # 1. alert
        assert any("alternative source" in m and "Route:" in m and "truck" in m for m in msgs)   # 2. alternatives + routing
        pend = client.get("/api/approvals", headers=h).json()
        assert pend and all(d["can_decide"] and d["route"]["routes"] and d["incident_id"] == cid for d in pend)  # 3. deals
        detail = client.get(f"/api/incidents/{cid}", headers=h).json()
        assert detail["lineage"]["parent"]["id"] == inc["id"]
    cid, buyer, *_ = kid_info[0]
    h = auth(buyer)
    with session_scope() as db:
        eid = db.query(User).filter_by(username=buyer).one().entity_id
        before = get_inv(db, eid, "leaves").on_hand
    for d in client.get("/api/approvals", headers=h).json():                                      # 4. approve
        out = client.post(f"/api/deals/{d['id']}/decision", headers=h, json={"approve": True}).json()
    assert out["graph_resumed"]
    with session_scope() as db:
        assert get_inv(db, eid, "leaves").on_hand > before


def test_supplier_stock_drop_alerts_and_serves_buyers_too(client, auth):
    r = client.post("/api/stock", headers=auth("mf3"), json={"product": "leaves", "set_to": 100}).json()
    assert r["buyer_incidents"], "a big drop in a supplier's stock must open incidents for its buyers"
    for k in r["buyer_incidents"]:
        with session_scope() as db:
            u = db.query(User).filter_by(entity_id=k["entity_id"]).one().username
        assert client.get("/api/approvals", headers=auth(u)).json()


def test_buyer_dashboard_outlook_reflects_supplier_disease(client, auth):
    before = client.get("/api/dashboard", headers=auth("sf3")).json()["me"]["outlook"][0]
    assert before["expected_loss"] == 0 and before["status"] == "ok"
    photo(client, auth, "mf1", "leaf_blight_sample.jpg", 100)
    after = client.get("/api/dashboard", headers=auth("sf3")).json()["me"]["outlook"][0]
    assert after["expected_loss"] > 0 and after["projected"] < before["projected"]
    assert any(s["loss_pct"] > 0 and s["incident_id"] for s in after["suppliers"])


def test_marking_supplier_incident_recovered_clears_the_outlook(client, auth):
    inc = photo(client, auth, "mf1", "leaf_blight_sample.jpg", 100)
    assert client.post(f"/api/incidents/{inc['id']}/close", headers=auth("mf1")).json()["status"] == "closed"
    sups = client.get("/api/dashboard", headers=auth("sf3")).json()["me"]["outlook"][0]["suppliers"]
    assert all(s["loss_pct"] == 0 and s["incident_id"] is None for s in sups)   # the disease no longer counts downstream
    assert client.post(f"/api/incidents/{inc['id']}/close", headers=auth("mf2")).status_code == 404


def test_reeler_outage_opens_incidents_for_spinners(client, auth):
    inc = client.post("/api/chat", headers=auth("reeler1"), data={"message": "x", "fields": json.dumps(
        {"incident_type": "low_yarn_output", "reduction_pct": 100, "duration_days": 21})}).json()
    kids = inc["payload"]["outcome"]["children"]
    assert kids and all(k["product"] == "yarn" for k in kids)
    with session_scope() as db:
        assert all(db.get(Incident, k["incident_id"]).parent_id == inc["id"] for k in kids)
