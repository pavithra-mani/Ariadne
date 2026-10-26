"""Role-aware chatbot intake + incident endpoints."""
import json
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Entity, Incident, User
from app.db.session import get_db
from app.graph.runner import start_incident_background
from app.security import current_user
from app.visibility.scope import visible_entities

router = APIRouter(prefix="/api", tags=["chat"])

ALLOWED_IMG = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMG = 10 * 1024 * 1024


HIDDEN = "Partner not visible to you"


PUBLIC_KEYS = ("finding", "rag", "risk", "supply_impact", "advisory", "memory", "plans", "outcome", "route", "error", "input_fields")


def redact_payload(payload: dict, vis: set[int], me: int) -> dict:
    """What a user may see of an incident's working data. Internal state (candidate lists, routes,
    case internals) is never sent, and partners outside the user's visibility keep their numbers
    but lose their identity."""
    import copy
    src = copy.deepcopy(payload or {})
    p = {k: src[k] for k in PUBLIC_KEYS if k in src}
    hidden_ids: set[int] = set()
    hidden_names: set[str] = set()

    def mask(row: dict, id_key: str, name_key: str):
        eid = row.get(id_key)
        if eid is not None and eid != me and eid not in vis:
            hidden_ids.add(eid)
            hidden_names.add(row.get(name_key, ""))
            row[name_key] = HIDDEN
            row["village"] = ""
    imp = p.get("supply_impact") or {}
    # recovery internals (names, exclusions) stay server-side; expose only what is needed
    imp["needs"] = [{"product": c["product"], "qty": c["qty"], "direction": c["direction"]} for c in imp.pop("cases", [])]
    for a in imp.get("affected", []) + imp.get("cascade", []):
        mask(a, "entity_id", "name")
    for u in (p.get("outcome") or {}).get("unresolved", []):
        mask(u, "buyer_id", "buyer_name")
    for c in p.get("plans", []):
        for k in ("buyer_name", "approver"):
            if c.get(k) in hidden_names:
                c[k] = HIDDEN
    fnd = p.get("finding") or {}
    fnd.pop("impact", None)  # duplicate of supply_impact with unmasked names
    p["hidden_partners"] = len(hidden_ids)
    return p


def incident_out(inc: Incident, full: bool = False) -> dict:
    out = {"id": inc.id, "role": inc.role, "entity_id": inc.entity_id, "kind": inc.kind,
           "is_issue": inc.is_issue, "status": inc.status, "date": inc.date, "solution": inc.solution,
           "severity": inc.severity, "urgency": inc.urgency, "priority": inc.priority,
           "parent_id": inc.parent_id, "message": inc.message, "created_at": inc.created_at,
           "has_image": bool(inc.image_path)}
    if full:
        out["payload"] = inc.payload
        out["trace"] = inc.trace
    return out


async def save_upload(image: UploadFile | None) -> str | None:
    if not image or not image.filename:
        return None
    ext = Path(image.filename).suffix.lower()
    if ext not in ALLOWED_IMG:
        raise HTTPException(400, f"Unsupported image type {ext}; use jpg, png or webp")
    data = await image.read()
    if len(data) > MAX_IMG:
        raise HTTPException(413, "Image too large (max 10 MB)")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(image.filename).stem)[:40]
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    path = Path(settings.upload_dir) / f"{uuid.uuid4().hex[:8]}_{safe}{ext}"
    path.write_bytes(data)
    return str(path)


@router.post("/chat")
async def chat(message: str = Form(""), fields: str = Form("{}"), image: UploadFile | None = File(None),
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        fields_d = json.loads(fields or "{}")
        assert isinstance(fields_d, dict)
    except Exception:
        raise HTTPException(400, "fields must be a JSON object")
    path = await save_upload(image)
    if not message.strip() and not path and not fields_d.get("incident_type"):
        raise HTTPException(400, "Send a message, a photo or a structured report")
    inc_id = start_incident_background(user.role, user.entity_id, user.id, message.strip(), fields_d, path)
    inc = db.get(Incident, inc_id)
    db.refresh(inc)
    out = incident_out(inc, full=True)
    out["payload"] = redact_payload(inc.payload, set(visible_entities(db, user)), user.entity_id)
    return out


@router.get("/incidents")
def list_incidents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Incident).filter(Incident.entity_id == user.entity_id).order_by(Incident.id.desc()).limit(100)
    return [incident_out(i) for i in rows]


def lineage(db: Session, user: User, inc: Incident) -> dict:
    """Linked (cascade) incidents, limited to entities the user is allowed to see."""
    vis = visible_entities(db, user)

    def brief(i: Incident) -> dict:
        e = db.get(Entity, i.entity_id)
        return {"id": i.id, "kind": i.kind, "status": i.status, "priority": i.priority, "entity": e.name,
                "date": i.date}
    parent = db.get(Incident, inc.parent_id) if inc.parent_id else None
    kids = db.query(Incident).filter(Incident.parent_id == inc.id).all()
    shown = [brief(k) for k in kids if k.entity_id in vis]
    return {"parent": brief(parent) if parent and parent.entity_id in vis else None,
            "has_hidden_parent": bool(parent and parent.entity_id not in vis),
            "children": shown, "hidden_children": len(kids) - len(shown)}


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inc = db.get(Incident, incident_id)
    if not inc or inc.entity_id != user.entity_id:  # same 404 either way: no existence leak
        raise HTTPException(404, "Incident not found")
    out = incident_out(inc, full=True)
    out["payload"] = redact_payload(inc.payload, set(visible_entities(db, user)), user.entity_id)
    out["lineage"] = lineage(db, user, inc)
    return out


@router.post("/incidents/{incident_id}/close")
def close_incident(incident_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Mark an incident as recovered: it stops reducing the supply outlook of downstream buyers."""
    inc = db.get(Incident, incident_id)
    if not inc or inc.entity_id != user.entity_id:
        raise HTTPException(404, "Incident not found")
    if inc.status == "awaiting_approval":
        raise HTTPException(409, "Decide the pending deals first")
    inc.status = "closed"
    db.commit()
    return incident_out(inc)
