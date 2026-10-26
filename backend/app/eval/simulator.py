"""Simulation harness for the guardian: many episodes, hidden vendor behaviour, simulated human approvals.

    DATABASE_URL=...ariadne_test python -m app.eval.simulator --modes rules,optimizer --episodes 12 --seeds 3

WIPES the database it points at. What is simulated, and what is real:
  REAL      the network, stock maths, flow solver, routing, optimiser, deal API, memory, guardian modes, (optionally) the LLM agent.
  SIMULATED the humans' final approvals: every seller and buyer has a HIDDEN acceptance probability (some reliable, some flaky);
            when offers are pending the simulator decides them through the real approval API by sampling from those probabilities.
            In production these are humans; here they let us run hundreds of episodes and measure learning.
An episode = one perturbation (demand surge / stock drop) -> guardian acts -> simulated humans decide -> outcome events wake the
guardian -> repeat until covered or `rounds` exhausted. Episodes run back-to-back in the SAME database so memory accumulates (the
learning curve); `--no-memory` switches the memory off for the ablation.
Per episode: realised cost = executed purchase+transport + penalty x uncovered kg at the end; rounds used; offers; declines; and regret
vs a hindsight oracle (CP-SAT that KNOWS the true probabilities) on the first round's needs."""
import argparse
import json
import random
import statistics
import time
from datetime import datetime
from pathlib import Path

from app import constants
from app.agents.guardian import submit as guardian_agent_submit
from app.calc.needs import open_needs
from app.calc.objective import unmet_penalty
from app.config import settings
from app.db.models import AgentEvent, Deal, Entity, Inventory, Target, User
from app.db.seed import reseed_data
from app.db.session import session_scope
from app.llm.provider import get_llm

RESULTS = Path(__file__).resolve().parents[3] / "data" / "eval" / "results"


def hidden_behaviour(rng: random.Random) -> dict[int, float]:
    """True acceptance probability per participant: 60% reliable (0.9-0.99), 25% moderate (0.5-0.7), 15% flaky (0.1-0.3)."""
    out = {}
    with session_scope() as db:
        for (eid,) in db.query(Entity.id).filter(Entity.kind != "warehouse"):
            r = rng.random()
            out[eid] = rng.uniform(0.9, 0.99) if r < 0.6 else rng.uniform(0.5, 0.7) if r < 0.85 else rng.uniform(0.1, 0.3)
    return out


def snapshot_world() -> dict:
    with session_scope() as db:
        return {"inv": {i.id: (i.on_hand, i.reserved, i.daily_demand, i.demand_std, i.stocked_on) for i in db.query(Inventory)},
                "bal": {e.id: e.balance for e in db.query(Entity)}}


def reset_world(snap: dict) -> None:
    """Start every episode from the same stock and balances; KEEP the deal history, because that is the agent's memory.
    Undecided offers are expired (their reserved stock is released) and open incidents are closed."""
    from app.db.models import Incident
    with session_scope() as db:
        for i in db.query(Inventory):
            i.on_hand, i.reserved, i.daily_demand, i.demand_std, i.stocked_on = snap["inv"][i.id]
        for e in db.query(Entity):
            e.balance = snap["bal"][e.id]
        db.query(Target).delete()
        db.query(Deal).filter(Deal.status.in_(["pending", "approved"])).update({"status": "expired"}, synchronize_session=False)
        db.query(Incident).filter(Incident.status.in_(["awaiting_approval", "running", "open", "resuming"])).update({"status": "closed"}, synchronize_session=False)


def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _login(client, uname):
    r = client.post("/api/auth/login", json={"username": uname, "password": "ariadne123"})
    return {"Authorization": "Bearer " + r.json()["token"]}


def humans_decide(client, truth: dict[int, float], rng: random.Random, users: dict[int, str]) -> tuple[int, int]:
    """Every pending deal: the seller and the buyer each approve with their hidden probability. Returns (approved, declined)."""
    ok = no = 0
    with session_scope() as db:
        pend = [(d.id, d.seller_id, d.buyer_id) for d in db.query(Deal).filter(Deal.status == "pending").order_by(Deal.id)]
    for did, s, b in pend:
        sides = [("seller", s), ("buyer", b)]
        for side, eid in sides:
            with session_scope() as db:
                st = db.get(Deal, did).status
            if st != "pending":
                break
            yes = rng.random() < truth[eid]
            r = client.post(f"/api/deals/{did}/decision", headers=_login(client, users[eid]), json={"approve": yes, "reason": "" if yes else "cannot supply right now"})
            if r.status_code == 200:
                ok, no = (ok + 1, no) if yes else (ok, no + 1)
    return ok, no


