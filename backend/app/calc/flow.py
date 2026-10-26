"""Network flow solver: how a change in demand at any tier propagates through the whole chain and back.

Chain (top = demand side):  spinner <- reeler <- silkworm farm <- mulberry farm   (product flows left to right)

Each round has two passes, repeated until nothing changes:
  DOWN  (demand travels up the chain): a tier's requested output turns into the input it needs
        (kg output x conversion ratio, minus input already in stock), split across its suppliers by link share.
  UP    (supply travels down the chain): each supplier can deliver what its sellable stock plus production
        (limited by capacity, disease losses and the inputs it itself receives) allows; buyers receive that
        pro rata. A buyer that receives less produces less, which shrinks what ITS buyers receive.
  SPILL what a buyer cannot get from its linked suppliers is asked from the nearest other suppliers of the same
        tier that still have spare potential; those suppliers then need more input themselves, so the next
        round repeats DOWN/UP with the extra demand until the numbers are consistent.

Outputs per entity: requested / feasible output, input needed and received, `short_linked` (what its current
suppliers cannot deliver: this is what the guardian agent acts on) and `short_final` (what is still missing
after the other suppliers in the network have been counted). Pure maths over PostgreSQL stock; no LLM.
"""
import math
from collections import defaultdict
from datetime import date

from sqlalchemy.orm import Session

from app import constants
from app.calc.impact import INPUT_PRODUCT, OUTPUT_PRODUCT
from app.calc.outlook import active_loss
from app.calc.supply import stock_status
from app.db.models import Entity, Inventory, Link, Target

TIERS = ["spinner", "reeler", "silkworm_farm", "mulberry_farm"]  # demand side first
MAX_ROUNDS = 6
EPS = 0.5  # kg


def ratio(kind: str) -> float:
    """Input kg needed per output kg."""
    return {"spinner": constants.get("yarn_per_thread"), "reeler": constants.get("cocoon_per_yarn"),
            "silkworm_farm": constants.get("leaf_per_kg_cocoon")}.get(kind, 0.0)


def _km(a: Entity, b: Entity) -> float:
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b.lon - a.lon) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def active_target(db: Session, entity_id: int, horizon: float) -> Target | None:
    t = db.query(Target).filter_by(entity_id=entity_id).order_by(Target.id.desc()).first()
    if t and t.created_at and (date.today() - t.created_at.date()).days > t.horizon_days:
        return None  # an expired target no longer drives demand
    return t


