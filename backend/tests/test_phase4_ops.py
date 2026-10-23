import json


def chat(client, headers, message="", fields=None):
    r = client.post("/api/chat", headers=headers, data={"message": message, "fields": json.dumps(fields or {})})
    assert r.status_code == 200, r.text
    return r.json()


def test_reeler_low_yarn_identifies_affected_spinners(client, auth):
    inc = chat(client, auth("reeler1"), "factory machine breakdown, output down", {"incident_type": "low_yarn_output", "reduction_pct": 80, "duration_days": 14})
    p = inc["payload"]
    assert inc["kind"] == "low_yarn" and inc["is_issue"]
    imp = p["supply_impact"]
    assert imp["n_affected"] >= 1 and imp["total_need"] > 0
    assert all("allocated" in a for a in imp["affected"])
    assert inc["priority"] in {"P1", "P2", "P3", "P4"}
    assert p["advisory"]["mitigation_steps"]
    # allocation never exceeds deliverable, and never exceeds a spinner's need
    assert sum(a["allocated"] for a in imp["affected"]) <= imp["deliverable"] + 0.2
    assert all(a["allocated"] <= a["need"] + 0.1 for a in imp["affected"])


def test_reeler_small_issue_has_no_shortfall(client, auth):
    inc = chat(client, auth("reeler2"), "small delay", {"incident_type": "delivery_delay", "delay_days": 1, "quantity_kg": 1})
    imp = inc["payload"]["supply_impact"]
    assert imp["total_shortfall"] == 0 and imp["at_risk"] is False
    assert inc["priority"] in ("P4", "P3")


def test_reeler_cocoon_shortage_creates_upstream_case(client, auth):
    inc = chat(client, auth("reeler3"), "not enough cocoon supply", {"incident_type": "cocoon_shortage", "quantity_kg": 3000, "duration_days": 10})
    cases = inc["payload"]["supply_impact"]["needs"]
    assert any(c["product"] == "cocoon" and c["direction"] == "upstream" for c in cases)


def test_spinner_target_gap(client, auth):
    big = chat(client, auth("spinner1"), "demand surge", {"target_qty": 5000, "horizon_days": 7})
    imp = big["payload"]["supply_impact"]
    assert imp["gap"] > 0 and imp["at_risk"] and imp["needs"][0]["product"] == "yarn"
    assert big["kind"] == "demand_surge" and big["priority"] in ("P1", "P2")
    small = chat(client, auth("spinner2"), "need a bit more yarn", {"target_qty": 5, "horizon_days": 30})
    assert small["payload"]["supply_impact"]["gap"] == 0
    # target is persisted
    assert client.get("/api/target", headers=auth("spinner1")).json()["target_qty"] == 5000
    client.post("/api/target", headers=auth("spinner1"), json={"target_qty": 300})


def test_text_only_reeler_inference(client, auth):
    inc = chat(client, auth("reeler1"), "delivery delayed by 5 days, stuck at transport")
    assert inc["kind"] == "delay"


def test_ops_roles_can_still_ask_questions(client, auth):
    q = chat(client, auth("reeler1"), "how should raw silk yarn be stored?")
    assert q["is_issue"] is False and q["payload"]["advisory"]["type"] == "answer"
