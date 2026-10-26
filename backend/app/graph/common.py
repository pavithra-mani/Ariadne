import functools
import time
from datetime import datetime, timezone

from app.db.models import Incident
from app.db.session import session_scope
from app.llm.provider import take_calls


def traced(name: str, kind: str = "node"):
    """Wrap a node: time it and append a trace entry (LangGraph-state + persisted on the incident)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(state):
            t0 = time.perf_counter()
            out = fn(state) or {}
            out = dict(out)
            entry = {"node": name, "kind": kind, "ms": round((time.perf_counter() - t0) * 1000),
                     "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "summary": out.pop("_summary", ""), "tools": out.pop("_tools", []),
                     "agent": out.pop("_agent", []), "llm": take_calls()}
            out["trace"] = [entry]
            _progress(state, entry)
            return out
        return wrapper
    return deco


def _progress(state: dict, entry: dict) -> None:
    """Show a running incident's steps as they finish (the UI polls the incident while it works)."""
    try:
        with session_scope() as db:
            inc = db.get(Incident, state["incident_id"])
            if inc is not None and inc.status == "running":
                inc.trace = list(inc.trace or []) + [entry]
    except Exception:
        pass  # progress is cosmetic; the final save writes the full trace


def save_incident(state: dict, status: str | None = None, **extra) -> None:
    """Persist the current graph state onto the incident record (the JSON incident of design 2.3)."""
    with session_scope() as db:
        inc = db.get(Incident, state["incident_id"])
        if status:
            inc.status = status
        risk = state.get("risk") or {}
        inc.severity, inc.urgency, inc.priority = risk.get("severity"), risk.get("urgency"), risk.get("priority")
        inc.kind = state.get("incident_kind", inc.kind)
        inc.is_issue = state.get("mode") == "incident"
        payload = dict(inc.payload or {})
        for k in ("finding", "rag", "risk", "supply_impact", "health_impact", "advisory", "memory", "cases", "plans",
                  "outcome", "assessment", "route"):
            if state.get(k) is not None:
                payload[k] = state[k]
        payload.update(extra.pop("payload", {}))
        inc.payload = payload
        inc.trace = state.get("trace", [])
        for k, v in extra.items():
            setattr(inc, k, v)
