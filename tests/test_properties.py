"""Metamorphic & property-based tests.

These assert relationships that must hold for ANY claim under input transformations, so
they need no gold labels and catch whole classes of regressions.
"""

from __future__ import annotations

import pytest

from triageiq.agent import triage
from triageiq.config import Config
from triageiq.llm import MockClient
from triageiq.schemas import Claim, Queue, Severity

# Force mock so these are deterministic and cost nothing regardless of the caller's environment.
_CFG = Config(api_key=None, model="claude-sonnet-5", mode="mock")

SEV_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
FRAUD_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def run(**over):
    base = dict(
        claim_id="P1", policy_id="MOT-100234", loss_type="motor_collision",
        description="Collision damage to the vehicle.", estimated_amount=5600,
        incident_date="2026-08-01", reported_date="2026-08-02", claimant_statement="",
    )
    base.update(over)
    return triage(Claim(**base), MockClient(_CFG), model=_CFG.model)


# ---------------------------------------------------------------- monotonicity (metamorphic)
def test_severity_is_monotonic_in_amount():
    """PROPERTY: raising the estimated amount never lowers the severity band."""
    prev = -1
    for amount in [1850, 9900, 32400]:  # LOW -> MEDIUM -> HIGH boundaries
        band = SEV_RANK[run(estimated_amount=amount).severity.value]
        assert band >= prev, "severity dropped when amount increased"
        prev = band


def test_late_reporting_never_lowers_fraud_risk():
    """PROPERTY: reporting later (crossing the 30-day threshold) can only raise fraud risk."""
    on_time = FRAUD_RANK[run(reported_date="2026-08-02").fraud_risk]
    late = FRAUD_RANK[run(reported_date="2026-09-15").fraud_risk]  # 45-day lag
    assert late >= on_time


def test_round_amount_never_lowers_fraud_risk():
    """PROPERTY: a round-number estimate is a fraud signal, so it can only raise risk."""
    non_round = FRAUD_RANK[run(estimated_amount=5600).fraud_risk]
    rounded = FRAUD_RANK[run(estimated_amount=5000).fraud_risk]  # same LOW severity band
    assert rounded >= non_round


def test_missing_evidence_never_lowers_fraud_risk():
    """PROPERTY: adding 'no forced entry' to a theft can only raise risk."""
    clean = FRAUD_RANK[run(loss_type="motor_theft",
                           description="Vehicle stolen, reported to police.").fraud_risk]
    suspicious = FRAUD_RANK[run(loss_type="motor_theft",
                                description="Vehicle stolen. No forced entry found.").fraud_risk]
    assert suspicious >= clean


# ---------------------------------------------------------------- entry-evidence wording
def _entry_signal(description):
    d = run(policy_id="HOM-205678", loss_type="home_burglary", description=description)
    return next(s for s in d.fraud_signals if s.name == "no_forced_entry_evidence")


@pytest.mark.parametrize("description", [
    "Door lock was broken.",
    "Door lock was broken, no witnesses around.",   # witnesses are irrelevant to this signal
    "Window was smashed and items taken.",
    "They forced the back door open.",
    "Kicked in the front door.",
    "Broke in through the garage.",
    "Glass broken at the rear.",
])
def test_described_forced_entry_is_not_flagged(description):
    """REGRESSION: claimants describe what they saw ('the lock was broken'), never the
    absence of forced entry. Positive evidence must not be read as its opposite."""
    assert _entry_signal(description).triggered is False


@pytest.mark.parametrize("description", [
    "No forced entry found.",
    "Items gone but no sign of a break-in.",
    "Nothing was forced, no damage to the lock.",
    "No signs of forced entry anywhere.",
])
def test_absent_forced_entry_is_flagged(description):
    """An explicit statement that entry showed no force is the genuine anomaly."""
    assert _entry_signal(description).triggered is True


