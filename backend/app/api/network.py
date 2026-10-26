"""Whole-chain views: the flow solver (what-if), the guardian agent's activity, and live constants."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import constants
from app.calc.flow import solve
from app.db.models import AgentEvent, Entity, User
from app.db.session import get_db
from app.security import current_user

router = APIRouter(prefix="/api", tags=["network"])


class WhatIf(BaseModel):
    entity_id: int
    qty: float = Field(gt=0, description="kg of extra demand: yarn wanted (spinner) or extra orders for the entity's output")
    horizon_days: float | None = Field(None, gt=0, le=90)


@router.get("/flow")
def flow(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """The chain as it stands: per tier and per entity, what is requested, what can be delivered and what is short."""
    return solve(db)


@router.post("/flow/what-if")
def what_if(body: WhatIf, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Simulate extra demand at any entity (nothing is saved, no agent is triggered)."""
    e = db.get(Entity, body.entity_id)
    if not e or e.kind == "warehouse":
        raise HTTPException(404, "Entity not found")
    base = solve(db, horizon=body.horizon_days)
    sim = solve(db, extra_demand={body.entity_id: body.qty}, horizon=body.horizon_days)
    return {"entity": {"id": e.id, "name": e.name, "kind": e.kind}, "qty": body.qty, "before": base, "after": sim}


@router.get("/agent/activity")
def activity(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """What the guardian agent noticed and did, newest first."""
    rows = db.query(AgentEvent).order_by(AgentEvent.id.desc()).limit(40).all()
    names = {e.id: e.name for e in db.query(Entity).filter(Entity.id.in_({r.entity_id for r in rows if r.entity_id}))} if rows else {}
    return [{"id": r.id, "entity": names.get(r.entity_id), "product": r.product, "reason": r.reason, "status": r.status,
             "opened": (r.result or {}).get("opened", []), "flow": (r.result or {}).get("flow"), "error": (r.result or {}).get("error"),
             "mode": (r.result or {}).get("mode"), "summary": (r.result or {}).get("summary"), "fallback_reason": (r.result or {}).get("fallback_reason"),
             "steps": (r.result or {}).get("steps", []), "offers": (r.result or {}).get("offers", []), "residual": (r.result or {}).get("residual", []),
             "llm_calls": (r.result or {}).get("llm_calls"), "invalid_tool_calls": (r.result or {}).get("invalid_tool_calls"), "seconds": (r.result or {}).get("seconds"),
             "created_at": r.created_at, "handled_at": r.handled_at} for r in rows]


@router.get("/system/constants")
def get_constants(user: User = Depends(current_user)):
    return constants.snapshot()


@router.post("/system/constants/refresh")
def refresh_constants(user: User = Depends(current_user)):
    """Re-check the live sources now (normally this runs at start-up)."""
    from app.refresh.live_data import refresh
    return refresh(force=True)
