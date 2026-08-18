"""The shapes everything agrees on. Agent output is validated against these."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class LossType(str, Enum):
    MOTOR_COLLISION = "motor_collision"
    MOTOR_THEFT = "motor_theft"
    HOME_FIRE = "home_fire"
    HOME_STORM = "home_storm"
    HOME_BURGLARY = "home_burglary"
    WATER_DAMAGE = "water_damage"
    OTHER = "other"


class Queue(str, Enum):
    FAST_TRACK = "FAST_TRACK"   # low value, clearly covered, low risk
    STANDARD = "STANDARD"       # normal assessor handling
    INVESTIGATE = "INVESTIGATE" # needs more info / borderline coverage
    SIU = "SIU"                 # Special Investigations Unit — fraud suspected


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Claim(BaseModel):
    """A First Notice of Loss."""

    claim_id: str
    policy_id: str
    loss_type: LossType
    description: str
    estimated_amount: float = Field(ge=0)
    incident_date: str
    reported_date: str
    claimant_statement: str = ""


class FraudSignal(BaseModel):
    name: str
    triggered: bool
    detail: str = ""


class CoverageFinding(BaseModel):
    covered: bool
    clause_id: str | None = None
    clause_text: str | None = None
    reason: str


class TriageDecision(BaseModel):
    """What the agent ultimately produces."""

    claim_id: str
    severity: Severity
    coverage: CoverageFinding
    fraud_signals: list[FraudSignal] = Field(default_factory=list)
    fraud_risk: Literal["LOW", "MEDIUM", "HIGH"]
    recommended_queue: Queue
    rationale: str
    # Filled in by the harness, not the model:
    latency_ms: float | None = None
    cost_usd: float | None = None
    tool_calls: int | None = None


class LabeledClaim(BaseModel):
    """A claim with its gold labels."""

    claim: Claim
    gold_queue: Queue
    gold_severity: Severity
    gold_covered: bool
