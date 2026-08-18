"""Tools the agent can call, plus their JSON schemas."""

from __future__ import annotations

from datetime import date

from . import knowledge
from .rules import RULES
from .schemas import Claim, Severity

# ------------------------------------------------------------------ tool implementations
def assess_severity(claim: Claim) -> dict:
    """Severity band from exposure and loss type, with the reasons why."""
    drivers = []
    amount = claim.estimated_amount
    if amount >= 30_000:
        band, drivers = Severity.HIGH, [f"High exposure (${amount:,.0f})"]
    elif amount >= 8_000:
        band, drivers = Severity.MEDIUM, [f"Moderate exposure (${amount:,.0f})"]
    else:
        band, drivers = Severity.LOW, [f"Low exposure (${amount:,.0f})"]

    if claim.loss_type.value in {"home_fire", "motor_theft"} and band == Severity.LOW:
        band = Severity.MEDIUM
        drivers.append("Loss type escalates minimum severity")

    return {"severity": band.value, "drivers": drivers}


def detect_fraud_signals(claim: Claim) -> dict:
    """Fraud indicators. Thresholds live in data/fraud_rules.json."""
    signals = []

    lag = _days_between(claim.incident_date, claim.reported_date)
    signals.append({
        "name": "late_reporting",
        "triggered": lag is not None and lag > RULES.late_reporting_days,
        "detail": f"Reported {lag} days after incident" if lag is not None else "Unknown dates",
    })

    is_round = (claim.estimated_amount >= RULES.round_amount_minimum
                and claim.estimated_amount % RULES.round_amount_multiple == 0)
    signals.append({
        "name": "round_number_amount",
        "triggered": is_round,
        "detail": f"Estimate is a round ${claim.estimated_amount:,.0f}",
    })

    signals.append(_forced_entry_signal(claim))

    triggered = [s for s in signals if s["triggered"]]
    if len(triggered) >= 2:
        risk = "HIGH"
    elif len(triggered) == 1:
        risk = "MEDIUM"
    else:
        risk = "LOW"

    return {"signals": signals, "fraud_risk": risk, "num_triggered": len(triggered)}


def _forced_entry_signal(claim: Claim) -> dict:
    """Flag theft/burglary claims where forced entry is explicitly absent."""
    if claim.loss_type.value not in RULES.theft_loss_types:
        return {"name": "no_forced_entry_evidence", "triggered": False,
                "detail": "Not a theft or burglary claim"}

    text = f"{claim.description} {claim.claimant_statement}".lower()

    # Negation first — "no forced entry" contains "forced entry".
    if any(p in text for p in RULES.no_forced_entry):
        return {"name": "no_forced_entry_evidence", "triggered": True,
                "detail": "Theft/burglary reported with no sign of forced entry"}

    if any(p in text for p in RULES.forced_entry_evidence):
        return {"name": "no_forced_entry_evidence", "triggered": False,
                "detail": "Forced entry is evidenced in the claim description"}

    return {"name": "no_forced_entry_evidence", "triggered": False,
            "detail": "Entry method not described — worth confirming with the claimant"}


def _days_between(d1: str, d2: str) -> int | None:
    try:
        return (date.fromisoformat(d2) - date.fromisoformat(d1)).days
    except ValueError:
        return None


# ------------------------------------------------------------------ executor
class ToolExecutor:
    def __init__(self, claim: Claim):
        self.claim = claim
        self.calls = 0

    def run(self, name: str, tool_input: dict) -> dict:
        self.calls += 1
        if name == "lookup_policy":
            result = knowledge.lookup_policy(tool_input.get("policy_id", self.claim.policy_id))
            return result or {"error": "policy_not_found"}
        if name == "check_coverage":
            return knowledge.determine_coverage(
                tool_input.get("policy_id", self.claim.policy_id),
                tool_input.get("loss_type", self.claim.loss_type.value),
            )
        if name == "assess_severity":
            return assess_severity(self.claim)
        if name == "detect_fraud_signals":
            return detect_fraud_signals(self.claim)
        return {"error": f"unknown_tool:{name}"}


# ------------------------------------------------------------------ schemas for the LLM
TOOL_SCHEMAS = [
    {
        "name": "lookup_policy",
        "description": "Fetch the policy record (product, status, excess) for a policy id.",
        "input_schema": {
            "type": "object",
            "properties": {"policy_id": {"type": "string"}},
            "required": ["policy_id"],
        },
    },
    {
        "name": "check_coverage",
        "description": "Determine whether a loss type is covered, returning the specific policy "
                       "clause relied upon. Use this before deciding coverage.",
        "input_schema": {
            "type": "object",
            "properties": {
                "policy_id": {"type": "string"},
                "loss_type": {"type": "string"},
            },
            "required": ["policy_id", "loss_type"],
        },
    },
    {
        "name": "assess_severity",
        "description": "Return a severity band (LOW/MEDIUM/HIGH) and drivers for the current claim.",
        "input_schema": {
            "type": "object",
            "properties": {"claim_id": {"type": "string"}},
            "required": ["claim_id"],
        },
    },
    {
        "name": "detect_fraud_signals",
        "description": "Run fraud indicators over the current claim and return a fraud risk band.",
        "input_schema": {
            "type": "object",
            "properties": {"claim_id": {"type": "string"}},
            "required": ["claim_id"],
        },
    },
    {
        "name": "submit_triage",
        "description": "Submit the final triage decision. Call this exactly once, last, after "
                       "gathering coverage, severity and fraud evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "claim_id": {"type": "string"},
                "severity": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
                "coverage": {
                    "type": "object",
                    "properties": {
                        "covered": {"type": "boolean"},
                        "clause_id": {"type": ["string", "null"]},
                        "clause_text": {"type": ["string", "null"]},
                        "reason": {"type": "string"},
                    },
                    "required": ["covered", "reason"],
                },
                "fraud_signals": {"type": "array", "items": {"type": "object"}},
                "fraud_risk": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
                "recommended_queue": {
                    "type": "string",
                    "enum": ["FAST_TRACK", "STANDARD", "INVESTIGATE", "SIU"],
                },
                "rationale": {"type": "string"},
            },
            "required": ["claim_id", "severity", "coverage", "fraud_risk",
                         "recommended_queue", "rationale"],
        },
    },
]
