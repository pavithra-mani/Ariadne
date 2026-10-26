import os

os.environ.setdefault("ARIADNE_CLASSIFIER", "stub")  # tests use the file-name stub, not the trained models

import pytest
from fastapi.testclient import TestClient

from app.db.models import Base
from app.db.seed import reseed_data
from app.db.session import engine, ensure_schema
from app.config import settings
from app.llm.provider import set_llm_override
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def no_real_llm():
    """The suite must never spend the real Gemini/Groq quota (the dev .env holds live keys)."""
    settings.gemini_api_key = ""
    settings.groq_api_key = ""
    settings.run_mode = "inline"       # chat + guardian run synchronously so tests can assert on results
    settings.guardian_workers = 1
    yield


@pytest.fixture(autouse=True)
def reset_llm():
    set_llm_override(None)
    yield
    set_llm_override(None)


@pytest.fixture(scope="session", autouse=True)
def fresh_demo_data():
    Base.metadata.create_all(engine)
    ensure_schema()
    reseed_data()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def login(client, username, password="ariadne123"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def auth(client):
    return lambda u: login(client, u)


def decide_deals(client, auth, deal_ids, approve=True, sides=("buyer", "seller")):
    """Both parties of every deal decide (a deal moves stock and money only when the seller AND the buyer approve)."""
    from app.db.models import Deal, User
    from app.db.session import session_scope
    out = None
    for did in deal_ids:
        with session_scope() as db:
            d = db.get(Deal, did)
            ents = {"seller": d.seller_id, "buyer": d.buyer_id}
            users = {k: db.query(User).filter_by(entity_id=v).one().username for k, v in ents.items()}
        for side in sides:
            out = client.post(f"/api/deals/{did}/decision", headers=auth(users[side]), json={"approve": approve}).json()
    return out
