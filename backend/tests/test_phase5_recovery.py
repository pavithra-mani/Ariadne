import json

import pytest

from sqlalchemy import func

from app.calc.impact import get_inv
from app.config import settings
from app.db.models import AuditLog, Deal, Entity, Ledger
from app.db.seed import reseed_data
from app.db.session import session_scope


@pytest.fixture(scope="module", autouse=True)
def clean_slate():
    """Earlier phases leave pending proposals that (correctly) hold stock; start recovery tests fresh."""
    reseed_data()


def report(client, headers, fields, message="demand surge"):
    r = client.post("/api/chat", headers=headers, data={"message": message, "fields": json.dumps(fields)})
    assert r.status_code == 200, r.text
    return r.json()


def snapshot(entity_ids, product="yarn"):
    with session_scope() as db:
        return {i: {"stock": get_inv(db, i, product).on_hand, "balance": db.get(Entity, i).balance} for i in entity_ids}


def gap_target(client, h, extra):
    """Target that exceeds what the spinner's own stock and linked reelers can give by `extra` kg."""
    probe = report(client, h, {"target_qty": 1, "horizon_days": 7})["payload"]["supply_impact"]
    return round(probe["own_buffer"] + probe["linked_supply"] + extra, 1)


def deal_parties(deal_ids):
    with session_scope() as db:
        return {d.id: (d.seller_id, d.buyer_id, d.quantity, d.unit_price + d.transport_cost / d.quantity, d.status)
                for d in db.query(Deal).filter(Deal.id.in_(deal_ids))}


def test_surge_pauses_for_human_then_executes_ledger(client, auth):
    h = auth("spinner1")
    inc = report(client, h, {"target_qty": gap_target(client, h, 60), "horizon_days": 7})
    assert inc["status"] == "awaiting_approval"
    # nothing changed in the ledger before approval
    with session_scope() as db:
        assert db.query(func.count(Ledger.id)).filter(Ledger.deal_id.isnot(None)).scalar() == 0
    plans = inc["payload"]["plans"][0]
    assert plans["deals"] and len(plans["attempts"]) <= settings.max_searches
    pend = client.get("/api/approvals", headers=h).json()
    assert {d["id"] for d in pend} == set(plans["deals"]) and all(d["can_decide"] for d in pend)
    assert all(d["route"]["routes"] for d in pend)  # OR-Tools route attached
    parties = deal_parties(plans["deals"])
    ids = {i for p in parties.values() for i in p[:2]}
    before = snapshot(ids)
    out = None
    for d in pend:
        out = client.post(f"/api/deals/{d['id']}/decision", headers=h, json={"approve": True}).json()
    assert out["graph_resumed"] is True
    after = snapshot(ids)
    buyer = next(iter(parties.values()))[1]
    got = sum(p[2] for p in parties.values())
    assert abs((after[buyer]["stock"] - before[buyer]["stock"]) - got) < 0.01
    spent = sum(p[2] * p[3] for p in parties.values())
    assert before[buyer]["balance"] - after[buyer]["balance"] > 0
    # money is conserved apart from the transport cost paid out of the system
    total_before = sum(v["balance"] for v in before.values())
    total_after = sum(v["balance"] for v in after.values())
    assert total_before - total_after > 0 and total_before - total_after < spent * 0.2
    final = client.get(f"/api/incidents/{inc['id']}", headers=h).json()
    assert final["status"] in ("resolved", "partially_resolved")
    assert {t["node"] for t in final["trace"]} >= {"deal_rerouting", "notification", "finalize"}
    with session_scope() as db:
        assert db.query(AuditLog).filter(AuditLog.action == "deal_executed").count() == len(plans["deals"])
    # buyer sees ledger lines + both parties are notified
    assert any(r["deal_id"] for r in client.get("/api/ledger", headers=h).json())
    assert client.get("/api/notifications", headers=auth("reeler1")).status_code == 200


def test_rejected_deal_changes_nothing(client, auth):
    h = auth("spinner2")
    inc = report(client, h, {"target_qty": gap_target(client, h, 60), "horizon_days": 7})
    assert inc["status"] == "awaiting_approval"
    deals = inc["payload"]["plans"][0]["deals"]
    parties = deal_parties(deals)
    ids = {i for p in parties.values() for i in p[:2]}
    before = snapshot(ids)
    for d in deals:
        out = client.post(f"/api/deals/{d}/decision", headers=h, json={"approve": False}).json()
    assert out["incident"]["status"] == "rejected"
    assert snapshot(ids) == before
    with session_scope() as db:
        for d in deals:
            inv = get_inv(db, parties[d][0], "yarn")
            assert inv.reserved >= 0
    # decision is final
    assert client.post(f"/api/deals/{deals[0]}/decision", headers=h, json={"approve": True}).status_code == 409


def test_only_the_approver_can_decide(client, auth):
    h = auth("spinner3")
    inc = report(client, h, {"target_qty": gap_target(client, h, 60), "horizon_days": 7})
    if inc["status"] != "awaiting_approval":
        return
    d = inc["payload"]["plans"][0]["deals"][0]
    assert client.post(f"/api/deals/{d}/decision", headers=auth("spinner1"), json={"approve": True}).status_code == 404
    assert client.post(f"/api/deals/{d}/decision", headers=auth("mf1"), json={"approve": True}).status_code == 404


