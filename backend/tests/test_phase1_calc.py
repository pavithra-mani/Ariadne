import math
from datetime import date, timedelta
from types import SimpleNamespace

from app.calc.supply import capacity_utilisation, reorder_point, safety_stock, stock_status


def inv(**kw):
    base = dict(product="yarn", on_hand=100, reserved=0, daily_demand=10, demand_std=2,
                lead_time_days=4, shelf_life_days=365, stocked_on=date.today(), unit_price=1, is_finished=True)
    base.update(kw)
    return SimpleNamespace(**base)


def test_safety_stock_and_rop_formulae():
    ss = safety_stock(2, 4)
    assert math.isclose(ss, 1.65 * 2 * 2)
    assert math.isclose(reorder_point(10, 4, ss), 40 + ss)


def test_status_transitions():
    assert stock_status(inv(on_hand=200)).status == "ok"
    assert stock_status(inv(on_hand=45)).status == "reorder"   # below ROP (~46.6)
    assert stock_status(inv(on_hand=5)).status == "critical"  # below safety (6.6)


def test_sellable_excludes_safety_and_raw_inputs():
    s = stock_status(inv(on_hand=100, reserved=10))
    assert math.isclose(s.sellable, 90 - s.safety_stock)
    assert stock_status(inv(is_finished=False)).sellable == 0


def test_degradation_clock():
    s = stock_status(inv(product="cocoon", shelf_life_days=8, stocked_on=date.today() - timedelta(days=6)))
    assert s.degrades_in_days == 2


def test_capacity_utilisation():
    assert capacity_utilisation(15, 30) == 0.5
    assert capacity_utilisation(5, 0) == 0


def test_stock_entry_changes_numbers(client, auth):
    h = auth("reeler1")
    before = client.get("/api/dashboard", headers=h).json()["me"]["stock"][0]
    r = client.post("/api/stock", headers=h, json={"product": "yarn", "set_to": 500, "note": "test"})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    client.post("/api/stock", headers=h, json={"product": "yarn", "set_to": before["on_hand"]})


def test_only_buyers_of_yarn_set_targets(client, auth):
    assert client.post("/api/target", headers=auth("mf1"), json={"target_qty": 100}).status_code == 403
    assert client.post("/api/target", headers=auth("spinner1"), json={"target_qty": 300}).status_code == 200
    assert client.post("/api/target", headers=auth("reeler1"), json={"target_qty": 100}).status_code == 200  # reelers add demand too
