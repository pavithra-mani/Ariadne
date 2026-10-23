"""Pydantic schemas every agent output must satisfy (machine-validated, per design doc 2.4)."""
from pydantic import BaseModel, Field


class Advisory(BaseModel):
    """Health / operational impact branch output."""
    headline: str
    diagnosis: str
    mitigation_steps: list[str] = Field(default_factory=list)
    escalate: bool = False
    escalation_reason: str = ""
    citations: list[int] = Field(default_factory=list)
    follow_up: list[str] = Field(default_factory=list)
    ungrounded_steps: list[int] = Field(default_factory=list)  # filled by the guard, not by the model


class AnswerOut(BaseModel):
    """Plain knowledge answer (no incident)."""
    answer: str
    key_points: list[str] = Field(default_factory=list)
    citations: list[int] = Field(default_factory=list)
    abstained: bool = False


class RecoverySummary(BaseModel):
    headline: str
    explanation: str
    next_steps: list[str] = Field(default_factory=list)


class FindingOut(BaseModel):
    label: str | None = None
    confidence: float = Field(ge=0, le=1)
    source: str
    uncertain: bool = False


class RiskOut(BaseModel):
    severity: str | None = None
    urgency: str | None = None
    priority: str | None = None
    rationale: list[str] = Field(default_factory=list)


class JudgeOut(BaseModel):
    completeness: float = Field(ge=0, le=1)
    relevance: float = Field(ge=0, le=1)


class TriageOut(BaseModel):
    """LLM triage of a free-text report: what is it, and which numbers did the user actually state?"""
    intent: str                      # question | disease_report | low_stock | supply_problem | demand_request | unclear
    incident_type: str | None = None  # reeler: low_yarn_output|cocoon_shortage|delivery_delay ; spinner: demand_surge
    product: str | None = None        # leaves | cocoon | yarn | thread
    affected_pct: float | None = None
    reduction_pct: float | None = None
    duration_days: float | None = None
    delay_days: float | None = None
    quantity_kg: float | None = None
    target_qty: float | None = None
    horizon_days: float | None = None
    stock_now_kg: float | None = None  # stock the user says they hold right now
    confidence: float = 0.5
    clarification: str | None = None


class StrategyChoice(BaseModel):
    case: int
    strategy: str                    # cheapest | nearest | fewest_sources | balanced
    reason: str


class StrategyOut(BaseModel):
    choices: list[StrategyChoice] = Field(default_factory=list)


class GradeOut(BaseModel):
    relevant: list[int] = Field(default_factory=list)   # indexes of passages that help answer the query
    answerable: bool = False
    rewrite: str | None = None                          # a better search query if not answerable


class DiagnosisOut(BaseModel):
    label: str                       # one of the allowed disease labels, or "unknown"
    confidence: float = 0.0
    rationale: str = ""
