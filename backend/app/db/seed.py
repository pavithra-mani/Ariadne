"""Synthetic but geographically real supply network around Ramanagara (Karnataka).

The design doc notes that no public registry of participants exists, so the network is
generated deterministically here. Replace by loading real records into the same tables.

    python -m app.db.seed --reset
"""
import math
import random
import sys
from datetime import date, timedelta

from sqlalchemy import text

from app import constants
from app.db.models import (Base, Entity, Inventory, Link, Target, User)
from app.db.session import engine, session_scope
from app.security import hash_password

DEMO_PASSWORD = "ariadne123"

TOWNS = {
    "Ramanagara": (12.7209, 77.2760), "Channapatna": (12.6518, 77.2067),
    "Kanakapura": (12.5465, 77.4194), "Magadi": (12.9570, 77.2247),
    "Bidadi": (12.7966, 77.3883), "Harohalli": (12.6667, 77.4167),
}
FIRST = ["Ravi", "Suresh", "Mahesh", "Lakshmi", "Gowramma", "Nagaraj", "Shivanna", "Kavitha",
         "Manjunath", "Rukmini", "Venkatesh", "Anitha", "Basavaraj", "Chandrappa", "Savitha",
         "Mohan", "Prakash", "Geetha", "Raju", "Shobha", "Krishne Gowda", "Puttaswamy"]
LAST = ["Gowda", "Naik", "Reddy", "Kumar", "Shetty", "Murthy", "Swamy", "Rao"]

# Finished/input products per entity kind: (product, is_finished, price/kg)
PRODUCTS = {
    "mulberry_farm": [("leaves", True, 4.0)],
    "silkworm_farm": [("cocoon", True, 480.0), ("leaves", False, 4.0)],
    "reeler": [("yarn", True, 4800.0), ("cocoon", False, 480.0)],
    "spinner": [("thread", True, 5600.0), ("yarn", False, 4800.0)],
}
SHELF = {"leaves": 3, "cocoon": 8, "yarn": 365, "thread": 365}


