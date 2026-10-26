"""Create an incident row and run the graph on it (used by the chat API, the guardian agent and cascades)."""
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

from app.config import settings
from app.db.models import Incident
from app.db.session import session_scope
from app.llm.provider import reset_budget, start_budget

log = logging.getLogger("ariadne.runner")
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="incident")


def create_incident(role: str, entity_id: int, user_id: int | None, message: str, fields: dict,
                    image_path: str | None = None, parent_id: int | None = None) -> dict:
    with session_scope() as db:
        inc = Incident(thread_id=uuid.uuid4().hex, role=role, entity_id=entity_id, message=message, status="running",
                       image_path=image_path, parent_id=parent_id, payload={"input_fields": fields})
        db.add(inc)
        db.flush()
        incident_id, thread_id = inc.id, inc.thread_id
    return {"incident_id": incident_id, "role": role, "entity_id": entity_id, "user_id": user_id,
            "message": message, "image_path": image_path, "fields": fields, "_thread": thread_id}


def run_incident(state: dict, fresh_budget: bool = False) -> int:
    if fresh_budget:
        reset_budget()
    start_budget()  # one LLM-call budget per user request; child incidents share it
    state = dict(state)
    thread_id, incident_id = state.pop("_thread"), state["incident_id"]
    from app.graph.runtime import get_graph  # lazy: runtime -> build -> cascade -> runner
    try:
        get_graph().invoke(state, {"configurable": {"thread_id": thread_id}})
    except Exception as exc:  # never leave an incident silently stuck
        log.exception("incident %s failed", incident_id)
        with session_scope() as db:
            inc = db.get(Incident, incident_id)
            inc.status = "error"
            inc.payload = {**(inc.payload or {}), "error": f"{type(exc).__name__}: {exc}"[:500]}
    return incident_id


def start_incident(role: str, entity_id: int, user_id: int | None, message: str, fields: dict,
                   image_path: str | None = None, parent_id: int | None = None) -> int:
    """Create and run an incident to its first stopping point (done, or awaiting approval)."""
    return run_incident(create_incident(role, entity_id, user_id, message, fields, image_path, parent_id))


def start_incident_background(role: str, entity_id: int, user_id: int | None, message: str, fields: dict,
                              image_path: str | None = None) -> int:
    """Create the incident and run it in the background: the caller gets the id at once and polls for progress."""
    state = create_incident(role, entity_id, user_id, message, fields, image_path)
    if settings.run_mode == "inline":
        run_incident(state)
    else:
        _pool.submit(run_incident, state, True)
    return state["incident_id"]
