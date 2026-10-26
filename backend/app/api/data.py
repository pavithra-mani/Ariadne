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
    from app.llm.provider import llm_status
    from app.llm.structured import groq_enabled, stats
    from app.rag.store import collection
    from app.vision.classifier import get_classifier
    return {
        "groq": groq_enabled(), "langsmith": bool(settings.langsmith_api_key), "llm": llm_status(),
        "disease_fallback": settings.disease_fallback or None,
        "knowledge_chunks": collection("knowledge").count(),
        "classifiers": {c: {"StubClassifier": "stub", "GeminiVisionClassifier": "gemini"}.get(get_classifier(c).__class__.__name__, "model")
                        for c in ("mulberry", "silkworm")},
        "max_searches": settings.max_searches, "llm_stats": stats,
    }


@router.get("/eval/latest")
def eval_latest(user: User = Depends(current_user)):
    """Latest report per mode: 'agents' (Gemini on) and 'rules' (rule-based fallback), for side-by-side comparison."""
    import json
    from app.eval.run import RESULTS
    files = sorted(RESULTS.glob("*_2*.json")) if RESULTS.exists() else []
    latest: dict[str, dict] = {}
    for f in files:  # sorted by timestamp: later files overwrite earlier ones of the same mode
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if not isinstance(d, dict) or not isinstance(d.get("metrics"), dict) or not d["metrics"]:
            continue  # other result files live here too (simulator, agentic, vision): only Table-5 reports belong on this page
        d.pop("rows", None)
        mode = "agents" if (d.get("llm_agents") or f.name.startswith(("llm_", "agents_"))) else "rules"
        latest[mode] = {**d, "file": f.name, "mode": mode}
    return {"runs": list(latest.values())} if latest else None


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
