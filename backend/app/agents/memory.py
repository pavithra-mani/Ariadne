"""What the guardian agent remembers: who declined or delivered before (derived from the deal history itself, so
it cannot drift from the facts) and the lessons the agent chose to write down."""
import math
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import constants
from app.config import settings
from app.db.models import AgentNote, Deal, Entity

DECLINE_MEMORY_H = 24


def pair_declined_recently(db: Session, seller_id: int, buyer_id: int, product: str, hours: int = DECLINE_MEMORY_H) -> bool:
    since = datetime.utcnow() - timedelta(hours=hours)
    return db.query(Deal).filter(Deal.seller_id == seller_id, Deal.buyer_id == buyer_id, Deal.product == product,
                                 Deal.status == "rejected", Deal.created_at > since).count() > 0


def acceptance(db: Session, entity_id: int, role: str = "seller") -> dict:
    """Learned probability that this participant approves an offer, as a Beta posterior over its own past decisions.

    prior Beta(a, b) (constants) + approvals / declines observed in the deal history. Returns the posterior mean `p`, a
    ~90% credible interval and the evidence count `n`. With `memory_enabled=False` (ablation) the prior mean is returned.
    Decisions are read from the deals themselves, so the estimate can never drift from what actually happened."""
    a, b = constants.get("accept_prior_a"), constants.get("accept_prior_b")
    col, dec = (Deal.seller_id, Deal.seller_decision) if role == "seller" else (Deal.buyer_id, Deal.buyer_decision)
    ok = no = 0
    if settings.memory_enabled:
        rows = db.query(dec).filter(col == entity_id).all()
        ok, no = sum(1 for (x,) in rows if x == "approved"), sum(1 for (x,) in rows if x == "rejected")
    A, B = a + ok, b + no
    mean = A / (A + B)
    sd = math.sqrt(A * B / ((A + B) ** 2 * (A + B + 1)))
    return {"p": round(mean, 3), "lo": round(max(mean - 1.645 * sd, 0.0), 3), "hi": round(min(mean + 1.645 * sd, 1.0), 3), "n": ok + no, "approved": ok, "declined": no}


def vendor_stats(db: Session, entity_id: int) -> dict:
    """Track record of an entity as a seller and as a buyer, from the deal history."""
    out = {}
    for role, col in (("as_seller", Deal.seller_id), ("as_buyer", Deal.buyer_id)):
        rows = db.query(Deal).filter(col == entity_id).all()
        declined_by_me = [d for d in rows if d.status == "rejected" and d.rejected_by == entity_id]
        out[role] = {"offers": len(rows), "executed": len([d for d in rows if d.status == "executed"]),
                     "declined_by_them": len(declined_by_me), "declined_by_counterparty": len([d for d in rows if d.status == "rejected" and d.rejected_by not in (None, entity_id)]),
                     "pending": len([d for d in rows if d.status == "pending"]),
                     "recent_decline_reasons": [d.decline_reason for d in declined_by_me if d.decline_reason][-3:]}
    out["seller_acceptance"] = acceptance(db, entity_id, "seller")
    out["seller_reliability"] = out["seller_acceptance"]["p"]  # kept for older callers
    return out


def notes_for(db: Session, entity_ids: list[int], n: int = 8) -> list[dict]:
    q = db.query(AgentNote).filter(AgentNote.entity_id.in_(entity_ids)) if entity_ids else db.query(AgentNote)
    return [{"entity": db.get(Entity, r.entity_id).name if r.entity_id else None, "note": r.text, "at": r.created_at.isoformat(timespec="minutes")}
            for r in q.order_by(AgentNote.id.desc()).limit(n)]


def add_note(db: Session, entity_id: int | None, text: str, event_id: int | None = None) -> None:
    db.add(AgentNote(entity_id=entity_id, text=text[:300], event_id=event_id))