@pytest.mark.parametrize("description", [
    "Contents stolen overnight.",
    "TV and laptop gone when I got home.",
])
def test_unstated_entry_is_not_flagged(description):
    """Silence is not evidence of fraud — flag nothing, but say the detail is missing."""
    signal = _entry_signal(description)
    assert signal.triggered is False
    assert "not described" in signal.detail


def test_absence_of_witnesses_alone_is_not_a_signal():
    """Most burglaries have no witnesses, so that fact alone carries no fraud information."""
    assert _entry_signal("Contents stolen, no witnesses.").triggered is False


# ---------------------------------------------------------------- invariants (property)
def test_high_fraud_always_routes_to_siu_even_when_covered():
    """INVARIANT: HIGH fraud -> SIU, regardless of coverage."""
    d = run(estimated_amount=5000, reported_date="2026-09-15")  # round + late = 2 signals
    assert d.fraud_risk == "HIGH"
    assert d.recommended_queue == Queue.SIU


def test_high_fraud_overrides_lack_of_coverage():
    """INVARIANT: fraud escalation beats coverage — a not-covered claim can still be SIU."""
    d = run(policy_id="MOT-100999", estimated_amount=5000, reported_date="2026-09-15")
    assert d.coverage.covered is False
    assert d.recommended_queue == Queue.SIU


def test_lapsed_policy_is_never_covered_or_fast_tracked():
    """INVARIANT: a lapsed policy cannot be covered and must never be fast-tracked."""
    d = run(policy_id="MOT-100999")
    assert d.coverage.covered is False
    assert d.recommended_queue != Queue.FAST_TRACK


def test_building_only_policy_never_covers_contents_theft():
    """INVARIANT: a building-only policy cannot cover a burglary (contents) claim."""
    d = run(policy_id="HOM-205679", loss_type="home_burglary",
            description="Contents stolen in a break-in.")
    assert d.coverage.covered is False


def test_covered_decision_always_cites_a_clause():
    """INVARIANT (grounding): if it says 'covered', it must cite the supporting clause."""
    for policy, loss in [("MOT-100234", "motor_collision"),
                         ("HOM-205678", "home_fire"),
                         ("HOM-205678", "water_damage")]:
        d = run(policy_id=policy, loss_type=loss, description="loss occurred")
        if d.coverage.covered:
            assert d.coverage.clause_id, f"{policy}/{loss}: covered but no clause cited"


def test_output_enums_always_valid():
    """INVARIANT: routing/severity/fraud are always drawn from the allowed sets."""
    d = run()
    assert d.recommended_queue in set(Queue)
    assert d.severity in set(Severity)
    assert d.fraud_risk in {"LOW", "MEDIUM", "HIGH"}


# ---------------------------------------------------------------- stability (metamorphic)
def test_paraphrasing_description_does_not_change_routing():
    """PROPERTY: rewording the description (same facts) must not change the queue."""
    a = run(loss_type="home_storm", policy_id="HOM-205678", estimated_amount=6500,
            description="Storm damaged the roof.")
    b = run(loss_type="home_storm", policy_id="HOM-205678", estimated_amount=6500,
            description="The roof was damaged during a storm.")
    assert a.recommended_queue == b.recommended_queue


def test_triage_is_idempotent():
    """PROPERTY: same claim in, same decision out (ignoring wall-clock latency)."""
    a = run().model_dump(exclude={"latency_ms", "cost_usd"})
    b = run().model_dump(exclude={"latency_ms", "cost_usd"})
    assert a == b


@pytest.mark.parametrize("amount", [1850, 5000, 8500, 15000, 32400])
def test_severity_bands_are_consistent_with_thresholds(amount):
    """PROPERTY: severity band matches the documented dollar thresholds (non-escalating loss)."""
    band = run(estimated_amount=amount).severity.value
    expected = "HIGH" if amount >= 30000 else "MEDIUM" if amount >= 8000 else "LOW"
    assert band == expected
