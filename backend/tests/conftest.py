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
