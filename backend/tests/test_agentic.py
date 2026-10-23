"""The agentic layer: LLM triage, tool-using advisor, LLM-graded RAG, planning - and its guards and fallbacks."""
import json
from pathlib import Path

import pytest

from app.agents.tools import ToolContext, build_tools
from app.db.models import Entity, User
from app.db.seed import reseed_data
from app.db.session import session_scope
from app.llm.provider import LLMUnavailable, set_llm_override, start_budget
from app.llm.schemas import AnswerOut, Advisory, DiagnosisOut, GradeOut, StrategyChoice, StrategyOut, TriageOut
from app.rag.agentic import agentic_rag
from tests.fakes import FakeLLM

IMG = Path(__file__).resolve().parents[2] / "data" / "images"


@pytest.fixture(autouse=True)
def fresh():
    reseed_data()


def chat(client, auth, user, message, fields=None, image=None):
    files = {"image": (image, open(IMG / image, "rb"), "image/jpeg")} if image else None
    r = client.post("/api/chat", headers=auth(user), data={"message": message, "fields": json.dumps(fields or {})}, files=files)
    assert r.status_code == 200, r.text
    return r.json()


def make_low(username, product, on_hand=50):
    from app.calc.impact import get_inv
    with session_scope() as db:
        eid = db.query(User).filter_by(username=username).one().entity_id
        get_inv(db, eid, product).on_hand = on_hand


def trace(inc, node):
    return next(t for t in inc["trace"] if t["node"] == node)


# ------------------------------------------------------------------ triage
def test_llm_triage_turns_free_text_into_a_stock_incident(client, auth):
    fake = FakeLLM(json={"triage": lambda s, u: TriageOut(intent="low_stock", product="cocoon", confidence=0.9)})
    set_llm_override(fake)
    inc = chat(client, auth, "reeler1", "we are nearly out of cocoons, need to restock")
    assert inc["kind"] == "low_stock" and inc["payload"]["finding"]["product"] == "cocoon"
    assert "llm.triage" in trace(inc, "intake")["tools"] and trace(inc, "intake")["llm"][0]["purpose"] == "triage"


def test_triage_numbers_must_appear_in_the_message(client, auth):
    set_llm_override(FakeLLM(json={"triage": lambda s, u: TriageOut(intent="supply_problem", incident_type="low_yarn_output",
                                                                    reduction_pct=55, duration_days=9, confidence=0.9)}))
    inc = chat(client, auth, "reeler1", "the factory is down for 9 days")
    f = inc["payload"]["finding"]
    assert f["reduction_pct"] != 55          # 55 was never said: the hallucinated number is dropped (rule default applies)
    assert f["window_days"] == 9             # 9 was said: kept


def test_unclear_message_gets_a_follow_up_question_not_a_guess(client, auth):
    set_llm_override(FakeLLM(json={"triage": lambda s, u: TriageOut(intent="unclear", confidence=0.2,
                                                                    clarification="Which product is short, and by roughly how much?")}))
    inc = chat(client, auth, "reeler1", "something is wrong")
    assert inc["status"] == "needs_info" and inc["payload"]["advisory"]["type"] == "clarify"
    assert "Which product" in inc["payload"]["advisory"]["question"]
    assert [t["node"] for t in inc["trace"]][:2] == ["intake", "finalize"]  # no analysis, no deals on a guess


def test_triage_failure_falls_back_to_keyword_rules(client, auth):
    set_llm_override(FakeLLM())  # no scripted triage -> LLMUnavailable
    inc = chat(client, auth, "sf1", "how should fresh cocoons be stored?")
    assert inc["is_issue"] is False and inc["status"] == "answered"


def test_role_cannot_be_given_an_intent_it_does_not_have(client, auth):
    set_llm_override(FakeLLM(json={"triage": lambda s, u: TriageOut(intent="demand_request", target_qty=500, confidence=0.9)}))
    inc = chat(client, auth, "mf1", "I want 500 kg")      # a mulberry farmer has no demand requests
    assert inc["kind"] != "demand_surge"


