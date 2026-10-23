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
