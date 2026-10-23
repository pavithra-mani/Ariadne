"""Create an incident row and run the graph on it (used by the chat API and by cascades)."""
import logging
import uuid

from app.db.models import Incident
from app.db.session import session_scope

log = logging.getLogger("ariadne.runner")


def start_incident(role: str, entity_id: int, user_id: int | None, message: str, fields: dict,
                   image_path: str | None = None, parent_id: int | None = None) -> int:
    with session_scope() as db:
        inc = Incident(thread_id=uuid.uuid4().hex, role=role, entity_id=entity_id, message=message,
                       image_path=image_path, parent_id=parent_id, payload={"input_fields": fields})
        db.add(inc)
        db.flush()
        incident_id, thread_id = inc.id, inc.thread_id
    state = {"incident_id": incident_id, "role": role, "entity_id": entity_id, "user_id": user_id,
             "message": message, "image_path": image_path, "fields": fields}
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