# ------------------------------------------------------------------ text diagnosis
def test_llm_reads_symptom_text_when_there_is_no_photo(client, auth):
    set_llm_override(FakeLLM(json={
        "triage": lambda s, u: TriageOut(intent="disease_report", confidence=0.9),
        "diagnose": lambda s, u: DiagnosisOut(label="grasserie", confidence=0.95, rationale="milky fluid, climbing"),
    }))
    inc = chat(client, auth, "sf1", "the larvae climb the tray edge and ooze milky fluid")
    f = inc["payload"]["finding"]
    assert f["label"] == "grasserie" and f["source"] == "llm_symptoms"
    assert f["confidence"] <= 0.7          # a description alone is never treated as certain


# ------------------------------------------------------------------ advisor agent (tools)
def advisor_fake(answer):
    return FakeLLM(json={"triage": lambda s, u: TriageOut(intent="question", confidence=0.9), "advisor.final": answer},
                   tools={"advisor": [("search_knowledge", {"query": "fresh cocoon storage"})]})


def test_advisor_agent_uses_tools_and_cites_retrieved_passages(client, auth):
    set_llm_override(advisor_fake(lambda s, u: AnswerOut(answer="Spread cocoons thin in a cool, ventilated room.",
                                                         key_points=["Do not stack in sacks."], citations=[1, 99])))
    inc = chat(client, auth, "sf1", "how should fresh cocoons be stored?")
    adv = inc["payload"]["advisory"]
    assert adv["structured_by"] == "agent" and adv["abstained"] is False
    assert adv["citations"] == [1]                       # ref 99 was never retrieved -> dropped
    assert inc["payload"]["rag"]["passages"] and inc["payload"]["rag"]["passages"][0]["source"].endswith(".md")
    step = trace(inc, "advisory_action_plan")["agent"][0]
    assert step["tool"] == "search_knowledge" and "fresh cocoon" in step["args"]["query"]


def test_answer_without_any_valid_citation_is_forced_to_abstain(client, auth):
    set_llm_override(advisor_fake(lambda s, u: AnswerOut(answer="Cocoons should be frozen.", citations=[42])))
    inc = chat(client, auth, "sf1", "how should fresh cocoons be stored?")
    adv = inc["payload"]["advisory"]
    assert adv["abstained"] is True and "could not find reliable information" in adv["answer"]


def test_advisor_failure_falls_back_to_the_grounded_template(client, auth):
    fake = FakeLLM(json={"triage": lambda s, u: TriageOut(intent="question", confidence=0.9)},
                   tools={"advisor": [("search_knowledge", {"query": "cocoon storage"})]})  # advisor.final missing -> LLMUnavailable
    set_llm_override(fake)
    inc = chat(client, auth, "sf1", "how should fresh cocoons be stored?")
    assert inc["payload"]["advisory"]["structured_by"] == "template" and inc["payload"]["advisory"]["answer"]


def test_llm_budget_exhaustion_degrades_instead_of_failing(client, auth):
    import app.graph.runner as runner
    original = runner.start_budget
    runner.start_budget = lambda n=None: original(1)    # a single LLM call allowed for this request
    try:
        set_llm_override(advisor_fake(lambda s, u: AnswerOut(answer="x", citations=[1])))
        inc = chat(client, auth, "sf1", "how should fresh cocoons be stored?")
    finally:
        runner.start_budget = original
    assert inc["status"] == "answered" and inc["payload"]["advisory"]["structured_by"] == "template"


def test_incident_advice_marks_steps_that_the_evidence_does_not_support(client, auth):
    bad = "Apply a secret miracle compound weekly"
    set_llm_override(FakeLLM(
        json={"advisor.final": lambda s, u: Advisory(headline="Grasserie", diagnosis="d", mitigation_steps=[bad, "Remove and burn infected larvae."],
                                                     citations=[1])},
        tools={"advisor": [("search_knowledge", {"query": "grasserie management"})]}))
    inc = chat(client, auth, "sf1", "photo", {"affected_pct": 50}, "grasserie_sample.jpg")
    adv = inc["payload"]["advisory"]
    assert adv["structured_by"] in ("agent", "gemini") and 0 in adv["ungrounded_steps"]
    assert adv["escalate"] is True                       # decision fields stay locked to the calculations


