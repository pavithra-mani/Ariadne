"""Evaluation harness (design doc section 5).

    python -m app.eval.run --reset            # WIPES demo data; evaluates the Gemini agents (default when a key is set)
    python -m app.eval.run --reset --rules    # same scenarios on the rule-based fallback path (no LLM, deterministic)

Results: data/eval/results/baseline_<timestamp>.json  (+ printed table). Target thresholds are meant
to be fixed after a first baseline run, as stated in the design.
"""
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import DATA_DIR
from app.db.models import Deal, Entity, Inventory, User
from app.db.seed import reseed_data
from app.db.session import session_scope
from app.eval import metrics as M
from app.eval.scenarios import SCENARIOS, Scenario
from app.llm.structured import groq_enabled

RESULTS = DATA_DIR / "eval" / "results"
QA = DATA_DIR / "eval" / "qa_set.json"
IMAGES = DATA_DIR / "images"


class Api:
    def __init__(self, client: TestClient):
        self.c, self.tokens = client, {}

    def h(self, user: str) -> dict:
        if user not in self.tokens:
            r = self.c.post("/api/auth/login", json={"username": user, "password": "ariadne123"})
            self.tokens[user] = {"Authorization": "Bearer " + r.json()["token"]}
        return self.tokens[user]

    def chat(self, user: str, message: str, fields: dict, image: str | None):
        files = {"image": (image, open(IMAGES / image, "rb"), "image/jpeg")} if image else None
        r = self.c.post("/api/chat", headers=self.h(user), data={"message": message, "fields": json.dumps(fields)}, files=files)
        return r.json() if r.status_code == 200 else {"status": "error", "payload": {}, "trace": [], "http": r.status_code}

    def incident(self, user: str, iid: int) -> dict:
        return self.c.get(f"/api/incidents/{iid}", headers=self.h(user)).json()


def apply_setup(setup: dict | None):
    if not setup:
        return
    with session_scope() as db:
        if "stock" in setup:
            s = setup["stock"]
            uid = db.query(User).filter(User.username == s["user"]).one().entity_id
            db.query(Inventory).filter_by(entity_id=uid, product=s["product"]).one().on_hand = s["on_hand"]


def resolve_target_gap(api: Api, sc: Scenario) -> dict:
    """Turn a wanted shortfall (kg beyond own+linked supply) into an absolute target."""
    f = dict(sc.fields)
    if "target_gap" in f:
        probe = api.chat(sc.user, "probe", {"target_qty": 1, "horizon_days": f["horizon_days"]}, None)
        imp = probe["payload"]["supply_impact"]
        f = {"target_qty": round(imp["own_buffer"] + imp["linked_supply"] + f.pop("target_gap"), 1),
             "horizon_days": f["horizon_days"]}
    return f


def decide_all(api: Api, incident_id: int):
    with session_scope() as db:
        pend = [(d.id, db.query(User).filter(User.entity_id == d.approver_id).first().username)
                for d in db.query(Deal).filter(Deal.incident_id == incident_id, Deal.status == "pending")]
    return pend


