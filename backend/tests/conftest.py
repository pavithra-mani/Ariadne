import pytest
from fastapi.testclient import TestClient

from app.db.models import Base
from app.db.seed import reseed_data
from app.db.session import engine, ensure_schema
from app.main import app


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