def realised_cost(db, since_deal_id: int, start_needs: dict) -> dict:
    """What the episode cost: executed purchases + transport, plus the penalty for need that is STILL uncovered afterwards."""
    ds = db.query(Deal).filter(Deal.id > since_deal_id).all()
    purchase = sum(d.quantity * d.unit_price for d in ds if d.status == "executed")
    transport = sum(d.transport_cost for d in ds if d.status == "executed")
    after = open_needs(db)
    mine = {k: v for k, v in after.items() if k in start_needs}   # only the shortfalls THIS episode's disturbance created
    pen = sum(v * unmet_penalty(k[1]) for k, v in mine.items())
    return {"purchase_inr": round(purchase), "transport_inr": round(transport), "unmet_kg": round(sum(mine.values())), "penalty_inr": round(pen),
            "cost_inr": round(purchase + transport + pen), "executed": len([d for d in ds if d.status == "executed"]), "offers": len(ds),
            "declined": len([d for d in ds if d.status == "rejected"])}


def perturbation(rng: random.Random, users: dict[int, str], names: dict[int, str]):
    """A random disturbance: spinner/reeler demand surge, or a raw-input stock crash at a reeler/silkworm farm."""
    with session_scope() as db:
        spinners = sorted(e.id for e in db.query(Entity).filter_by(kind="spinner"))
        reelers = sorted(e.id for e in db.query(Entity).filter_by(kind="reeler"))
        farms = sorted(e.id for e in db.query(Entity).filter_by(kind="silkworm_farm"))
    k = rng.choice(["surge_spinner", "surge_reeler", "crash_reeler", "crash_farm"])
    return k, (rng.choice(spinners) if k == "surge_spinner" else rng.choice(reelers) if k in ("surge_reeler", "crash_reeler") else rng.choice(farms))


def apply_perturbation(client, kind: str, eid: int, users: dict[int, str], rng: random.Random):
    h = _login(client, users[eid])
    if kind.startswith("surge"):
        client.post("/api/target", headers=h, json={"target_qty": round(rng.uniform(300, 700)), "horizon_days": 7})
    else:
        product = "cocoon" if kind == "crash_reeler" else "leaves"
        client.post("/api/stock", headers=h, json={"product": product, "set_to": round(rng.uniform(10, 60))})


def run_episode(client, kind, eid, users, truth, rng, rounds: int, rng_h=None) -> dict:
    rng_h = rng_h or rng
    t0 = time.time()
    with session_scope() as db:
        since = (db.query(Deal).order_by(Deal.id.desc()).first() or Deal(id=0)).id
        ev0 = db.query(AgentEvent).count()
    with session_scope() as db:
        baseline = open_needs(db)
    real_mode, settings.guardian_mode = settings.guardian_mode, "none"      # apply the disturbance, nobody acts yet
    apply_perturbation(client, kind, eid, users, rng)
    settings.guardian_mode = real_mode
    with session_scope() as db:
        after_n = open_needs(db)
        start_needs = {k: v for k, v in after_n.items() if v > baseline.get(k, 0.0) + 1}  # needs CAUSED by the disturbance
        ev = db.query(AgentEvent).order_by(AgentEvent.id.desc()).first()
        ev_args = (ev.entity_id, ev.product, ev.reason, dict(ev.data or {})) if ev else None
    if ev_args:                                                               # now release the SAME event to the decision-maker
        guardian_agent_submit(*ev_args)
    approved = declined = 0
    for r in range(rounds):
        a, d = humans_decide(client, truth, rng_h, users)
        approved, declined = approved + a, declined + d
        with session_scope() as db:
            pend = db.query(Deal).filter(Deal.status == "pending").count()
        if a + d == 0 and pend == 0:
            break
    with session_scope() as db:
        evs = [(e.result or {}) for e in db.query(AgentEvent).filter(AgentEvent.id > ev0)]
        res = realised_cost(db, since, start_needs)
    res.update(kind=kind, entity_id=eid, rounds_used=r + 1, human_approvals=approved, human_declines=declined,
               tool_calls=sum(len(e.get("steps", [])) for e in evs), invalid_tool_calls=sum(e.get("invalid_tool_calls") or 0 for e in evs),
               llm_calls=sum(e.get("llm_calls") or 0 for e in evs), modes=sorted({e.get("mode") for e in evs if e.get("mode")}),
               regrets=[e["regret"]["regret_pct"] for e in evs if e.get("regret", {}).get("regret_pct") is not None],
               seconds=round(time.time() - t0, 1), start_need_kg=round(sum(start_needs.values())))
    return res


