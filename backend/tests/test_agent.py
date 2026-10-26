"""The guardian as an agent: tool choice, guardrails, replanning after a decline, memory, rules fallback.

A scripted `PolicyLLM` stands in for the model: it looks at what each tool RETURNED and decides the next call, the way
the real model does, so these tests exercise the loop, the tools and the safety envelope without a network. (How good the
real model's choices are is measured separately by `python -m app.eval.agentic_eval`.)"""
import pytest
from conftest import decide_deals

from app import constants
from app.config import settings
from app.db.models import AgentEvent, AgentNote, Deal, Entity, Inventory, Notification, User
from app.db.seed import reseed_data
from app.db.session import session_scope
from app.llm.provider import AgentRun, LLMUnavailable, set_llm_override, spend


class PolicyLLM:
    """tool_loop(...) drives `policy(history, tools)`: it returns (tool_name, kwargs) or None to stop."""
    name = "policy"

    def __init__(self, policy):
        self.policy, self.calls = policy, 0

    def generate_json(self, *a, **k):
        raise LLMUnavailable("json not scripted")

    def tool_loop(self, system, user, tools, purpose, max_steps):
        reg = {f.__name__: f for f in tools}
        run = AgentRun(text="done", calls=0)
        hist = [{"events": user}]
        for _ in range(max_steps):
            spend(purpose)
            nxt = self.policy(hist, reg)
            run.calls += 1
            if nxt is None:
                break
            name, kw = nxt
            out = reg[name](**kw)
            hist.append({"tool": name, "args": kw, "out": out})
            run.steps.append({"tool": name, "args": kw})
        return run


@pytest.fixture(autouse=True)
def fresh():
    reseed_data()
    constants.set_cache({})
    settings.guardian_mode = "auto"
    yield
    settings.guardian_mode = "auto"
    set_llm_override(None)


def uid(name):
    with session_scope() as db:
        return db.query(User).filter_by(username=name).one().entity_id


def last(hist, tool):
    return next((h["out"] for h in reversed(hist) if h.get("tool") == tool), None)


def sourcing_policy(hist, reg):
    """status -> take the biggest gap -> find vendors -> offer to the first -> verify -> stop."""
    st = last(hist, "get_network_status")
    if st is None:
        return "get_network_status", {}
    gaps = [g for g in st["gaps"] if g["already_offered_kg"] < g["short_linked"] - 1] or [{"entity_id": l["entity_id"], "product": l["product"], "short_linked": 0} for l in st["low_stock"] if l["entity_id"] == uid("reeler1")]
    if not gaps:
        return None
    g = gaps[0]
    fv = next((h["out"] for h in reversed(hist) if h.get("tool") == "find_vendors" and h["args"]["entity_id"] == g["entity_id"] and h["args"]["product"] == g["product"]), None)
    if fv is None:
        return "find_vendors", {"entity_id": g["entity_id"], "product": g["product"], "direction": "buy", "qty_kg": max(g["short_linked"], 50.0), "strategy": "nearest", "max_km": 80}
    offers = [h for h in hist if h.get("tool") == "propose_offer"]
    if len(offers) < 2 and len(offers) < len(fv.get("vendors", [])):
        v = fv["vendors"][len(offers)]
        return "propose_offer", {"buyer_id": g["entity_id"], "seller_id": v["entity_id"], "product": g["product"], "qty_kg": min(v["can_trade_kg"], max(g["short_linked"], 50.0))}
    if last(hist, "verify_coverage") is None:
        return "verify_coverage", {"entity_id": g["entity_id"], "product": g["product"]}
    return None