def run_scenarios(api: Api, m: Counter, rows: list[dict]):
    for sc in SCENARIOS:
        t0 = time.time()
        reseed_data()  # every scenario starts from the same network: pending proposals reserve stock and would couple scenarios
        apply_setup(sc.setup)
        fields = resolve_target_gap(api, sc)
        inc = api.chat(sc.user, sc.message, fields, sc.image)
        payload, trace = inc.get("payload", {}), inc.get("trace", [])
        nodes = [t["node"] for t in trace]
        tools = M.used_tools(trace)
        row = {"id": sc.id, "status": inc.get("status"), "priority": inc.get("priority"), "checks": {}}

        # --- A. workflow behaviour
        m["tasks"] += 1
        ok_run = inc.get("status") not in ("error", None)
        m["task_completed"] += int(ok_run and inc["status"] in sc.terminal)
        row["checks"]["completed"] = ok_run and inc["status"] in sc.terminal
        m["route_tests"] += 1
        m["route_ok"] += int(payload.get("route") == sc.route)
        row["checks"]["routing"] = payload.get("route") == sc.route
        m["tool_tests"] += 1
        tool_ok = all(t in tools for t in sc.tools_all) and not any(t in tools for t in sc.tools_none)
        m["tool_ok"] += int(tool_ok)
        row["checks"]["tool_selection"] = tool_ok
        v, n = M.output_validity(payload)
        m["out_valid"] += v
        m["out_checked"] += n
        m["handoff_tests"] += 1
        hand = M.is_subsequence(sc.sequence, nodes) and all(payload.get(k) is not None for k in ("finding", "rag", "risk", "advisory"))
        m["handoff_ok"] += int(hand)
        row["checks"]["handoff"] = hand
        tool_steps = [s for s in trace if s.get("tools")]
        m["tool_attempts"] += len(tool_steps) + (0 if ok_run else 1)
        m["tool_success"] += len(tool_steps)
        for s in trace:
            if s["node"] in ("alternative_sources", "routing_ortools"):
                m["calls_total"] += 1
                m["calls_unnecessary"] += int("no new candidates" in s["summary"] or "0 source(s)" in s["summary"])
            else:
                m["calls_total"] += len(s.get("tools", []))

        # --- human decision
        term_ok = inc.get("status") in sc.terminal
        if sc.after and inc.get("status") == "awaiting_approval":
            for did, uname in decide_all(api, inc["id"]):
                api.c.post(f"/api/deals/{did}/decision", headers=api.h(uname), json={"approve": sc.after == "approve"})
            final = api.incident(sc.user, inc["id"])
            term_ok = term_ok and final.get("status") in sc.final
            row["final_status"] = final.get("status")
        m["term_tests"] += 1
        m["term_ok"] += int(term_ok)
        row["checks"]["termination"] = term_ok

        # --- D. abstention (scenario-level)
        if sc.abstain:
            adv, rag, imp = payload.get("advisory", {}), payload.get("rag", {}), payload.get("supply_impact", {})
            abstained = bool(adv.get("abstained")) or str(adv.get("headline", "")).startswith("Diagnosis uncertain") \
                or inc.get("status") == "escalated" or bool((payload.get("outcome") or {}).get("unresolved"))
            m["abst_tests"] += 1
            m["abst_ok"] += int(abstained)
            row["checks"]["abstained"] = abstained
        row["seconds"] = round(time.time() - t0, 1)
        rows.append(row)
        print(f"  {'PASS' if all(row['checks'].values()) else 'FAIL'}  {sc.id:48s} status={row['status']}", flush=True)


def run_qa(api: Api, m: Counter, rows: list[dict]):
    qa = json.loads(QA.read_text())
    judge_kind = "heuristic"
    recalls, precs, comps, rels = [], [], [], []
    for item in qa["answerable"]:
        inc = api.chat("sf1", item["q"], {}, None)
        payload = inc.get("payload", {})
        adv, rag = payload.get("advisory", {}), payload.get("rag", {})
        text = M.answer_text(adv)
        m["qa_tests"] += 1
        ok = (not adv.get("abstained")) and M.correctness(text, item["must"])
        m["qa_correct"] += int(ok)
        c, r, judge_kind = M.judge(item["q"], text, item["checklist"])
        comps.append(c)
        rels.append(r)
        passages = [p["text"] for p in rag.get("passages", [])]
        claims = M.sentences(text)
        m["claims"] += len(claims)
        sup = sum(M.supported(c_, passages) for c_ in claims)
        m["claims_supported"] += sup
        for pt in rag.get("points", []):  # citation accuracy on the extractive points
            m["cites"] += 1
            idx = pt["citation"] - 1
            m["cites_ok"] += int(0 <= idx < len(passages) and M.supported(pt["text"], [passages[idx]]))
        rc, pr = M.retrieval_scores(item["q"], item["sources"])
        recalls.append(rc)
        precs.append(pr)
        rows.append({"id": "QA " + item["q"][:50], "correct": ok, "claims": len(claims), "supported": sup,
                     "recall@5": round(rc, 2), "precision@5": round(pr, 2)})
    m["recall_sum"], m["prec_sum"], m["recall_n"] = round(sum(recalls), 3), round(sum(precs), 3), len(recalls)
    m["comp_sum"], m["rel_sum"] = round(sum(comps), 3), round(sum(rels), 3)
    for q in qa["unanswerable"]:
        inc = api.chat("sf1", q, {}, None)
        adv = inc.get("payload", {}).get("advisory", {})
        m["abst_tests"] += 1
        m["abst_ok"] += int(bool(adv.get("abstained")))
        rows.append({"id": "OOD " + q[:50], "abstained": bool(adv.get("abstained"))})
        print(f"  {'PASS' if adv.get('abstained') else 'FAIL'}  OOD: {q}", flush=True)
    return judge_kind


