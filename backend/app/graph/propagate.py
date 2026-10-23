"""Downstream propagation: a supplier-side problem opens an incident for every affected buyer.

For each buyer whose stock would fall below its reorder point, Ariadne starts a buyer-owned incident
that (1) alerts the buyer, (2) searches alternative sources within a bounded number of searches and
routes them, (3) proposes deals, and (4) waits for the buyer to approve or reject. The chain continues:
if a buyer cannot be fully restocked, its own buyers are assessed in turn.
"""
from app.calc.impact import INPUT_PRODUCT, OUTPUT_PRODUCT, buyers, exposure_for_buyer, get_inv
from app.db.models import Entity, Incident
from app.db.session import session_scope
from app.graph.common import save_incident, traced
from app.graph.profiles import COCOON_PER_YARN, LEAF_PER_KG_COCOON
from app.graph.runner import start_incident

MAX_DEPTH = 4
KIND_LABEL = {"mulberry_farm": "mulberry farm", "silkworm_farm": "silkworm farm", "reeler": "reeling unit", "spinner": "twisting mill"}
EVENT_LABEL = {"low_yarn_output": "low yarn output", "cocoon_shortage": "a cocoon supply shortage", "delivery_delay": "a delivery delay"}
CONVERT = {"leaves": ("cocoon", LEAF_PER_KG_COCOON), "cocoon": ("yarn", COCOON_PER_YARN)}  # input kg per output kg


def _depth(db, incident_id: int | None) -> int:
    d = 0
    while incident_id and d <= MAX_DEPTH:
        inc = db.get(Incident, incident_id)
        incident_id, d = (inc.parent_id if inc else None), d + 1
    return d


def has_open_incident(db, entity_id: int, product: str) -> int | None:
    rows = db.query(Incident).filter(Incident.entity_id == entity_id, Incident.kind == "low_stock",
                                     Incident.status.in_(["awaiting_approval", "open", "resuming"]))
    for i in rows:
        p = i.payload or {}
        if (p.get("finding") or {}).get("product") == product or (p.get("input_fields") or {}).get("product") == product:
            return i.id
    return None


def buyers_needing_help(db, supplier: Entity, product: str, lost_qty: float) -> list[dict]:
    """Rows (same shape as impact['affected']) for buyers that cannot absorb `lost_qty` of the supplier's output."""
    rows = []
    for b, share in buyers(db, supplier.id):
        exposure = lost_qty * share
        ex = exposure_for_buyer(db, b, product, exposure)
        rows.append({"entity_id": b.id, "name": b.name, "kind": b.kind, "product": product, "lost_exposure": round(exposure, 1),
                     "shortfall": ex["shortfall"], "at_risk": ex["shortfall"] > 0})
    return rows


def spawn(rows: list[dict], supplier_id: int, supplier_name: str, supplier_kind: str, product: str,
          cause_incident_id: int | None, event: str) -> list[dict]:
    """Start one incident per at-risk buyer (skipping buyers already being handled)."""
    children = []
    with session_scope() as db:
        if _depth(db, cause_incident_id) >= MAX_DEPTH:
            return []
    for r in rows:
        if not r["at_risk"] or r["lost_exposure"] <= 0:
            continue
        with session_scope() as db:
            if has_open_incident(db, r["entity_id"], product):
                continue
        text = f"Upstream: {supplier_name} ({KIND_LABEL[supplier_kind]}) reported {event}."
        fields = {"incident_type": "low_stock", "product": product, "lost_exposure": r["lost_exposure"],
                  "cause_entity": supplier_id, "cause_incident": cause_incident_id, "cause_text": text}
        cid = start_incident(r["kind"], r["entity_id"], None, text, fields, parent_id=cause_incident_id)
        children.append({"incident_id": cid, "entity_id": r["entity_id"], "product": product, "qty": r["lost_exposure"]})
    return children


