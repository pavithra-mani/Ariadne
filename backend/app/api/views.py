"""Serialisers that turn visible entities into dashboard payloads."""
from sqlalchemy.orm import Session

from app.calc.outlook import outlook_for
from app.calc.supply import entity_capacity, stock_status
from app.db.models import Entity, Inventory, User
from app.visibility.scope import buyers_of, suppliers_of, visible_entities


def entity_view(db: Session, e: Entity, relation: str) -> dict:
    invs = db.query(Inventory).filter(Inventory.entity_id == e.id).order_by(Inventory.id).all()
    stock = [stock_status(i).dict() for i in invs]
    wh = db.get(Entity, e.warehouse_id) if e.warehouse_id else None
    warehouse = None
    if wh:  # the owner's own warehouse holds its finished goods
        used = sum(i.on_hand for i in invs if i.is_finished)
        warehouse = {"name": wh.name, "village": wh.village, "capacity": wh.capacity_per_day, "used": round(used, 1),
                     "utilisation": round(min(used / wh.capacity_per_day, 1.5), 3) if wh.capacity_per_day else 0,
                     "stores": next((i.product for i in invs if i.is_finished), None)}
    return {
        "id": e.id, "kind": e.kind, "name": e.name, "owner_name": e.owner_name,
        "village": e.village, "lat": e.lat, "lon": e.lon, "relation": relation,
        "balance": round(e.balance, 2), "warehouse": warehouse,
        "serves": e.serves, "area_acres": e.area_acres,
        "capacity": entity_capacity(e),
        "stock": stock,
    }


def dashboard(db: Session, user: User) -> dict:
    vis = visible_entities(db, user)
    ents = {e.id: e for e in db.query(Entity).filter(Entity.id.in_(vis.keys()))}
    me = ents[user.entity_id]
    views = {i: entity_view(db, e, vis[i]) for i, e in ents.items()}
    mine = views.pop(me.id)
    mine["outlook"] = outlook_for(db, me)
    sup, buy = set(suppliers_of(db, me.id)), set(buyers_of(db, me.id))
    partners = [v for v in views.values()]
    return {
        "me": mine,
        "partners": partners,
        "summary": {
            "n_buyers": len([p for p in partners if p["id"] in buy]),
            "n_suppliers": len([p for p in partners if p["id"] in sup]),
            "alerts": [f"{s['product']}: {s['status']}" for s in mine["stock"] if s["status"] != "ok"],
        },
    }
