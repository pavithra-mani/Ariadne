"""Network visibility.

The whole supply chain is visible to every signed-in user: the point of Ariadne is that a change at any tier
(a reeler's extra demand, a farm's disease) propagates through every tier and back, so each participant needs
to see the effect. What stays restricted is WRITE access: a user can only change their own stock, targets and
decide on deals they are a party to (enforced in the API routers, not here).

  relation: 'self' | 'supplier' (feeds me directly) | 'buyer' (I feed it directly) | 'network' (everyone else)
"""
from sqlalchemy.orm import Session

from app.db.models import Entity, Link, User


def suppliers_of(db: Session, entity_id: int) -> list[int]:
    return [l.supplier_id for l in db.query(Link).filter(Link.buyer_id == entity_id)]


def buyers_of(db: Session, entity_id: int) -> list[int]:
    return [l.buyer_id for l in db.query(Link).filter(Link.supplier_id == entity_id)]


def visible_entities(db: Session, user: User) -> dict[int, str]:
    """Map entity_id -> relation. Warehouses are part of their owner's entity, so they are not listed."""
    me = user.entity_id
    sup, buy = set(suppliers_of(db, me)), set(buyers_of(db, me))
    out: dict[int, str] = {}
    for (eid,) in db.query(Entity.id).filter(Entity.kind != "warehouse", Entity.active.is_(True)):
        out[eid] = "self" if eid == me else "supplier" if eid in sup else "buyer" if eid in buy else "network"
    return out


def can_see_entity(db: Session, user: User, entity_id: int) -> bool:
    return entity_id in visible_entities(db, user)