def test_search_is_bounded_and_unsourceable_demand_escalates(client, auth):
    inc = report(client, auth("spinner4"), {"target_qty": 90000, "horizon_days": 7})
    searches = [t for t in inc["trace"] if t["node"] == "alternative_sources"]
    assert 1 <= len(searches) <= settings.max_searches
    plan = inc["payload"]["plans"][0]
    assert plan["status"] in ("partial", "unresolved")
    assert inc["payload"]["outcome"]["unresolved"]
    assert inc["status"] in ("awaiting_approval", "escalated")


def test_farmer_incident_triggers_upstream_recovery_for_reeler(client, auth):
    # grasserie across a silkworm farm hits its reelers; recovery searches alternative farmers
    from pathlib import Path
    img = Path(__file__).resolve().parents[2] / "data" / "images" / "grasserie_sample.jpg"
    r = client.post("/api/chat", headers=auth("sf1"), data={"message": "outbreak", "fields": json.dumps({"affected_pct": 90})},
                    files={"image": ("grasserie.jpg", open(img, "rb"), "image/jpeg")}).json()
    imp = r["payload"]["supply_impact"]
    if imp["at_risk"]:
        assert all(c["product"] == "cocoon" and c["direction"] == "upstream" for c in imp["cases"])
        children = r["payload"]["outcome"]["children"]
        assert children and all(c["product"] == "cocoon" for c in children)
        for c in children:
            with session_scope() as db:
                for dd in db.query(Deal).filter(Deal.incident_id == c["incident_id"]):
                    assert dd.deal_type == "farmer_reeler" and db.get(Entity, dd.seller_id).kind == "silkworm_farm"
    assert r["status"] == "advised"


# ------------------------------------------------------------------ phase 6: cascade & hardening
def _first_pending_incident(client, h):
    return client.get("/api/approvals", headers=h).json()


def test_reeler_failure_opens_buyer_incidents_with_lineage(client, auth):
    reseed_data()
    h = auth("reeler2")
    inc = report(client, h, {"incident_type": "low_yarn_output", "reduction_pct": 100, "duration_days": 21}, "plant shut")
    children = (inc["payload"].get("outcome") or {}).get("children", [])
    assert children, "spinners that cannot absorb the outage get their own incidents"
    kid = children[0]["incident_id"]
    with session_scope() as db:
        from app.db.models import Incident, User
        child = db.get(Incident, kid)
        spinner_user = db.query(User).filter(User.entity_id == child.entity_id).first().username
        assert child.parent_id == inc["id"] and child.role == "spinner" and child.kind == "low_stock"
    sp = client.get(f"/api/incidents/{kid}", headers=auth(spinner_user)).json()
    assert sp["lineage"]["parent"]["id"] == inc["id"]
    assert any(c["id"] == kid for c in client.get(f"/api/incidents/{inc['id']}", headers=h).json()["lineage"]["children"])


def test_mulberry_cascade_hides_unseen_children(client, auth):
    from pathlib import Path
    img = Path(__file__).resolve().parents[2] / "data" / "images" / "leaf_blight_sample.jpg"
    r = client.post("/api/chat", headers=auth("mf1"), data={"message": "blight everywhere", "fields": json.dumps({"affected_pct": 100})},
                    files={"image": ("leaf_blight.jpg", open(img, "rb"), "image/jpeg")}).json()
    lin = client.get(f"/api/incidents/{r['id']}", headers=auth("mf1")).json()["lineage"]
    # a mulberry farmer may never see silkworm farms' incidents, only a count
    assert lin["children"] == []


def test_graph_failure_marks_incident_error_not_stuck(client, auth, monkeypatch):
    from app.graph import nodes
    monkeypatch.setattr(nodes, "agentic_rag", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("chroma down")))
    # the compiled graph captured the original function; call the runner with a broken graph instead
    from app.graph import runtime
    class Boom:
        def invoke(self, *a, **k): raise RuntimeError("boom")
    monkeypatch.setattr(runtime, "_graph", Boom())
    r = client.post("/api/chat", headers=auth("sf2"), data={"message": "worms are dying"})
    assert r.status_code == 200 and r.json()["status"] == "error"


def test_system_status(client, auth):
    s = client.get("/api/system/status", headers=auth("sf1")).json()
    assert s["knowledge_chunks"] > 0 and s["max_searches"] == 5 and s["classifiers"]["silkworm"] in ("stub", "model")


def test_demo_reset_is_guarded(client, auth, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "allow_demo_reset", False)
    assert client.post("/api/system/reset-demo", headers=auth("mf1")).status_code == 403
    monkeypatch.setattr(settings, "allow_demo_reset", True)
    assert client.post("/api/system/reset-demo", headers=auth("mf1")).json() == {"ok": True}
    assert client.get("/api/incidents", headers=auth("mf1")).json() == []