def test_agent_chooses_tools_and_proposes_offers_without_moving_stock(client, auth):
    set_llm_override(PolicyLLM(sourcing_policy))
    h = auth("reeler1")
    client.post("/api/stock", headers=h, json={"product": "cocoon", "set_to": 60})
    with session_scope() as db:
        ev = db.query(AgentEvent).filter_by(reason="stock_changed").one()
        r = ev.result
        assert r["mode"] == "agent" and r["steps"] and r["steps"][0]["tool"] == "get_network_status"
        deals = db.query(Deal).filter(Deal.origin == "agent").all()
        assert deals and all(d.status == "pending" and d.incident_id is None for d in deals)
        assert sum(1 for s in r["steps"] if s["tool"] == "propose_offer" and "deal_id" in s["result"]) == len(deals)
        assert db.query(Deal).filter(Deal.status == "executed").count() == 0   # proposal-only
    assert {s["tool"] for s in r["steps"]} >= {"get_network_status", "find_vendors", "propose_offer", "verify_coverage"}


def test_both_sides_must_approve_an_agent_deal_then_it_executes(client, auth):
    set_llm_override(PolicyLLM(sourcing_policy))
    client.post("/api/stock", headers=auth("reeler1"), json={"product": "cocoon", "set_to": 60})
    with session_scope() as db:
        d = db.query(Deal).filter(Deal.origin == "agent").first()
        did, seller, buyer, qty = d.id, d.seller_id, d.buyer_id, d.quantity
        before = db.query(Inventory).filter_by(entity_id=buyer, product="cocoon").one().on_hand
    out = decide_deals(client, auth, [did], sides=("buyer",))
    assert out["deal"]["status"] == "pending"
    out = decide_deals(client, auth, [did], sides=("seller",))
    assert out["deal"]["status"] == "executed"
    with session_scope() as db:
        assert abs(db.query(Inventory).filter_by(entity_id=buyer, product="cocoon").one().on_hand - before - qty) < 0.01


def test_guardrails_clamp_quantities_and_refuse_bad_proposals(client, auth):
    seen = {}

    def greedy(hist, reg):
        n = len(hist)
        r, s = uid("reeler1"), uid("sf1")
        if n == 1:
            return "propose_offer", {"buyer_id": r, "seller_id": s, "product": "cocoon", "qty_kg": 99999}      # absurd size
        if n == 2:
            seen["big"] = hist[-1]["out"]
            return "propose_offer", {"buyer_id": s, "seller_id": r, "product": "cocoon", "qty_kg": 10}        # wrong direction of trade
        if n == 3:
            seen["wrong"] = hist[-1]["out"]
            return "propose_offer", {"buyer_id": 99999, "seller_id": s, "product": "cocoon", "qty_kg": 10}    # unknown party
        seen["unknown"] = hist[-1]["out"]
        return None
    client.post("/api/stock", headers=auth("reeler1"), json={"product": "cocoon", "set_to": 600})  # healthy: no real need
    reseed_data()
    set_llm_override(PolicyLLM(greedy))
    client.post("/api/stock", headers=auth("reeler2"), json={"product": "cocoon", "set_to": 1200})
    assert "error" in seen["big"] and "nothing to offer" in seen["big"]["error"]      # buyer has no real need -> refused, not obeyed
    assert "error" in seen["wrong"] and "error" in seen["unknown"]
    with session_scope() as db:
        assert db.query(Deal).count() == 0
        assert db.query(AgentEvent).filter_by(reason="stock_changed").one().result["invalid_tool_calls"] == 3