def km(a: Entity, b: Entity) -> float:
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dphi, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def build(db, rng: random.Random):
    today = date.today()
    towns = list(TOWNS.items())

    def place(kind, name, village=None, jitter=0.07, **kw):
        v, (la, lo) = (village, TOWNS[village]) if village else rng.choice(towns)
        e = Entity(kind=kind, name=name, village=v, lat=la + rng.uniform(-jitter, jitter),
                   lon=lo + rng.uniform(-jitter, jitter),
                   owner_name=f"{rng.choice(FIRST)} {rng.choice(LAST)}", **kw)
        db.add(e)
        return e

    mfs = [place("mulberry_farm", f"MF-{i + 1:02d}", area_acres=round(rng.uniform(1.5, 6), 1),
                 capacity_per_day=rng.randint(350, 500), balance=rng.randint(40, 300) * 1000)
           for i in range(10)]
    sfs = [place("silkworm_farm", f"SF-{i + 1:02d}", area_acres=round(rng.uniform(0.5, 3), 1),
                 capacity_per_day=rng.randint(50, 80), balance=rng.randint(40, 250) * 1000)
           for i in range(10)]
    rls = [place("reeler", f"Reeling Unit R{i + 1}", capacity_per_day=rng.randint(22, 30),
                 balance=rng.randint(8, 20) * 100000)
           for i in range(5)]
    sps = [place("spinner", f"Twisting Mill T{i + 1}", capacity_per_day=rng.randint(28, 36),
                 balance=rng.randint(10, 30) * 100000)
           for i in range(4)]
    db.flush()

    def nearest(src, pool, n, key=lambda e: e):
        return sorted(pool, key=lambda c: km(src, c))[:n]

    # Every reeler and spinner owns the warehouse where its finished goods are kept
    whs = []
    for owner, cap in [(r, 300) for r in rls] + [(sp, 400) for sp in sps]:
        w = Entity(kind="warehouse", name=f"{owner.name} Warehouse", village=owner.village,
                   lat=owner.lat + rng.uniform(-0.01, 0.01), lon=owner.lon + rng.uniform(-0.01, 0.01),
                   owner_name=owner.owner_name, serves=owner.kind, owner_id=owner.id, capacity_per_day=cap)
        db.add(w)
        whs.append((owner, w))
    db.flush()
    for owner, w in whs:
        owner.warehouse_id = w.id

    # Supply links: mulberry -> silkworm -> reeler -> spinner
    for s in sfs:
        for k, m in enumerate(nearest(s, mfs, 2)):
            db.add(Link(supplier_id=m.id, buyer_id=s.id, share=0.6 if k == 0 else 0.4))
    for s in sfs:
        near = nearest(s, rls, 2)
        for k, r in enumerate(near):
            db.add(Link(supplier_id=s.id, buyer_id=r.id, share=0.6 if k == 0 else 0.4))
    # make sure every reeler has at least 3 farmers
    db.flush()
    for r in rls:
        for s in nearest(r, sfs, 4):
            if not db.query(Link).filter_by(supplier_id=s.id, buyer_id=r.id).first():
                db.add(Link(supplier_id=s.id, buyer_id=r.id, share=0.3))
    for r in rls:
        for k, sp in enumerate(nearest(r, sps, 2)):
            db.add(Link(supplier_id=r.id, buyer_id=sp.id, share=0.6 if k == 0 else 0.4))
    for sp in sps:
        for r in nearest(sp, rls, 3):
            if not db.query(Link).filter_by(supplier_id=r.id, buyer_id=sp.id).first():
                db.add(Link(supplier_id=r.id, buyer_id=sp.id, share=0.3))

    # Inventory
    def inv(e, product, finished, price, on_hand, demand, lead, age=1):
        db.add(Inventory(entity_id=e.id, product=product, on_hand=round(on_hand, 1),
                         reserved=round(on_hand * rng.uniform(0, 0.1), 1),
                         daily_demand=round(demand, 1), demand_std=round(demand * 0.2, 1),
                         lead_time_days=lead, shelf_life_days=SHELF[product],
                         stocked_on=today - timedelta(days=age), unit_price=price,
                         is_finished=finished))

    for m in mfs:
        m.daily_throughput = round(m.capacity_per_day * rng.uniform(0.5, 0.85), 1)
        inv(m, "leaves", True, constants.price("leaves"), rng.uniform(900, 2500), m.daily_throughput * 0.8, 1, 0)
    for s in sfs:
        s.daily_throughput = round(s.capacity_per_day * rng.uniform(0.5, 0.85), 1)
        inv(s, "cocoon", True, constants.price("cocoon"), rng.uniform(120, 320), s.daily_throughput, 4, rng.randint(1, 3))
        inv(s, "leaves", False, constants.price("leaves"), rng.uniform(300, 800), rng.uniform(100, 200), 1, 0)
    for r in rls:
        r.daily_throughput = round(r.capacity_per_day * rng.uniform(0.6, 0.85), 1)
        inv(r, "yarn", True, constants.price("yarn"), rng.uniform(70, 160), r.daily_throughput * 0.9, 5, 20)
        inv(r, "cocoon", False, constants.price("cocoon"), rng.uniform(900, 1700), r.daily_throughput * 9, 3, rng.randint(1, 3))
    for sp in sps:
        sp.daily_throughput = round(sp.capacity_per_day * rng.uniform(0.6, 0.85), 1)
        inv(sp, "thread", True, constants.price("thread"), rng.uniform(80, 200), sp.daily_throughput * 0.9, 4, 15)
        inv(sp, "yarn", False, constants.price("yarn"), rng.uniform(100, 260), sp.daily_throughput, 5, 20)
    for sp in sps:
        db.add(Target(entity_id=sp.id, product="yarn", target_qty=round(sp.daily_throughput * 14, 0),
                      horizon_days=14))

    # Demo logins: one per entity, numbered per kind (mf1, sf1, reeler1, spinner1, wh1)
    short = {"mulberry_farm": "mf", "silkworm_farm": "sf", "reeler": "reeler", "spinner": "spinner"}
    pw = hash_password(DEMO_PASSWORD)
    for group in (mfs, sfs, rls, sps):
        for i, e in enumerate(group, 1):
            db.add(User(username=f"{short[e.kind]}{i}", password_hash=pw, role=e.kind,
                        entity_id=e.id, display_name=f"{e.owner_name} ({e.name})"))


def reseed_data():
    """Wipe operational data (keeps LangGraph checkpoint tables) and rebuild the demo network.
    Used by the test-suite and by POST /api/admin/reset-demo."""
    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    with session_scope() as db:
        build(db, random.Random(14))
    from app.rag.store import reset_collection
    reset_collection("incident_memory")


def seed(reset: bool = False):
    if reset:
        with engine.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    Base.metadata.create_all(engine)
    with session_scope() as db:
        if db.query(Entity).count():
            print("Database already seeded (use --reset to rebuild).")
            return
        build(db, random.Random(14))
    print("Seeded. Demo logins: mf1, sf1, reeler1, spinner1 / password:", DEMO_PASSWORD)


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
