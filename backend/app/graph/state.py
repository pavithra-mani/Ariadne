import operator
from typing import Annotated, Any, TypedDict


class State(TypedDict, total=False):
    # intake
    incident_id: int
    role: str
    entity_id: int
    user_id: int
    message: str
    image_path: str | None
    crop: str | None
    fields: dict[str, Any]
    # supervisor
    route: str            # mulberry | silkworm | reeler | spinner | advisor
    mode: str             # incident | query
    incident_kind: str
    memory: dict
    # specialists / assessment
    finding: dict
    assessment: dict      # severity_level, urgency_level, rationale (inputs to the matrix)
    rag: dict
    rag_query: str
    risk: dict
    supply_impact: dict
    health_impact: dict
    advisory: dict
    # recovery pipeline
    cases: list[dict]
    search_count: int
    plans: list[dict]
    deal_ids: list[int]
    decisions: dict
    outcome: dict
    status: str
    trace: Annotated[list, operator.add]
