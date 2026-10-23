def test_login_rejects_bad_password(client):
    r = client.post("/api/auth/login", json={"username": "mf1", "password": "nope"})
    assert r.status_code == 401


def test_requires_token(client):
    assert client.get("/api/dashboard").status_code == 401


def test_mulberry_farmer_sees_only_own_farm(client, auth):
    d = client.get("/api/dashboard", headers=auth("mf1")).json()
    assert d["me"]["kind"] == "mulberry_farm"
    assert d["partners"] == []


def test_silkworm_farmer_sees_mulberry_suppliers_and_reelers(client, auth):
    d = client.get("/api/dashboard", headers=auth("sf1")).json()
    kinds = {p["kind"] for p in d["partners"]}
    assert kinds == {"mulberry_farm", "reeler"}
    assert d["summary"]["n_buyers"] >= 1


def test_reeler_sees_spinners_and_farmers_not_other_reelers(client, auth):
    d = client.get("/api/dashboard", headers=auth("reeler1")).json()
    kinds = {p["kind"] for p in d["partners"]}
    assert kinds <= {"spinner", "silkworm_farm"} and "spinner" in kinds


def test_spinner_sees_only_his_reelers(client, auth):
    d = client.get("/api/dashboard", headers=auth("spinner1")).json()
    assert {p["kind"] for p in d["partners"]} == {"reeler"}


def test_each_reeler_and_spinner_owns_a_warehouse_and_there_is_no_warehouse_login(client, auth):
    for u in ("reeler1", "spinner1"):
        me = client.get("/api/dashboard", headers=auth(u)).json()["me"]
        assert me["warehouse"]["name"].endswith("Warehouse") and me["warehouse"]["capacity"] > 0
        assert me["warehouse"]["stores"] in ("yarn", "thread")
    for u in ("mf1", "sf1"):  # farmers keep produce on the farm
        assert client.get("/api/dashboard", headers=auth(u)).json()["me"]["warehouse"] is None
    r = client.post("/api/auth/login", json={"username": "wh1", "password": "ariadne123"})
    assert r.status_code == 401