def run_series(mode: str, seed: int, episodes: int, rounds: int, memory: bool, tools: str) -> list[dict]:
    reseed_data()
    constants.set_cache({})
    rng = random.Random(seed)                 # disturbances: the SAME sequence for every mode/memory arm (paired comparison)
    rng_h = random.Random(seed + 7)           # the simulated humans' coin flips: separate stream so arms stay paired
    settings.guardian_mode = "rules" if mode == "rules" else "optimizer" if mode == "optimizer" else "auto"
    settings.memory_enabled, settings.agent_tools = memory, tools
    settings.agent_log_regret = mode in ("optimizer", "agent")
    truth = hidden_behaviour(random.Random(seed + 1000))
    with session_scope() as db:
        users = {u.entity_id: u.username for u in db.query(User)}
        names = {e.id: e.name for e in db.query(Entity)}
    out = []
    snap = snapshot_world()
    with _client() as client:
        for i in range(episodes):
            reset_world(snap)
            kind, eid = perturbation(rng, users, names)
            r = run_episode(client, kind, eid, users, truth, rng, rounds, rng_h)
            r.update(episode=i, seed=seed, mode=mode, memory=memory, tools=tools)
            out.append(r)
            print(json.dumps({k: r[k] for k in ("mode", "seed", "episode", "kind", "cost_inr", "unmet_kg", "offers", "declined", "rounds_used", "seconds")}), flush=True)
    return out


def summarise(runs: list[dict]) -> list[dict]:
    rows = []
    for key in sorted({(r["mode"], r["memory"], r["tools"]) for r in runs}):
        rs = [r for r in runs if (r["mode"], r["memory"], r["tools"]) == key]
        half = max(len(rs) // 2, 1)
        decl = lambda xs: sum(x["declined"] for x in xs) / max(sum(x["offers"] for x in xs), 1)
        rows.append({"mode": key[0], "memory": key[1], "tools": key[2], "episodes": len(rs),
                     "mean_cost_inr": round(statistics.mean(r["cost_inr"] for r in rs)), "mean_unmet_kg": round(statistics.mean(r["unmet_kg"] for r in rs)),
                     "mean_offers": round(statistics.mean(r["offers"] for r in rs), 1), "decline_rate": round(decl(rs), 3),
                     "decline_rate_first_half": round(decl(rs[:half]), 3), "decline_rate_second_half": round(decl(rs[half:]), 3),
                     "mean_rounds": round(statistics.mean(r["rounds_used"] for r in rs), 2), "mean_seconds": round(statistics.mean(r["seconds"] for r in rs), 1),
                     "mean_regret_pct": round(statistics.mean([x for r in rs for x in r["regrets"]]), 2) if any(r["regrets"] for r in rs) else None})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default="rules,optimizer")
    ap.add_argument("--episodes", type=int, default=10)
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--no-memory", action="store_true", help="also run each mode with memory off")
    ap.add_argument("--tools", default="full")
    ap.add_argument("--out", default=str(RESULTS))
    a = ap.parse_args()
    settings.run_mode, settings.guardian_workers = "inline", 1
    runs = []
    for mode in a.modes.split(","):
        if mode in ("agent", "agent_noopt") and get_llm() is None:
            print(f"skip {mode}: no LLM key"); continue
        tools = "no_optimizer" if mode == "agent_noopt" else a.tools
        m = "agent" if mode == "agent_noopt" else mode
        for mem in ([True, False] if a.no_memory and m != "rules" else [True]):  # rules never read memory
            for seed in range(a.seeds):
                runs += run_series(m, seed, a.episodes, a.rounds, mem, tools)
    summ = summarise(runs)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    f = Path(a.out) / f"simulator_{datetime.now():%Y%m%d_%H%M%S}.json"
    f.write_text(json.dumps({"args": vars(a), "model": settings.gemini_model, "summary": summ, "runs": runs}, indent=1, default=str))
    print(json.dumps(summ, indent=1)); print("saved", f)


if __name__ == "__main__":
    main()
