"""What each participant really needs to buy: the single definition shared by the agent's guardrails, the optimiser and the simulator."""
from app.calc.flow import solve
from app.calc.impact import INPUT_PRODUCT, get_inv
from app.calc.supply import stock_status
from app.db.models import Deal, Entity, Inventory


def pending_in(db, buyer_id: int, product: str) -> float:
    return sum(d.quantity for d in db.query(Deal).filter(Deal.buyer_id == buyer_id, Deal.product == product, Deal.status.in_(["pending", "approved"])))


def pending_out(db, seller_id: int, product: str) -> float:
    return sum(d.quantity for d in db.query(Deal).filter(Deal.seller_id == seller_id, Deal.product == product, Deal.status.in_(["pending", "approved"])))


def need_cap(db, buyer: Entity, product: str, flow: dict | None = None) -> float:
    """kg the buyer can really use: the larger of its order-up-to gap and the solver's shortfall, minus offers already pending."""
    inv = get_inv(db, buyer.id, product)
    if not inv:
        return 0.0
    st = stock_status(inv)
    gap_stock = st.reorder_point + inv.daily_demand * 3 - st.available
    flow = flow or solve(db)
    gap_flow = next((g["short_linked"] for g in flow["gaps"] if g["entity_id"] == buyer.id and g["product"] == product), 0.0)
    return max(max(gap_stock, gap_flow) - pending_in(db, buyer.id, product), 0.0)


def open_needs(db, flow: dict | None = None, min_kg: float = 1.0) -> dict[tuple[int, str], float]:
    """{(buyer_id, product): kg still to source}: solver shortfalls plus raw-input stock at/below reorder point."""
    flow = flow or solve(db)
    keys = {(g["entity_id"], g["product"]) for g in flow["gaps"]}
    for e in db.query(Entity).filter(Entity.kind != "warehouse", Entity.active.is_(True)):
        p = INPUT_PRODUCT.get(e.kind)
        inv = get_inv(db, e.id, p) if p else None
        if inv and stock_status(inv).status in ("reorder", "critical"):
            keys.add((e.id, p))
    out = {}
    for eid, p in keys:
        n = need_cap(db, db.get(Entity, eid), p, flow)
        if n >= min_kg:
            out[(eid, p)] = round(n, 1)
    return out
