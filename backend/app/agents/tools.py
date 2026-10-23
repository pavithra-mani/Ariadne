"""Read-only tools the LLM agents may call. Every tool is bound to the caller's own entity and obeys the
visibility rules; there are no write tools (money and stock only move through human-approved deals)."""
from dataclasses import dataclass, field
from typing import Callable

from app.calc.impact import get_inv
from app.calc.outlook import outlook_for
from app.calc.supply import stock_status
from app.db.models import Entity, Inventory
from app.db.session import session_scope
from app.memory.incidents import recall
from app.rag.agentic import agentic_rag
from app.visibility.scope import visible_entities


@dataclass
class ToolContext:
    entity_id: int
    role: str
    retrieved: list[dict] = field(default_factory=list)   # evidence registry: ref numbers are 1-based positions

    def register(self, passages: list[dict]) -> list[dict]:
        out = []
        for p in passages:
            existing = next((i for i, q in enumerate(self.retrieved) if q["id"] == p["id"]), None)
            if existing is None:
                self.retrieved.append(p)
                existing = len(self.retrieved) - 1
            out.append({"ref": existing + 1, "title": p["title"][:80], "source": p["source"], "text": p["text"][:700]})
        return out


def build_tools(ctx: ToolContext) -> list[Callable]:
    def get_my_stock(product: str = "") -> dict:
        """Current stock position of the user's own business: on-hand kg, available, safety stock, reorder point,
        sellable kg, days of cover, days until the stock degrades, and a status (ok/reorder/critical/degrading).
        Pass a product (leaves, cocoon, yarn, thread) or leave empty for all products held."""
        with session_scope() as db:
            q = db.query(Inventory).filter_by(entity_id=ctx.entity_id)
            if product:
                q = q.filter_by(product=product)
            return {"stock": [stock_status(i).dict() for i in q]}

    def get_supply_outlook() -> dict:
        """What the user's suppliers can ship against the user's own need, including losses from suppliers'
        open incidents: expected shortfall in kg, projected stock, reorder point and per-supplier detail."""
        with session_scope() as db:
            return {"outlook": outlook_for(db, db.get(Entity, ctx.entity_id))}

    def get_my_partners() -> dict:
        """The suppliers and buyers the user is allowed to see, with their stock status."""
        with session_scope() as db:
            vis = visible_entities(db, type("U", (), {"entity_id": ctx.entity_id, "role": ctx.role})())
            rows = []
            for eid, rel in vis.items():
                if eid == ctx.entity_id:
                    continue
                e = db.get(Entity, eid)
                inv = db.query(Inventory).filter_by(entity_id=eid)
                rows.append({"name": e.name, "relation": rel, "village": e.village,
                             "stock": [{"product": i.product, "status": stock_status(i).status} for i in inv]})
            return {"partners": rows}

    def search_knowledge(query: str, topic: str = "") -> dict:
        """Search the sericulture knowledge base (disease management, rearing, cocoon storage, reeling, yarn).
        Returns numbered passages; cite them by their `ref`. `topic` may be mulberry, silkworm, rearing, storage,
        reeling or policy to narrow the search. If nothing relevant exists the result says so: then do not guess."""
        res = agentic_rag(query, topics=[topic] if topic else None)
        if res.abstained:
            return {"found": False, "note": "No relevant passage in the knowledge base."}
        passages = [{"id": p.id, "title": p.title, "source": p.source, "text": p.text, "origin": p.origin, "publisher": p.publisher} for p in res.passages]
        return {"found": True, "passages": ctx.register(passages)}

    def recall_similar_incidents() -> dict:
        """Earlier incidents of the user's own business of the same kind, to spot recurring problems."""
        with session_scope() as db:
            e = db.get(Entity, ctx.entity_id)
            village = e.village
        return recall(ctx.entity_id, "disease", None, village)

    return [get_my_stock, get_supply_outlook, get_my_partners, search_knowledge, recall_similar_incidents]
