"""Supply outlook: what a buyer can expect from its suppliers, given their stock and open incidents.

Shown on the buyer's dashboard so a supplier's disease report or stock change is visible downstream
immediately. Pure read-side maths: the automatic reaction lives in graph/propagate.py.
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.calc.impact import INPUT_PRODUCT, get_inv, suppliers
from app.calc.supply import stock_status
from app.db.models import Entity, Incident

HORIZON_DAYS = {"leaves": 3, "cocoon": 5, "yarn": 7}  # days of use the outlook looks ahead (leaves are perishable)
ACTIVE_DAYS = 14  # an incident keeps affecting downstream supply this long unless marked recovered


def active_loss(db: Session, entity_id: int) -> tuple[float, int | None]:
    """Largest unresolved output-loss fraction (0..1) from the entity's recent incidents, and its id."""
    since = date.today() - timedelta(days=ACTIVE_DAYS)
    rows = db.query(Incident).filter(Incident.entity_id == entity_id, Incident.date >= since,
                                     Incident.status.notin_(["closed", "error"]), Incident.is_issue.is_(True))
    best, src = 0.0, None
    for i in rows:
        p = i.payload or {}
        v = max((p.get("finding") or {}).get("loss_fraction") or 0.0, (p.get("outcome") or {}).get("residual_loss_fraction") or 0.0)
        if v > best:
            best, src = v, i.id
    return best, src


def outlook_for(db: Session, buyer: Entity) -> list[dict]:
    """One entry per raw-input product the buyer depends on (leaves / cocoon / yarn).

    Expected shortfall = (a) what suppliers cannot ship from stock against this buyer's share of its
    need over the horizon, plus (b) the output suppliers will lose to open incidents. Both change as
    soon as a supplier edits its stock or reports a problem."""
    product = INPUT_PRODUCT.get(buyer.kind)
    inv = get_inv(db, buyer.id, product) if product else None
    if not inv:
        return []
    H = HORIZON_DAYS[product]
    st = stock_status(inv)
    need = inv.daily_demand * H
    sups = suppliers(db, buyer.id)
    total_share = sum(sh for _, sh in sups) or 1.0
    rows, expected_loss = [], 0.0
    for s, sh in sups:
        s_inv = get_inv(db, s.id, product)
        if not s_inv:
            continue
        s_st = stock_status(s_inv)
        loss, src = active_loss(db, s.id)
        want = need * sh / total_share                                  # this supplier's share of my need
        covered = min(want, s_st.sellable * (1 - loss))                  # what its stock can ship
        flow_loss = loss * s.daily_throughput * H * sh                   # output it will not produce for me
        short = (want - covered) + flow_loss
        expected_loss += short
        rows.append({"entity_id": s.id, "name": s.name, "village": s.village, "share": round(sh / total_share, 2),
                     "sellable": round(s_st.sellable, 1), "status": s_st.status, "loss_pct": round(loss * 100),
                     "incident_id": src, "want": round(want, 1), "covered": round(covered, 1), "at_stake": round(short, 1)})
    projected = st.available - expected_loss
    target = st.reorder_point + inv.daily_demand * 3
    return [{"product": product, "horizon_days": H, "need": round(need, 1), "on_hand": round(st.on_hand, 1),
             "available": round(st.available, 1), "reorder_point": round(st.reorder_point, 1),
             "expected_loss": round(expected_loss, 1), "projected": round(projected, 1), "target": round(target, 1),
             "gap": round(max(target - projected, 0.0), 1) if projected < st.reorder_point else 0.0,
             "status": "ok" if projected >= st.reorder_point else "at_risk", "suppliers": rows}]