def stock_drop_children(entity_id: int, product: str, drop: float) -> list[dict]:
    """A supplier's sellable stock fell by `drop` kg: assess its buyers."""
    with session_scope() as db:
        sup = db.get(Entity, entity_id)
        rows = buyers_needing_help(db, sup, product, drop)
        name, kind = sup.name, sup.kind
    return spawn(rows, entity_id, name, kind, product, None, f"a {drop:.0f} kg drop in its {product} stock")


@traced("propagate_downstream", "propagate")
def propagate_early(state):
    """Right after the incident is assessed: open incidents for buyers that the loss pushes below reorder."""
    f, imp = state.get("finding") or {}, state.get("supply_impact") or {}
    route = state.get("route")
    if state.get("mode") != "incident" or f.get("uncertain") or f.get("incident_type") in ("demand_surge", "input_shortage") \
            or route == "spinner" or not imp.get("affected") or not any(a.get("lost_exposure") for a in imp["affected"]):
        return {"_summary": "no downstream buyers to protect"}
    product = imp["product"]
    event = (f"{f['label'].replace('_', ' ')} on its {f['crop']}" if f.get("crop") else
             f"low {product} stock" if f.get("incident_type") == "low_stock" else EVENT_LABEL.get(f.get("incident_type"), "a supply problem"))
    save_incident(state)  # make the loss visible to the supply outlook before buyers react
    with session_scope() as db:
        me = db.get(Entity, state["entity_id"])
        name, kind = me.name, me.kind
    children = spawn(imp["affected"], state["entity_id"], name, kind, product, state["incident_id"], event)
    out = {**(state.get("outcome") or {}), "children": (state.get("outcome") or {}).get("children", []) + children}
    return {"outcome": out, "_tools": ["graph.start_incident"] if children else [],
            "_summary": f"{len(children)} buyer incident(s) opened" if children else "buyers can absorb the loss"}


@traced("propagate_residual", "propagate")
def propagate_final(state):
    """After recovery: supply this entity still could not secure reduces its own output, so its buyers are assessed next."""
    route = state.get("route")
    if state.get("mode") != "incident" or route not in ("silkworm", "reeler"):
        return {"_summary": "end of chain"}
    unresolved = 0.0
    with session_scope() as db:
        from app.db.models import Deal
        me = db.get(Entity, state["entity_id"])
        own_input = INPUT_PRODUCT.get(me.kind)
        for c in state.get("cases", []):
            if c.get("buyer_id") != me.id or c["product"] != own_input or c["direction"] != "upstream":
                continue
            done = sum(d.quantity for d in db.query(Deal).filter(Deal.id.in_(c.get("deals", [])), Deal.status == "executed")) if c.get("deals") else 0.0
            unresolved += max(c["qty"] - done, 0.0)
        name, kind, thr = me.name, me.kind, me.daily_throughput
    if unresolved <= 0.5 or own_input not in CONVERT:
        return {"_summary": "own supply fully restored"}
    out_product, ratio = CONVERT[own_input]
    lost_out = unresolved / ratio
    frac = round(min(lost_out / max(thr * 7, 1.0), 1.0), 3)
    outcome = {**(state.get("outcome") or {}), "residual_loss_fraction": frac}
    save_incident({**state, "outcome": outcome})
    with session_scope() as db:
        rows = buyers_needing_help(db, db.get(Entity, state["entity_id"]), out_product, lost_out)
    children = spawn(rows, state["entity_id"], name, kind, out_product, state["incident_id"],
                     f"a {unresolved:.0f} kg {own_input} shortfall it could not cover (≈{lost_out:.0f} kg less {out_product})")
    outcome["children"] = outcome.get("children", []) + children
    return {"outcome": outcome, "_tools": ["graph.start_incident"] if children else [],
            "_summary": f"residual {unresolved:.0f} kg {own_input} -> {len(children)} buyer incident(s)"}