def test_decline_triggers_replanning_with_memory_and_never_reoffers_the_decliner(client, auth):
    set_llm_override(PolicyLLM(sourcing_policy))
    client.post("/api/stock", headers=auth("reeler1"), json={"product": "cocoon", "set_to": 60})
    with session_scope() as db:
        first = db.query(Deal).filter(Deal.origin == "agent").order_by(Deal.id).all()
        victim = first[0]
        vid, v_seller = victim.id, victim.seller_id
        seller_user = db.query(User).filter_by(entity_id=v_seller).one().username
    n_before = len(first)
    # the seller declines with a reason; the agent is woken by that event and re-plans
    r = client.post(f"/api/deals/{vid}/decision", headers=auth(seller_user), json={"approve": False, "reason": "my cocoons are promised to another buyer"})
    assert r.status_code == 200
    with session_scope() as db:
        ev = db.query(AgentEvent).filter_by(reason="deal_rejected").one()
        assert ev.status == "done" and ev.result["mode"] == "agent"
        again = db.query(Deal).filter(Deal.origin == "agent", Deal.id > max(d.id for d in first)).all()
        assert again, "the agent should have sent a replacement offer by itself"
        assert v_seller not in {d.seller_id for d in again}                        # the decliner is not offered the trade again
    # the decline reason is part of what the agent can recall about that vendor
    rec = PolicyLLM(lambda hist, reg: ("recall_memory", {"entity_id": v_seller}) if len(hist) == 1 else None)
    set_llm_override(rec)
    from app.agents.guardian_agent import Episode, build_tools
    ep = Episode(event_ids=[])
    out = {f.__name__: f for f in build_tools(ep)}["recall_memory"](entity_id=v_seller)
    assert out["as_seller"]["declined_by_them"] == 1 and "promised" in out["as_seller"]["recent_decline_reasons"][0]
    assert out["seller_acceptance"]["p"] < 0.6 and out["seller_acceptance"]["declined"] == 1   # prior mean 0.67 fell after one decline


def test_agent_writes_and_reads_lessons(client, auth):
    from app.agents.guardian_agent import Episode, build_tools
    tools = {f.__name__: f for f in build_tools(Episode(event_ids=[]))}
    sf = uid("sf1")
    tools["save_note"](entity_id=sf, note="declines orders under 50 kg")
    assert "declines orders" in tools["recall_memory"](entity_id=sf)["notes"][0]["note"]


def test_unresolved_shortfall_is_reported_with_computed_numbers(client, auth):
    from app.agents.guardian_agent import Episode, build_tools
    tools = {f.__name__: f for f in build_tools(Episode(event_ids=[]))}
    with session_scope() as db:
        inv = db.query(Inventory).filter_by(entity_id=uid("reeler3"), product="cocoon").one()
        inv.on_hand, inv.reserved = 40, 0
    r = tools["report_unresolved"](entity_id=uid("reeler3"), product="cocoon", reason="no source within 150 km")
    # the amount in the message is computed from the solver, not taken from the model
    with session_scope() as db:
        msg = db.query(Notification).filter(Notification.entity_id == uid("reeler3"), Notification.level == "alert").order_by(Notification.id.desc()).first()
    assert (r.get("sent") and "still uncovered" in msg.message) or "nothing remains" in r.get("note", "")


# ------------------------------------------------------------------ honest degradation
def test_without_an_llm_the_guardian_falls_back_to_rules_and_says_so(client, auth):
    set_llm_override(None)                      # no key in tests
    client.post("/api/target", headers=auth("spinner1"), json={"target_qty": 900, "horizon_days": 7})
    with session_scope() as db:
        ev = db.query(AgentEvent).filter_by(reason="target_set").one()
    assert ev.result["mode"] == "rules" and ev.result["opened"] and "no LLM" in (ev.result["fallback_reason"] or "")


def test_llm_failing_midway_is_reported_as_agent_plus_rules(client, auth):
    class Dies(PolicyLLM):
        def tool_loop(self, system, user, tools, purpose, max_steps):
            reg = {f.__name__: f for f in tools}
            reg["get_network_status"]()
            raise LLMUnavailable("quota exhausted")
    set_llm_override(Dies(lambda h, r: None))
    client.post("/api/target", headers=auth("spinner1"), json={"target_qty": 900, "horizon_days": 7})
    with session_scope() as db:
        ev = db.query(AgentEvent).filter_by(reason="target_set").one()
    assert ev.result["mode"] == "agent+rules" and "quota" in ev.result["fallback_reason"] and ev.result["opened"]


def test_rules_mode_can_be_forced_for_ablation(client, auth):
    set_llm_override(PolicyLLM(sourcing_policy))
    settings.guardian_mode = "rules"
    client.post("/api/target", headers=auth("spinner1"), json={"target_qty": 900, "horizon_days": 7})
    with session_scope() as db:
        assert db.query(AgentEvent).filter_by(reason="target_set").one().result["mode"] == "rules"
