"""Supply-impact calculations: who is exposed to a disruption and by how much.

All figures come from PostgreSQL stock + the supply links; nothing is LLM-generated.
"""
from sqlalchemy.orm import Session

from app.calc.supply import stock_status
from app.db.models import Entity, Inventory, Link, Target
from app import constants

INPUT_PRODUCT = {"silkworm_farm": "leaves", "reeler": "cocoon", "spinner": "yarn"}
OUTPUT_PRODUCT = {"mulberry_farm": "leaves", "silkworm_farm": "cocoon", "reeler": "yarn", "spinner": "thread"}


def get_inv(db: Session, entity_id: int, product: str) -> Inventory | None:
    return db.query(Inventory).filter_by(entity_id=entity_id, product=product).first()


def buyers(db: Session, supplier_id: int) -> list[tuple[Entity, float]]:
    rows = db.query(Link, Entity).join(Entity, Entity.id == Link.buyer_id).filter(Link.supplier_id == supplier_id)
    return [(e, l.share) for l, e in rows]


def suppliers(db: Session, buyer_id: int) -> list[tuple[Entity, float]]:
    rows = db.query(Link, Entity).join(Entity, Entity.id == Link.supplier_id).filter(Link.buyer_id == buyer_id)
    return [(e, l.share) for l, e in rows]


def expected_output(entity: Entity) -> float:
    return entity.daily_throughput * constants.get("horizon_days")


def exposure_for_buyer(db: Session, buyer: Entity, product: str, lost_qty: float) -> dict:
    """Inventory policy for a supplier-side loss.

    `lost_qty` is stock the buyer will not receive. The buyer is *at risk* when stock after the
    loss would fall below its reorder point (not only when it hits zero); the amount to bridge
    is the order-up-to level (reorder point + 3 days of use) minus that projected stock."""
    inv = get_inv(db, buyer.id, product)
    if not inv:
        return {"shortfall": lost_qty, "cover_days": 0.0, "buffer": 0.0, "projected": -lost_qty, "target": lost_qty}
    st = stock_status(inv)
    target = st.reorder_point + inv.daily_demand * 3
    projected = st.available - max(lost_qty, 0.0)
    shortfall = max(target - projected, 0.0) if (lost_qty > 0 and projected < st.reorder_point) else 0.0
    return {"shortfall": round(shortfall, 1), "cover_days": round(st.days_of_cover, 1),
            "buffer": round(max(st.available - st.reorder_point, 0.0), 1), "projected": round(projected, 1),
            "target": round(target, 1)}


def farmer_impact(db: Session, farm: Entity, loss_fraction: float) -> dict:
    """Disease at a mulberry or silkworm farm -> downstream exposure (design doc 2.3 steps 4-5)."""
    product = OUTPUT_PRODUCT[farm.kind]
    lost = round(expected_output(farm) * min(max(loss_fraction, 0), 1), 1)
    affected = []
    for buyer, share in buyers(db, farm.id):
        exp_qty = lost * share
        ex = exposure_for_buyer(db, buyer, product, exp_qty)
        affected.append({"entity_id": buyer.id, "name": buyer.name, "kind": buyer.kind, "village": buyer.village,
                         "product": product, "exposure_qty": round(exp_qty, 1), "lost_exposure": round(exp_qty, 1), **ex,
                         "at_risk": ex["shortfall"] > 0})
    # cascade: lost leaves at a mulberry farm reduce downstream cocoons at silkworm farms
    cascade = []
    if farm.kind == "mulberry_farm":
        for a in affected:
            if a["at_risk"]:
                cascade.append({"entity_id": a["entity_id"], "name": a["name"],
                                "cocoon_loss_est": round(a["lost_exposure"] / constants.get("leaf_per_kg_cocoon"), 1)})
    return {
        "product": product, "horizon_days": constants.get("horizon_days"), "expected_output": round(expected_output(farm), 1),
        "lost_qty": lost, "affected": affected, "n_affected": len(affected),
        "n_at_risk": len([a for a in affected if a["at_risk"]]),
        "total_shortfall": round(sum(a["shortfall"] for a in affected), 1),
        "at_risk": any(a["at_risk"] for a in affected), "cascade": cascade,
    }


def latest_target(db: Session, entity_id: int) -> Target | None:
    return db.query(Target).filter_by(entity_id=entity_id).order_by(Target.id.desc()).first()
