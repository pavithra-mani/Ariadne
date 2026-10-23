"""Role-based data visibility: the single choke point for what a user may read.

Section 1 of the design doc:
  mulberry farmer  -> own farm only
  silkworm farmer  -> own farm + the mulberry farmers supplying him + his collaborating reelers
  reeler           -> own unit + collaborating spinners + the silkworm farmers supplying him
  spinner          -> own mill + his reelers
  (a reeler's / spinner's warehouse is part of its own entity; there is no separate warehouse login)
API routers must obtain entities/inventory through these helpers, never by raw query.
"""
from sqlalchemy.orm import Session

from app.db.models import Link, User


def suppliers_of(db: Session, entity_id: int) -> list[int]:
    return [l.supplier_id for l in db.query(Link).filter(Link.buyer_id == entity_id)]


def buyers_of(db: Session, entity_id: int) -> list[int]:
    return [l.buyer_id for l in db.query(Link).filter(Link.supplier_id == entity_id)]


def visible_entities(db: Session, user: User) -> dict[int, str]:
    """Map entity_id -> relation ('self', 'supplier', 'buyer', 'linked')."""
    me = user.entity_id
    out: dict[int, str] = {me: "self"}
    if user.role == "silkworm_farm":
        out.update({i: "supplier" for i in suppliers_of(db, me)})
        out.update({i: "buyer" for i in buyers_of(db, me)})
    elif user.role == "reeler":
        out.update({i: "buyer" for i in buyers_of(db, me)})
        out.update({i: "supplier" for i in suppliers_of(db, me)})
    elif user.role == "spinner":
        out.update({i: "supplier" for i in suppliers_of(db, me)})
    return out


def can_see_entity(db: Session, user: User, entity_id: int) -> bool:
    return entity_id in visible_entities(db, user)
