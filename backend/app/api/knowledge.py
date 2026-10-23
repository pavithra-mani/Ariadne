from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.db.models import User
from app.rag.agentic import agentic_rag
from app.rag.store import collection
from app.security import current_user

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    topic: str | None = None


@router.post("/ask")
def ask(body: Ask, user: User = Depends(current_user)):
    return agentic_rag(body.question, topics=[body.topic] if body.topic else None).dict()


@router.get("/stats")
def stats(user: User = Depends(current_user)):
    col = collection("knowledge")
    metas = col.get(include=["metadatas"])["metadatas"]
    topics: dict[str, int] = {}
    for m in metas:
        topics[m["topic"]] = topics.get(m["topic"], 0) + 1
    return {"chunks": col.count(), "topics": topics,
            "documents": len({m["source"] for m in metas})}
