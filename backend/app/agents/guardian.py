"""Guardian agent: perceives every change in the supply network and acts on it. Nobody presses "protect me".

PERCEIVE  an event is recorded whenever something changes: a stock edit, a new demand target, a deal that
          executed or was declined (see `submit`). Events wake the agent; there is no polling sweep.
REASON    the flow solver (calc/flow.py) carries the change down the chain and back up and says which
          entities now cannot be served by their current suppliers; stock policy says who is at reorder
          point and who holds surplus that will spoil.
ACT       for each such entity the agent opens an incident, which runs the sourcing graph: look for alternative
          vendors in both directions (buyers short of input -> sellers; sellers with surplus -> buyers),
          route them, and SEND OFFERS to the counterparties automatically.
OBSERVE   a counterparty that declines is remembered and skipped, and the agent re-plans. Money and stock only
          move when BOTH the seller and the buyer approve (human in the loop).
"""
import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from app.calc.flow import solve
from app.calc.supply import stock_status, surplus_qty
from app.config import settings
from app.db.models import AgentEvent, Entity, Inventory
from app.db.session import session_scope
from app.graph.propagate import has_open_incident, stock_drop_children
from app.graph.runner import start_incident
from app.llm.provider import LLMUnavailable, get_llm, reset_budget

log = logging.getLogger("ariadne.guardian")
_wake: "queue.Queue[int]" = queue.Queue()
_drain_lock = threading.Lock()
_tls = threading.local()
_worker: threading.Thread | None = None
LOW = ("reorder", "critical")


# ------------------------------------------------------------------ perceive
def submit(entity_id: int | None, product: str | None, reason: str, data: dict | None = None) -> dict | None:
    """Record a change and wake the agent. In `inline` mode (tests) the agent runs before this returns and its
    summary is returned; otherwise it runs in the background worker."""
    with session_scope() as db:
        ev = AgentEvent(entity_id=entity_id, product=product, reason=reason, data=data or {})
        db.add(ev)
        db.flush()
        eid = ev.id
    if settings.run_mode == "inline":
        return None if getattr(_tls, "busy", False) else drain()
    _wake.put(eid)
    _ensure_worker()
    return {"queued": eid}


def _ensure_worker() -> None:
    global _worker
    if _worker and _worker.is_alive():
        return

    def loop():
        while True:
            _wake.get()
            time.sleep(0.3)  # coalesce a burst of changes into one pass
            while not _wake.empty():
                _wake.get_nowait()
            try:
                drain()
            except Exception:
                log.exception("guardian pass failed")
    _worker = threading.Thread(target=loop, daemon=True, name="guardian")
    _worker.start()


def resume_pending() -> None:
    """After a restart: handle changes that arrived (or were interrupted) while the service was down."""
    with session_scope() as db:
        db.query(AgentEvent).filter(AgentEvent.status == "running").update({"status": "pending"})
        n = db.query(AgentEvent).filter(AgentEvent.status == "pending").count()
    if n:
        _wake.put(0)
        _ensure_worker()


def drain() -> dict:
    """Handle every pending event (repeat while handling produced new ones, e.g. executed deals)."""
    total = {"opened": [], "events": 0}
    with _drain_lock:
        _tls.busy = True
        try:
            for _ in range(5):
                with session_scope() as db:
                    evs = db.query(AgentEvent).filter(AgentEvent.status == "pending").order_by(AgentEvent.id).all()
                    batch = [(e.id, e.entity_id, e.product, e.reason, dict(e.data or {})) for e in evs]
                    for e in evs:
                        e.status = "running"
                if not batch:
                    break
                try:
                    res = _handle(batch)
                    status, err = "done", None
                except Exception as exc:
                    log.exception("guardian handling failed")
                    res, status, err = {"error": f"{type(exc).__name__}: {exc}"[:300]}, "error", True
                with session_scope() as db:
                    for eid, *_ in batch:
                        ev = db.get(AgentEvent, eid)
                        ev.status, ev.result, ev.handled_at = status, res, datetime.utcnow()
                total["opened"] += res.get("opened", [])
                total["events"] += len(batch)
        finally:
            _tls.busy = False
    return total


# ------------------------------------------------------------------ reason + act
def _handle(batch: list[tuple]) -> dict:
    """Decide with the LLM agent; when it is unavailable (or mode=rules) fall back to the deterministic rules and SAY SO."""
    from app.agents.guardian_agent import run_episode, run_optimizer_episode
    mode, fallback = settings.guardian_mode, None
    if mode == "none":  # evaluation only: observe the world without acting
        return {"mode": "none", "opened": []}
    if mode == "optimizer":
        return {**run_optimizer_episode(batch), "opened": [], **_observe(batch)}
    if mode != "rules":
        try:
            res = run_episode(batch)
            if not res["interrupted"]:
                return {**res, **_observe(batch)}
            fallback = f"LLM failed mid-episode: {res['interrupted']}"
            rules = _handle_rules(batch)
            return {**res, "mode": "agent+rules", "fallback_reason": fallback, "opened": rules.get("opened", []), "flow": rules.get("flow"), **_observe(batch)}
        except LLMUnavailable as exc:
            fallback = str(exc)
            if mode == "agent":
                return {"mode": "agent", "error": fallback, "opened": []}
    res = _handle_rules(batch)
    return {**res, "mode": "rules", "fallback_reason": fallback, **_observe(batch)}


