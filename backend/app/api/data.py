from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.views import dashboard
from app.db.models import User
from app.db.session import get_db
from app.security import current_user

router = APIRouter(prefix="/api", tags=["data"])


@router.get("/dashboard")
def get_dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return dashboard(db, user)


@router.get("/system/status")
def system_status(user: User = Depends(current_user)):
    from app.config import settings
    from app.llm.structured import groq_enabled, stats
    from app.rag.store import collection
    from app.vision.classifier import get_classifier
    return {
        "groq": groq_enabled(), "langsmith": bool(settings.langsmith_api_key),
        "knowledge_chunks": collection("knowledge").count(),
        "classifiers": {c: ("stub" if get_classifier(c).__class__.__name__ == "StubClassifier" else "model")
                        for c in ("mulberry", "silkworm")},
        "max_searches": settings.max_searches, "llm_stats": stats,
    }


@router.get("/eval/latest")
def eval_latest(user: User = Depends(current_user)):
    import json
    from app.eval.run import RESULTS
    files = sorted(RESULTS.glob("baseline_*.json")) if RESULTS.exists() else []
    if not files:
        return None
    d = json.loads(files[-1].read_text())
    d.pop("rows", None)
    d["file"] = files[-1].name
    d["runs"] = len(files)
    return d


@router.post("/system/reset-demo")
def reset_demo(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Restore the seeded demo network (wipes incidents, deals, ledger, notifications, memory)."""
    from fastapi import HTTPException
    from app.config import settings
    if not settings.allow_demo_reset:
        raise HTTPException(403, "Demo reset is disabled (set ALLOW_DEMO_RESET=true)")
    from app.db.seed import reseed_data
    db.rollback()  # release this request's read locks, otherwise TRUNCATE waits on our own session
    db.close()
    reseed_data()
    return {"ok": True}
