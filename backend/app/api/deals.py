"""Human-in-the-loop decisions on proposed deals; resumes the paused LangGraph run."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from langgraph.types import Command
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.agents.guardian import submit
from app.api.chat import incident_out
from app.api.ops import deal_out
from app.calc.impact import get_inv
from app.db.models import AuditLog, Deal, Entity, Incident, Notification, User
from app.db.session import get_db
from app.graph.runtime import get_graph
from app.security import current_user

router = APIRouter(prefix="/api", tags=["deals"])


class Decision(BaseModel):
    approve: bool
    reason: str = Field("", max_length=300)  # why a deal was declined: the agent reads it next time


@router.get("/approvals")
def approvals(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Deals waiting for THIS user's decision, as seller or as buyer (both sides must approve)."""
    me = user.entity_id
    rows = db.query(Deal).filter(Deal.status == "pending", or_(
        and_(Deal.seller_id == me, Deal.seller_decision == "pending"),
        and_(Deal.buyer_id == me, Deal.buyer_decision == "pending"))).order_by(Deal.id)
    return [deal_out(db, d, me) for d in rows]


@router.post("/deals/{deal_id}/decision")
def decide(deal_id: int, body: Decision, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = db.query(Deal).filter(Deal.id == deal_id).with_for_update().first()  # serialise concurrent decisions
    me = user.entity_id
    if not d or me not in (d.seller_id, d.buyer_id):
        raise HTTPException(404, "Deal not found")
    if d.status != "pending":
        raise HTTPException(409, f"Deal already {d.status}")
    side = "seller" if me == d.seller_id else "buyer"
    if getattr(d, f"{side}_decision") != "pending":
        raise HTTPException(409, f"You already {getattr(d, f'{side}_decision')} this deal")
    setattr(d, f"{side}_decision", "approved" if body.approve else "rejected")
    d.decided_by, d.decided_at = user.id, datetime.utcnow()
    other_id = d.buyer_id if side == "seller" else d.seller_id
    other = db.get(Entity, other_id)
    me_name = db.get(Entity, me).name
    if not body.approve:  # either side can say no: release the stock held for this proposal and tell the other side
        d.status, d.rejected_by, d.decline_reason = "rejected", me, body.reason.strip()
        inv = get_inv(db, d.seller_id, d.product)
        if inv:
            inv.reserved = max(inv.reserved - d.quantity, 0)
        db.add(Notification(entity_id=other_id, incident_id=d.incident_id, deal_id=d.id, level="info",
                            message=f"{me_name} declined the {d.quantity:.0f} kg {d.product} deal. Ariadne is looking for another option."))
    elif d.seller_decision == d.buyer_decision == "approved":
        d.status = "approved"
    else:
        db.add(Notification(entity_id=other_id, incident_id=d.incident_id, deal_id=d.id, level="deal",
                            message=f"{me_name} approved the {d.quantity:.0f} kg {d.product} deal. Waiting for your decision."))
    db.add(AuditLog(actor=user.username, action=f"deal_{side}_" + ("approved" if body.approve else "rejected"),
                    ref=str(deal_id), details={"incident": d.incident_id, "reason": body.reason.strip()}))
    db.commit()

    if d.status == "approved":  # both sides said yes: execute now, without waiting for sibling deals of the same incident
        from app.graph.recovery import confirm_deal, execute_deal
        if execute_deal(db, d.id) == "executed":
            confirm_deal(db, d, d.incident_id)
        db.commit()
        db.refresh(d)
        if d.status == "failed_funds":
            db.add(Notification(entity_id=d.buyer_id, deal_id=d.id, level="alert", message=f"Deal #{d.id} could not complete: not enough balance for ₹{d.quantity * d.unit_price + d.transport_cost:,.0f}."))
            db.commit()
    if d.status in ("executed", "rejected", "failed_funds"):  # the outcome is a change in the world: wake the guardian
        submit(None, d.product, "deal_executed" if d.status == "executed" else "deal_rejected",
               {"parties": [[d.buyer_id, d.product], [d.seller_id, d.product]], "deal_id": d.id})
    if d.origin == "agent":  # a deal the guardian agent proposed has no graph to resume
        return {"deal": deal_out(db, d, me), "graph_resumed": False, "incident": None}

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
            db.refresh(d)
            # the incident is closed now, so declined deals can finally be re-sourced (executed ones were announced when they ran)
            for x in db.query(Deal).filter(Deal.incident_id == inc.id, Deal.status == "rejected"):
                submit(None, x.product, "deal_rejected", {"parties": [[x.buyer_id, x.product], [x.seller_id, x.product]], "deal_id": x.id})
    return {"deal": deal_out(db, d, me), "graph_resumed": resumed,
            "incident": incident_out(inc) if inc else None}