def solve(db: Session, extra_demand: dict[int, float] | None = None, horizon: float | None = None) -> dict:
    """`extra_demand`: {entity_id: kg} what-if demand (spinner: yarn it wants to receive; others: extra orders for its
    output), over `horizon` days. Stored Targets are always included."""
    H = float(horizon or constants.get("horizon_days"))
    ents = {e.id: e for e in db.query(Entity).filter(Entity.kind != "warehouse", Entity.active.is_(True))}
    inv: dict[tuple[int, str], Inventory] = {(i.entity_id, i.product): i for i in db.query(Inventory)}
    sup_links: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for l in db.query(Link):
        if l.supplier_id in ents and l.buyer_id in ents:
            sup_links[l.buyer_id].append((l.supplier_id, l.share))

    info: dict[int, dict] = {}
    for e in ents.values():
        out_p, in_p = OUTPUT_PRODUCT[e.kind], INPUT_PRODUCT.get(e.kind)
        oi, ii = inv.get((e.id, out_p)), inv.get((e.id, in_p)) if in_p else None
        loss, _ = active_loss(db, e.id)
        ext = float((extra_demand or {}).get(e.id, 0.0))
        t = active_target(db, e.id, H)
        if t:
            ext += t.target_qty * H / max(t.horizon_days, 1)
        base_in = ii.daily_demand * H if ii else 0.0
        info[e.id] = {
            "id": e.id, "name": e.name, "kind": e.kind, "village": e.village, "in_product": in_p, "out_product": out_p,
            "sellable": stock_status(oi).sellable if oi else 0.0,
            "avail_in": stock_status(ii).available if ii else 0.0,
            "cap": e.capacity_per_day * H * (1 - loss), "loss_pct": round(loss * 100), "ratio": ratio(e.kind),
            # the spinner's demand is the yarn it wants to receive; for others it is extra orders on their output
            "top_in": max(base_in, ext) if e.kind == "spinner" else 0.0,
            "ext_out": 0.0 if e.kind == "spinner" else ext,
        }

    extras: dict[tuple[int, int], float] = defaultdict(float)  # (buyer, supplier) -> spilled request
    rounds, first_short = [], {}
    for rnd in range(1, MAX_ROUNDS + 1):
        for r in info.values():
            r.update(request_out=r["ext_out"], need_in=0.0, from_sup=0.0, received=0.0, unmet_cap=0.0)
        req_from: dict[tuple[int, int], float] = defaultdict(float)  # (buyer, supplier) -> kg requested
        # ---- DOWN: demand travels up the chain
        for kind in TIERS:
            for e in [r for r in info.values() if r["kind"] == kind]:
                if kind == "spinner":
                    need_in = e["top_in"]
                else:
                    produce = max(e["request_out"] - e["sellable"], 0.0)
                    produce_cap = min(produce, e["cap"])
                    e["unmet_cap"] = produce - produce_cap
                    need_in = produce_cap * e["ratio"]
                e["need_in"] = need_in
                e["from_sup"] = max(need_in - e["avail_in"], 0.0)
                links = sup_links.get(e["id"], [])
                tot = sum(sh for _, sh in links) or 1.0
                for sid, sh in links:
                    q = e["from_sup"] * sh / tot + extras.get((e["id"], sid), 0.0)
                    req_from[(e["id"], sid)] += q
                    info[sid]["request_out"] += q
                for (b, sid), q in extras.items():  # spilled requests to suppliers that are not linked
                    if b == e["id"] and all(sid != s for s, _ in links):
                        req_from[(b, sid)] += q
                        info[sid]["request_out"] += q
        # ---- UP: supply travels down the chain
        for kind in reversed(TIERS):
            for e in [r for r in info.values() if r["kind"] == kind]:
                if kind != "mulberry_farm":
                    got = 0.0
                    for (b, sid), q in req_from.items():
                        if b == e["id"]:
                            s = info[sid]
                            frac = min(s["feasible"] / s["request_out"], 1.0) if s["request_out"] > EPS else 1.0
                            got += q * frac
                    e["received"] = got
                    produce_possible = min(e["cap"], (e["avail_in"] + got) / e["ratio"]) if e["ratio"] else 0.0
                else:
                    produce_possible = e["cap"]
                e["potential"] = e["sellable"] + produce_possible
                e["feasible"] = min(e["request_out"], e["potential"]) if kind != "spinner" else e["potential"]
        for key in list(extras):  # keep only the spilled requests a supplier actually delivered
            s = info[key[1]]
            extras[key] *= min(s["feasible"] / s["request_out"], 1.0) if s["request_out"] > EPS else 1.0
        for e in info.values():
            extra_got = sum(q for (b, _), q in extras.items() if b == e["id"])
            e["short"] = max(e["from_sup"] - (e["received"] - extra_got), 0.0) if e["kind"] != "mulberry_farm" else 0.0
        if rnd == 1:
            first_short = {i: e["short"] for i, e in info.items()}
        # ---- SPILL: ask other suppliers of the tier below for what linked ones cannot deliver
        spare = {i: max(e["potential"] - e["request_out"], 0.0) for i, e in info.items()}
        spilled = 0.0
        for kind in TIERS[:-1]:
            sup_kind = TIERS[TIERS.index(kind) + 1]
            for e in sorted([r for r in info.values() if r["kind"] == kind and r["short"] > EPS], key=lambda r: -r["short"]):
                left = e["short"]
                for s in sorted((r for r in info.values() if r["kind"] == sup_kind and spare[r["id"]] > EPS),
                                key=lambda r: _km(ents[e["id"]], ents[r["id"]])):
                    take = min(left, spare[s["id"]])
                    extras[(e["id"], s["id"])] += take
                    spare[s["id"]] -= take
                    left -= take
                    spilled += take
                    if left <= EPS:
                        break
        rounds.append({"round": rnd, "short_kg": round(sum(e["short"] for e in info.values())), "spilled_kg": round(spilled)})
        if spilled <= EPS:
            break

    rows, gaps = [], []
    for e in info.values():
        sl, sf = first_short.get(e["id"], 0.0), e["short"]
        status = "short" if sf > EPS else "rerouted" if sl > EPS else "tight" if e["unmet_cap"] > EPS else "ok"
        row = {k: (round(v, 1) if isinstance(v, float) else v) for k, v in e.items() if k not in ("ratio",)}
        row.update(short_linked=round(sl, 1), short_final=round(sf, 1), status=status,
                   unmet_capacity=round(e["unmet_cap"], 1), requested_out=round(e["request_out"], 1),
                   feasible_out=round(e["feasible"], 1))
        rows.append(row)
        if sl > max(EPS, 0.03 * e["need_in"]):
            gaps.append({"entity_id": e["id"], "name": e["name"], "kind": e["kind"], "product": e["in_product"],
                         "short_linked": round(sl, 1), "short_final": round(sf, 1), "need_in": round(e["need_in"], 1)})
    by_tier = []
    for kind in TIERS:
        rs = [r for r in rows if r["kind"] == kind]
        by_tier.append({"kind": kind, "n": len(rs), "in_product": INPUT_PRODUCT.get(kind), "out_product": OUTPUT_PRODUCT[kind],
                        "requested_out": round(sum(r["requested_out"] for r in rs)), "feasible_out": round(sum(r["feasible_out"] for r in rs)),
                        "need_in": round(sum(r["need_in"] for r in rs)), "short_linked": round(sum(r["short_linked"] for r in rs)),
                        "short_final": round(sum(r["short_final"] for r in rs)), "n_short": len([r for r in rs if r["status"] != "ok"])})
    return {"horizon_days": H, "rounds": rounds, "entities": sorted(rows, key=lambda r: (TIERS.index(r["kind"]), r["id"])),
            "tiers": by_tier, "gaps": sorted(gaps, key=lambda g: -g["short_linked"]),
            "ok": not any(r["short_final"] > EPS for r in rows), "converged": rounds[-1]["spilled_kg"] <= EPS}