# ------------------------------------------------------------------ tools are read-only and scoped
def test_tools_only_expose_the_callers_own_data(client, auth):
    with session_scope() as db:
        mf = db.query(User).filter_by(username="mf1").one()
        sf = db.query(User).filter_by(username="sf1").one()
        mf_e, sf_e = mf.entity_id, sf.entity_id
    tools = {t.__name__: t for t in build_tools(ToolContext(mf_e, "mulberry_farm"))}
    assert tools["get_my_partners"]()["partners"] == []                    # a mulberry farmer sees nobody else
    assert {s["product"] for s in tools["get_my_stock"]()["stock"]} == {"leaves"}
    stolen = tools["get_my_stock"](product="cocoon")                       # asking for another business' product
    assert stolen["stock"] == []
    sf_tools = {t.__name__: t for t in build_tools(ToolContext(sf_e, "silkworm_farm"))}
    names = {p["name"] for p in sf_tools["get_my_partners"]()["partners"]}
    with session_scope() as db:
        hidden = {e.name for e in db.query(Entity).filter(Entity.kind == "spinner")}
    assert not (names & hidden)
    assert not any(n.startswith(("set_", "update_", "approve_", "delete_")) for n in sf_tools)  # no write tools exist


# ------------------------------------------------------------------ LLM-graded RAG
def test_llm_grader_selects_passages_and_rewrites_when_unanswerable(client):
    calls = []

    def grade(schema, user):
        calls.append(user)
        return GradeOut(relevant=[0], answerable=True) if len(calls) > 1 else GradeOut(relevant=[], answerable=False, rewrite="cocoon storage conditions")
    set_llm_override(FakeLLM(json={"rag.grade": grade}))
    start_budget()
    res = agentic_rag("where do i keep my harvest", use_llm=True)
    assert res.graded_by == "llm" and not res.abstained and len(res.queries_tried) == 2
    assert res.queries_tried[1] == "cocoon storage conditions"


def test_llm_grader_can_reject_everything_and_the_system_abstains(client):
    set_llm_override(FakeLLM(json={"rag.grade": lambda s, u: GradeOut(relevant=[], answerable=False)}))
    start_budget()
    res = agentic_rag("how should fresh cocoons be stored", use_llm=True)
    assert res.abstained


# ------------------------------------------------------------------ recovery planning
def test_planner_strategy_changes_which_sources_are_chosen(client, auth):
    def run(strategy):
        reseed_data()
        make_low("reeler1", "cocoon")
        set_llm_override(FakeLLM(json={"recovery.strategy": lambda s, u: StrategyOut(
            choices=[StrategyChoice(case=0, strategy=strategy, reason=f"test {strategy}")])}))
        inc = chat(client, auth, "reeler1", "x", {"incident_type": "low_stock", "product": "cocoon"})
        plan = inc["payload"]["plans"][0]
        assert plan["strategy"] == strategy and plan["strategy_reason"] == f"test {strategy}"
        return [d["seller"]["name"] for d in client.get("/api/approvals", headers=auth("reeler1")).json()], [
            d["route"]["stop_distance_km"] for d in client.get("/api/approvals", headers=auth("reeler1")).json()]
    cheapest = run("cheapest")
    nearest = run("nearest")
    assert cheapest and nearest
    assert nearest[1][0] == min(nearest[1])      # the nearest strategy starts with the shortest distance


def test_planner_unavailable_means_balanced_default(client, auth):
    make_low("reeler1", "cocoon")
    set_llm_override(FakeLLM())
    inc = chat(client, auth, "reeler1", "x", {"incident_type": "low_stock", "product": "cocoon"})
    assert inc["payload"]["plans"][0]["strategy"] == "balanced"