def report(m: Counter, judge_kind: str) -> dict:
    P = M.PCT
    avg = lambda s, n: round(100 * m[s] / m[n], 1) if m[n] else None  # noqa: E731
    return {
        "A. Agent workflow and tool behaviour": {
            "Task Completion Rate": P(m["task_completed"], m["tasks"]),
            "Supervisor Routing Accuracy": P(m["route_ok"], m["route_tests"]),
            "Tool Selection Accuracy": P(m["tool_ok"], m["tool_tests"]),
            "Structured Output Validity": P(m["out_valid"], m["out_checked"]),
            "Tool Execution Success Rate": P(m["tool_success"], m["tool_attempts"]),
            "Handoff Accuracy": P(m["handoff_ok"], m["handoff_tests"]),
            "Unnecessary Tool Call Rate": P(m["calls_unnecessary"], m["calls_total"]),
            "Workflow Termination Accuracy": P(m["term_ok"], m["term_tests"]),
        },
        "B. Answer quality": {
            "Answer Correctness": P(m["qa_correct"], m["qa_tests"]),
            f"Completeness (judge: {judge_kind})": avg("comp_sum", "recall_n"),
            f"Relevance (judge: {judge_kind})": avg("rel_sum", "recall_n"),
        },
        "C. Retrieval and grounding": {
            "Groundedness / Faithfulness": P(m["claims_supported"], m["claims"]),
            "Citation Accuracy": P(m["cites_ok"], m["cites"]),
            "Retrieval Recall@5": avg("recall_sum", "recall_n"),
            "Context Precision@5": avg("prec_sum", "recall_n"),
        },
        "D. Safe handling of uncertainty": {
            "Abstention Accuracy": P(m["abst_ok"], m["abst_tests"]),
            "Hallucination Rate": P(m["claims"] - m["claims_supported"], m["claims"]),
        },
    }


def main():
    if "--reset" not in sys.argv:
        print("This run WIPES the demo database and reseeds it. Re-run with --reset to confirm.")
        sys.exit(2)
    from app.config import settings
    # The agentic system is the product, so it is what gets evaluated by default (when a key is configured).
    # --rules switches the LLM off for a deterministic, free baseline of the rule-based fallback path.
    use_llm = "--rules" not in sys.argv and bool(settings.gemini_api_key)
    if not use_llm:
        settings.gemini_api_key = ""
        settings.groq_api_key = ""
    from app.main import app
    print(f"LLM agents: {'ON (Gemini)' if use_llm else 'off (rule-based path)'}", flush=True)
    print("Reseeding...", flush=True)
    reseed_data()
    m, rows = Counter(), []
    with TestClient(app) as client:
        api = Api(client)
        print("Scenarios:", flush=True)
        run_scenarios(api, m, rows)
        print("Question set:", flush=True)
        judge_kind = run_qa(api, m, rows)
    rep = report(m, judge_kind)
    out = {"created": datetime.now().isoformat(timespec="seconds"), "groq": groq_enabled(), "llm_agents": use_llm, "judge": judge_kind,
           "metrics": rep, "counts": dict(m), "rows": rows}
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{'agents' if use_llm else 'rules'}_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print("\n=== Ariadne evaluation (Table 5) ===")
    for group, ms in rep.items():
        print(f"\n{group}")
        for k, v in ms.items():
            print(f"  {k:46s} {v if v is not None else 'n/a'}{'%' if v is not None else ''}")
    print("\nReport:", path)


if __name__ == "__main__":
    main()
