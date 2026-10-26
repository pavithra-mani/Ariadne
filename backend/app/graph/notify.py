"""Early-warning notifications: the moment an incident is assessed, every directly affected
partner is told, whatever the tier (mulberry -> silkworm farmers, silkworm -> reelers,
reeler -> spinners, spinner -> its reelers). Sent before any recovery or approval."""
from app.db.models import Entity, Notification
from app.db.session import session_scope
from app.graph.common import traced

KIND_LABEL = {"mulberry_farm": "mulberry farm", "silkworm_farm": "silkworm farm", "reeler": "reeling unit",
              "spinner": "twisting mill"}
INCIDENT_LABEL = {"low_yarn_output": "low yarn output", "cocoon_shortage": "a cocoon supply shortage",
                  "delivery_delay": "a delivery delay", "demand_surge": "a demand surge"}


def _kg(x) -> str:
    return f"{float(x):,.0f} kg"


@traced("notify_affected", "notify")
def notify_affected(state):
    f, imp, risk = state.get("finding") or {}, state.get("supply_impact") or {}, state.get("risk") or {}
    if state.get("mode") != "incident" or f.get("uncertain") or f.get("healthy") or not imp.get("affected"):
        return {"_summary": "no downstream partners to alert"}
    route, sent = state["route"], 0
    pr = f"{risk.get('priority')} ({risk.get('severity')} severity, {risk.get('urgency')} urgency)"
    with session_scope() as db:
        src = db.get(Entity, state["entity_id"])
        who = f"{src.name} ({KIND_LABEL[src.kind]}, {src.village})"
        for a in imp["affected"]:
            if f.get("incident_type") == "low_stock":
                st = imp["stock"]
                head = f"Upstream alert: {who} is running low on {imp['product']} ({st['status']}, {st['days_of_cover']:.1f} days of cover), priority {pr}."
                body = (f" Over the next {imp['horizon_days']} days you need about {_kg(a['need'])} from it and can expect {_kg(a['allocated'])}. ")
                body += (f"Shortfall {_kg(a['shortfall'])} after your own stock - Ariadne is sourcing alternatives."
                         if a["at_risk"] else "Your own stock covers the gap - monitor.")
                level = "alert" if a["at_risk"] else "warning"
            elif route in ("mulberry", "silkworm"):
                what = ("a suspected infectious disease on its silkworms (not yet identified; unconfirmed - an expert check is pending)"
                        if f.get("provisional") else f"{f['label'].replace('_', ' ')} on its {f['crop']}")
                head = f"Upstream alert: {who} reported {what}, priority {pr}."
                body = (f" Expected loss ≈ {_kg(imp['lost_qty'])} of {imp['product']} over {imp['horizon_days']} days; "
                        f"your exposure ≈ {_kg(a['exposure_qty'])}. ")
                body += (f"Your {a['cover_days']:.1f} days of cover cannot absorb it: shortfall {_kg(a['shortfall'])} - Ariadne is searching alternatives."
                         if a["at_risk"] else f"Your stock ({a['cover_days']:.1f} days of cover) can absorb it for now - monitor.")
                level = "alert" if a["at_risk"] else "warning"
            elif route == "reeler":
                head = f"Upstream alert: {who} reported {INCIDENT_LABEL[f['incident_type']]}, priority {pr}."
                body = (f" Over {imp['horizon_days']:.0f} days you need {_kg(a['need'])} from it and can expect {_kg(a['allocated'])}. ")
                body += (f"Shortfall {_kg(a['shortfall'])} after your own stock - Ariadne is sourcing alternatives."
                         if a["at_risk"] else "Your own stock covers the gap - monitor.")
                level = "alert" if a["at_risk"] else "warning"
            else:  # spinner request -> the reelers it wants to buy from
                head = f"Incoming request: {who} needs {_kg(imp['target'])} of yarn within {imp['horizon_days']} days (priority {pr})."
                body = f" Based on your sellable stock and spare capacity you could supply up to {_kg(a['can_supply'])}."
                level = "info"
            db.add(Notification(entity_id=a["entity_id"], incident_id=state["incident_id"], level=level,
                                message=head + body))
            sent += 1
    return {"_summary": f"{sent} affected partner(s) notified"}
