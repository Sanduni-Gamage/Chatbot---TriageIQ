"""Unit + integration tests. Run: pytest -q"""

from __future__ import annotations

from triageiq.agent import triage
from triageiq.config import load_config
from triageiq.knowledge import determine_coverage, lookup_policy
from triageiq.llm import build_client
from triageiq.schemas import Claim
from triageiq.tools import assess_severity, detect_fraud_signals


def _claim(**over):
    base = dict(
        claim_id="T1", policy_id="MOT-100234", loss_type="motor_collision",
        description="minor bump", estimated_amount=1500,
        incident_date="2026-07-01", reported_date="2026-07-02", claimant_statement="",
    )
    base.update(over)
    return Claim(**base)


# ---- knowledge ----
def test_lookup_known_policy():
    assert lookup_policy("MOT-100234")["status"] == "active"


def test_lookup_unknown_policy():
    assert lookup_policy("NOPE") is None


def test_coverage_grounded_to_clause():
    r = determine_coverage("MOT-100234", "motor_collision")
    assert r["covered"] and r["clause_id"] == "MOT-C1"


def test_lapsed_policy_not_covered():
    r = determine_coverage("MOT-100999", "motor_collision")
    assert r["covered"] is False and "lapsed" in r["reason"]


def test_building_only_excludes_contents():
    r = determine_coverage("HOM-205679", "home_burglary")
    assert r["covered"] is False


# ---- tools ----
def test_severity_bands():
    assert assess_severity(_claim(estimated_amount=500))["severity"] == "LOW"
    assert assess_severity(_claim(estimated_amount=50000))["severity"] == "HIGH"


def test_fraud_two_signals_is_high():
    c = _claim(loss_type="home_burglary", policy_id="HOM-205678",
               estimated_amount=12000, incident_date="2026-05-01",
               reported_date="2026-07-01",
               description="no forced entry", claimant_statement="no sign of break-in")
    assert detect_fraud_signals(c)["fraud_risk"] == "HIGH"


# ---- agent (mock) ----
def test_agent_produces_valid_decision():
    cfg = load_config()  # mock unless a key is set
    decision = triage(_claim(), build_client(cfg), model=cfg.model)
    assert decision.claim_id == "T1"
    assert decision.recommended_queue.value in {"FAST_TRACK", "STANDARD", "INVESTIGATE", "SIU"}
    assert decision.tool_calls and decision.tool_calls >= 4


def test_agent_routes_clean_low_value_to_fast_track():
    cfg = load_config()
    decision = triage(_claim(), build_client(cfg), model=cfg.model)
    assert decision.recommended_queue.value == "FAST_TRACK"
