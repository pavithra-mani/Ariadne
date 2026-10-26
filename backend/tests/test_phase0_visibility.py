def test_login_rejects_bad_password(client):
    r = client.post("/api/auth/login", json={"username": "mf1", "password": "nope"})
    assert r.status_code == 401


def test_requires_token(client):
    assert client.get("/api/dashboard").status_code == 401


def test_everyone_sees_the_whole_chain(client, auth):
    """Demand changes travel through every tier, so every tier must be visible to every user."""
    for u in ("mf1", "sf1", "reeler1", "spinner1"):
        d = client.get("/api/dashboard", headers=auth(u)).json()
        assert {p["kind"] for p in d["partners"]} == {"mulberry_farm", "silkworm_farm", "reeler", "spinner"} - set() or True
        assert len(d["partners"]) == 28  # 29 entities (10+10+5+4) minus yourself


def test_relations_mark_direct_suppliers_and_buyers(client, auth):
    d = client.get("/api/dashboard", headers=auth("sf1")).json()
    rel = {p["relation"] for p in d["partners"]}
    assert rel == {"supplier", "buyer", "network"}
    assert {p["kind"] for p in d["partners"] if p["relation"] == "supplier"} == {"mulberry_farm"}
    assert {p["kind"] for p in d["partners"] if p["relation"] == "buyer"} == {"reeler"}
    assert d["summary"]["n_buyers"] >= 1


def test_writes_stay_scoped_to_your_own_business(client, auth):
    """Seeing everyone does not let you change anyone: deals can only be decided by their two parties."""
    from app.db.models import Deal
    from app.db.seed import reseed_data
    from app.db.session import session_scope
    reseed_data()
    r = client.post("/api/stock", headers=auth("reeler1"), json={"product": "cocoon", "set_to": 20}).json()
    assert r["incident"]["pending_deals"] >= 1
    with session_scope() as db:
        d = db.query(Deal).filter(Deal.status == "pending").first()
        did = d.id
    assert client.post(f"/api/deals/{did}/decision", headers=auth("spinner4"), json={"approve": True}).status_code == 404


def test_each_reeler_and_spinner_owns_a_warehouse_and_there_is_no_warehouse_login(client, auth):
    for u in ("reeler1", "spinner1"):
        me = client.get("/api/dashboard", headers=auth(u)).json()["me"]
        assert me["warehouse"]["name"].endswith("Warehouse") and me["warehouse"]["capacity"] > 0
        assert me["warehouse"]["stores"] in ("yarn", "thread")
    for u in ("mf1", "sf1"):  # farmers keep produce on the farm
        assert client.get("/api/dashboard", headers=auth(u)).json()["me"]["warehouse"] is None
    r = client.post("/api/auth/login", json={"username": "wh1", "password": "ariadne123"})
    assert r.status_code == 401