def _observe(batch: list[tuple]) -> dict:
    """After acting, check the world again: what is still uncovered once pending offers are counted? (verification, not trust)"""
    from app.calc.needs import pending_in as _pending_in
    with session_scope() as db:
        f = solve(db)
        left = [{"entity_id": g["entity_id"], "name": g["name"], "product": g["product"], "uncovered_kg": round(max(g["short_linked"] - _pending_in(db, g["entity_id"], g["product"]), 0.0), 1)}
                for g in f["gaps"]]
    return {"residual": [r for r in left if r["uncovered_kg"] > 0.5], "chain_balanced_after": f["ok"]}


def _handle_rules(batch: list[tuple]) -> dict:
    jobs: dict[tuple, dict] = {}       # (entity, product, kind) -> start_incident args, de-duplicated
    opened: list[dict] = []
    touched: set[tuple[int, str]] = set()

    def want(entity_id: int, product: str, why: str, kind: str = "low_stock", lost: float = 0.0, qty: float = 0.0, cause: str = ""):
        key = (entity_id, product, kind)
        if key in jobs:
            jobs[key]["fields"]["lost_exposure"] = max(jobs[key]["fields"].get("lost_exposure", 0.0), lost)
            return
        fields = {"incident_type": kind, "product": product, "lost_exposure": round(lost, 1)}
        if kind == "surplus":
            fields["qty"] = qty
        if cause:
            fields["cause_text"] = cause
        jobs[key] = {"entity_id": entity_id, "fields": fields, "why": why,
                     "text": f"{product} stock is low" if kind == "low_stock" else f"{product} surplus"}

    for _, entity_id, product, reason, data in batch:
        parties = [(entity_id, product)] if entity_id and product else []
        parties += [tuple(p) for p in data.get("parties", [])]
        touched.update(parties)
        if reason == "stock_changed":
            drop = float(data.get("sellable_drop", 0.0))
            if drop > 1:  # a supplier's sellable stock fell: its buyers are assessed straight away
                opened += stock_drop_children(entity_id, product, drop)
            if data.get("before_status") not in LOW:
                _want_if_low(want, entity_id, product, "its stock reached the reorder point")
        elif reason in ("deal_executed", "deal_rejected"):
            for eid, p in parties:
                _want_if_low(want, eid, p, "its stock is low after a deal" if reason == "deal_executed" else "an offer was declined; looking for another source")

    with session_scope() as db:  # reason over the whole chain: who can no longer be served by current suppliers?
        flow = solve(db)
        h = flow["horizon_days"]
        for g in flow["gaps"]:
            want(g["entity_id"], g["product"], "demand across the chain exceeds what its suppliers can ship", lost=g["short_linked"],
                 cause=f"Demand across the chain now exceeds what your current suppliers can ship: {g['short_linked']:.0f} kg of {g['product']} short over {h:.0f} days.")
        for eid, p in touched:  # surplus that will spoil goes to buyers who need it (the other direction)
            inv = db.query(Inventory).filter_by(entity_id=eid, product=p).first()
            if inv and inv.is_finished:
                q = surplus_qty(inv)
                if q > 0:
                    want(eid, p, f"{q:.0f} kg will not be used before it degrades", kind="surplus", qty=q)
        live = [(k, j) for k, j in jobs.items() if not has_open_incident(db, k[0], k[1], k[2]) and not _covered(db, k, j)]
        kinds = {k[0]: db.get(Entity, k[0]).kind for k, _ in live}

    def run(job):
        reset_budget()
        eid = job["entity_id"]
        iid = start_incident(kinds[eid], eid, None, job["text"], job["fields"])
        return {"incident_id": iid, "entity_id": eid, "product": job["fields"]["product"], "kind": job["fields"]["incident_type"], "why": job["why"]}

    with ThreadPoolExecutor(max_workers=max(settings.guardian_workers, 1)) as pool:
        opened += list(pool.map(run, [j for _, j in live]))
    return {"opened": opened, "flow": {"ok": flow["ok"], "gaps": len(flow["gaps"]), "rounds": len(flow["rounds"])}}


def _want_if_low(want, entity_id: int, product: str, why: str) -> None:
    with session_scope() as db:
        inv = db.query(Inventory).filter_by(entity_id=entity_id, product=product).first()
        low = bool(inv) and stock_status(inv).status in LOW
    if low:
        want(entity_id, product, why)


def _covered(db, key: tuple, job: dict) -> bool:
    """An agent's pending offers already cover this need: the rules must not duplicate them."""
    from app.calc.needs import pending_in as _pending_in, pending_out as _pending_out
    eid, product, kind = key
    f = job["fields"]
    if kind == "surplus":
        return _pending_out(db, eid, product) >= 0.9 * f.get("qty", 0.0)
    return f.get("lost_exposure", 0.0) > 0 and _pending_in(db, eid, product) >= 0.9 * f["lost_exposure"]
