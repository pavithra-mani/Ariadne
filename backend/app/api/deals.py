"""Human-in-the-loop decisions on proposed deals; resumes the paused LangGraph run."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from langgraph.types import Command
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.chat import incident_out
from app.api.ops import deal_out
from app.calc.impact import get_inv
from app.db.models import AuditLog, Deal, Incident, User
from app.db.session import get_db
from app.graph.runtime import get_graph
from app.security import current_user

router = APIRouter(prefix="/api", tags=["deals"])


class Decision(BaseModel):
    approve: bool


@router.get("/approvals")
def approvals(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Deal).filter(Deal.approver_id == user.entity_id, Deal.status == "pending").order_by(Deal.id)
    return [deal_out(db, d, user.entity_id) for d in rows]


@router.post("/deals/{deal_id}/decision")
def decide(deal_id: int, body: Decision, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.query(Deal).filter(Deal.id == deal_id).with_for_update().first()  # serialise concurrent decisions
    if not d or d.approver_id != user.entity_id:
        raise HTTPException(404, "Deal not found")
    if d.status != "pending":
        raise HTTPException(409, f"Deal already {d.status}")
    d.status = "approved" if body.approve else "rejected"
    d.decided_by, d.decided_at = user.id, datetime.utcnow()
    if not body.approve:  # release the stock held for this proposal
        inv = get_inv(db, d.seller_id, d.product)
        if inv:
            inv.reserved = max(inv.reserved - d.quantity, 0)
    db.add(AuditLog(actor=user.username, action="deal_approved" if body.approve else "deal_rejected",
                    ref=str(deal_id), details={"incident": d.incident_id}))
    db.commit()

    resumed = False
    inc = db.get(Incident, d.incident_id) if d.incident_id else None
    if inc:
        pending = db.query(Deal).filter(Deal.incident_id == inc.id, Deal.status == "pending").count()
        # claim the resume atomically so two simultaneous last decisions cannot resume the graph twice
        claimed = pending == 0 and db.query(Incident).filter(
            Incident.id == inc.id, Incident.status == "awaiting_approval").update({"status": "resuming"}) == 1
        db.commit()
        if claimed:
            decisions = {str(x.id): x.status for x in db.query(Deal).filter(Deal.incident_id == inc.id)}
            get_graph().invoke(Command(resume=decisions), {"configurable": {"thread_id": inc.thread_id}})
            resumed = True
            db.refresh(inc)
    return {"deal": deal_out(db, d, user.entity_id), "graph_resumed": resumed,
            "incident": incident_out(inc) if inc else None}
