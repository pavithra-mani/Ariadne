"""Incident memory: recall earlier incidents on recurrence, update after every incident."""
from datetime import date

from app.rag.store import collection

COLLECTION = "incident_memory"


def _doc(kind: str, label: str | None, village: str, summary: str) -> str:
    return f"{kind} {label or ''} {village} {summary}".strip()


def recall(entity_id: int, kind: str, label: str | None, village: str = "", k: int = 3) -> dict:
    """Return earlier incidents of this entity (and similar-label incidents nearby)."""
    col = collection(COLLECTION)
    if col.count() == 0:
        return {"recurring": False, "count": 0, "similar": []}
    res = col.query(query_texts=[_doc(kind, label, village, "")], n_results=min(k * 3, col.count()),
                    where={"entity_id": entity_id})
    similar = []
    for i, m in enumerate(res["metadatas"][0]):
        same = m["kind"] == kind and (not label or m.get("label") == label)
        if same:
            similar.append({"incident_id": m["incident_id"], "kind": m["kind"], "label": m.get("label"),
                            "date": m["date"], "solution": m.get("solution", "")})
    similar = similar[:k]
    return {"recurring": bool(similar), "count": len(similar), "similar": similar}


def remember(incident_id: int, entity_id: int, kind: str, label: str | None, village: str,
             solution: str, when: date | None = None, parent_id: int | None = None) -> None:
    col = collection(COLLECTION)
    col.upsert(ids=[f"inc-{incident_id}"], documents=[_doc(kind, label, village, solution)],
               metadatas=[{"incident_id": incident_id, "entity_id": entity_id, "kind": kind,
                           "label": label or "", "date": str(when or date.today()),
                           "solution": solution[:300], "parent_id": parent_id or 0}])
