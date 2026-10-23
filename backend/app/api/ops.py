"""Operational endpoints: stock entries, targets, ledger, deals, notifications."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.calc.outlook import outlook_for
from app.calc.supply import stock_status
from app.db.models import (AuditLog, Deal, Entity, Incident, Inventory, Ledger, Notification, Target, User)
from app.db.session import get_db
from app.security import current_user
from app.visibility.scope import visible_entities

router = APIRouter(prefix="/api", tags=["ops"])


class StockEntry(BaseModel):
    product: str
    set_to: float | None = Field(None, ge=0)
    delta: float | None = None
    daily_demand: float | None = Field(None, ge=0)
    note: str = ""


def _open_stock_incident(db: Session, user: User, product: str) -> Incident | None:
    rows = db.query(Incident).filter(Incident.entity_id == user.entity_id, Incident.kind == "low_stock",
                                     Incident.status.in_(["awaiting_approval", "open", "resuming"]))
    return next((i for i in rows if (i.payload or {}).get("finding", {}).get("product") == product
                 or (i.payload or {}).get("input_fields", {}).get("product") == product), None)


def _start_stock_incident(db: Session, user: User, product: str, lost_exposure: float = 0.0) -> dict:
    """Open (or return the already open) low-stock incident for this product."""
    from app.graph.runner import start_incident
    existing = _open_stock_incident(db, user, product)
    if existing:
        return {"incident_id": existing.id, "status": existing.status, "existing": True}
    iid = start_incident(user.role, user.entity_id, user.id, f"{product} stock is low", {"incident_type": "low_stock", "product": product, "lost_exposure": lost_exposure})
    db.expire_all()
    inc = db.get(Incident, iid)
    pending = db.query(Deal).filter(Deal.incident_id == iid, Deal.status == "pending").count()
    kids = db.query(Incident).filter(Incident.parent_id == iid).all()
    return {"incident_id": iid, "status": inc.status, "existing": False, "pending_deals": pending, "priority": inc.priority,
            "buyer_incidents": len(kids), "buyer_deals": db.query(Deal).filter(Deal.incident_id.in_([k.id for k in kids]), Deal.status == "pending").count() if kids else 0}


@router.post("/stock/{product}/replenish")
def replenish(product: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """'Ask Ariadne to fix this': open a low-stock incident for a product that is below target."""
    inv = db.query(Inventory).filter_by(entity_id=user.entity_id, product=product).first()
    if not inv:
        raise HTTPException(404, "You do not hold this product")
    st = stock_status(inv)
    me = db.get(Entity, user.entity_id)
    ol = next((o for o in outlook_for(db, me) if o["product"] == product), None)  # losses expected from suppliers
    lost = ol["expected_loss"] if ol else 0.0
    if st.status == "ok" and not (ol and ol["gap"] > 0):
        raise HTTPException(400, f"{product} stock is healthy ({st.days_of_cover:.1f} days of cover) and suppliers are on track; nothing to fix")
    return _start_stock_incident(db, user, product, lost)


@router.post("/stock")
def adjust_stock(body: StockEntry, user: User = Depends(current_user), db: Session = Depends(get_db)):
    inv = db.query(Inventory).filter_by(entity_id=user.entity_id, product=body.product).first()
    if not inv:
        raise HTTPException(404, "You do not hold this product")
    before = inv.on_hand
    before_st = stock_status(inv)
    before_status, sellable_before = before_st.status, before_st.sellable
    if body.set_to is not None:
        inv.on_hand = body.set_to
    elif body.delta is not None:
        inv.on_hand = max(inv.on_hand + body.delta, 0)
        if body.delta > 0:
            inv.stocked_on = date.today()  # fresh receipt resets the age clock
    if body.daily_demand is not None:
        inv.daily_demand, inv.demand_std = body.daily_demand, body.daily_demand * 0.2
    db.add(Ledger(entity_id=user.entity_id, product=body.product, delta_qty=inv.on_hand - before,
                  memo=body.note or "manual stock entry"))
    db.add(AuditLog(actor=user.username, action="stock_entry", ref=body.product,
                    details={"before": before, "after": inv.on_hand}))
    db.commit()
    st = stock_status(inv)
    out = st.dict()
    # a supplier's finished stock dropping hits the buyers who rely on it: assess them straight away
    drop = sellable_before - st.sellable if inv.is_finished else 0.0
    if drop > 1:
        from app.graph.propagate import stock_drop_children
        out["buyer_incidents"] = stock_drop_children(user.entity_id, body.product, drop)
    # a product pushed to its reorder point / below safety stock makes Ariadne act by itself
    if st.status in ("reorder", "critical") and before_status not in ("reorder", "critical"):
        out["incident"] = _start_stock_incident(db, user, body.product)
    return out


class TargetIn(BaseModel):
    target_qty: float = Field(gt=0)
    horizon_days: int = Field(14, gt=0, le=180)


@router.get("/target")
def get_target(user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = db.query(Target).filter_by(entity_id=user.entity_id).order_by(Target.id.desc()).first()
    return {"target_qty": t.target_qty, "horizon_days": t.horizon_days} if t else None


@router.post("/target")
def set_target(body: TargetIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "spinner":
        raise HTTPException(403, "Only spinners set yarn targets")
    db.add(Target(entity_id=user.entity_id, product="yarn", target_qty=body.target_qty,
                  horizon_days=body.horizon_days))
    db.commit()
    return body


@router.get("/ledger")
def ledger(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Ledger).filter_by(entity_id=user.entity_id).order_by(Ledger.id.desc()).limit(100)
    return [{"id": r.id, "deal_id": r.deal_id, "product": r.product, "delta_qty": r.delta_qty,
             "delta_money": r.delta_money, "memo": r.memo, "created_at": r.created_at} for r in rows]


def _can(eid: int, me: int, vis: set[int] | None, d: Deal) -> bool:
    return vis is None or eid == me or eid in vis or me in (d.seller_id, d.buyer_id, d.approver_id)


def _party(e: Entity, me: int, vis: set[int] | None, d: Deal) -> dict:
    ok = _can(e.id, me, vis, d)
    return {"id": e.id if ok else None, "name": e.name if ok else "Partner not visible to you", "village": e.village if ok else ""}


def deal_out(db: Session, d: Deal, me: int, vis: set[int] | None = None) -> dict:
    """`vis` = entity ids the viewer may see; parties outside it are anonymised (incident reporters
    can follow a proposal without learning who the other farms are)."""
    s, b, ap = db.get(Entity, d.seller_id), db.get(Entity, d.buyer_id), db.get(Entity, d.approver_id)
    return {"approver": ({"id": ap.id, "name": ap.name if _can(ap.id, me, vis, d) else "Partner not visible to you"} if ap else None), "id": d.id, "incident_id": d.incident_id, "deal_type": d.deal_type, "product": d.product,
            "quantity": d.quantity, "unit_price": d.unit_price, "transport_cost": d.transport_cost,
            "total": round(d.quantity * d.unit_price + d.transport_cost, 2), "status": d.status,
            "route": d.route if (vis is None or me in (d.seller_id, d.buyer_id, d.approver_id)) else {}, "note": d.note if (vis is None or me in (d.seller_id, d.buyer_id, d.approver_id)) else "", "created_at": d.created_at,
            "seller": _party(s, me, vis, d), "buyer": _party(b, me, vis, d),
            "approver_id": d.approver_id, "can_decide": d.status == "pending" and d.approver_id == me}


@router.get("/deals")
def deals(user: User = Depends(current_user), db: Session = Depends(get_db)):
    mine = db.query(Incident.id).filter(Incident.entity_id == user.entity_id)  # deals arising from my incidents
    q = db.query(Deal).filter(or_(Deal.buyer_id == user.entity_id, Deal.seller_id == user.entity_id,
                                  Deal.approver_id == user.entity_id, Deal.incident_id.in_(mine)))
    vis = set(visible_entities(db, user))
    return [deal_out(db, d, user.entity_id, vis) for d in q.order_by(Deal.id.desc()).limit(100)]


@router.get("/notifications")
def notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Notification).filter_by(entity_id=user.entity_id).order_by(Notification.id.desc()).limit(50)
    return [{"id": n.id, "message": n.message, "incident_id": n.incident_id, "deal_id": n.deal_id,
             "level": n.level, "read": n.read, "created_at": n.created_at} for n in rows]


@router.post("/notifications/read")
def mark_read(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.query(Notification).filter_by(entity_id=user.entity_id, read=False).update({"read": True})
    db.commit()
    return {"ok": True}
