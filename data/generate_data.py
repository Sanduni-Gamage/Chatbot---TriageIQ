"""Generate a labeled claims dataset for evaluation (100 varied claims).

Design: a procedural generator with an independent *oracle*.

* The generator enumerates realistic claims across policies, loss types, dollar bands, reporting
  lags and evidence variants.
* The oracle assigns gold labels (queue / severity / covered) by re-stating the business rules
  and reading coverage straight from ``policies.json``. It deliberately does NOT import the
  system under test (``src/triageiq``), so gold labels are an independent ground truth: if the
  system's logic ever drifts from the rules, the eval will surface the disagreement instead of
  hiding it.

The set is balanced (~25 per routing queue) and deterministic (no randomness), so results are
reproducible. It spans all four queues, all severity bands, covered/not-covered outcomes
(lapsed policy, building-only exclusions, wrong loss type, unlisted peril) and every combination
of the three fraud signals — including not-covered claims escalated to SIU on fraud risk.

Run:  python data/generate_data.py   ->   writes data/claims.jsonl
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "claims.jsonl"
POLICIES_PATH = HERE / "policies.json"
RULES_PATH = HERE / "fraud_rules.json"

PER_QUEUE = 25  # -> 100 claims total

# --------------------------------------------------------------------------- independent oracle
# The oracle reads the same reference DATA as the system (policy wording, fraud thresholds and
# phrase lists) but implements the decision LOGIC independently. Sharing tuned parameters keeps
# the two from drifting on vocabulary, while the separate implementation still catches a genuine
# logic regression in src/triageiq.
_POLICIES = {p["policy_id"]: p for p in json.loads(POLICIES_PATH.read_text("utf-8"))}
_RULES = json.loads(RULES_PATH.read_text("utf-8"))

THEFT_FAMILY = set(_RULES["theft_loss_types"])
SEVERITY_ESCALATORS = {"home_fire", "motor_theft"}
_FORCED_ENTRY_EVIDENCE = tuple(_RULES["forced_entry_evidence"])
_NO_FORCED_ENTRY = tuple(_RULES["no_forced_entry"])
_LATE_DAYS = _RULES["late_reporting_days"]
_ROUND_MIN = _RULES["round_amount_minimum"]
_ROUND_MULT = _RULES["round_amount_multiple"]


def _covered(policy_id: str, loss_type: str) -> bool:
    p = _POLICIES.get(policy_id)
    if not p or p["status"] != "active":
        return False
    covered_types = {lt for clause in p["clauses"] for lt in clause.get("covers", [])}
    return loss_type in covered_types


def _severity(loss_type: str, amount: float) -> str:
    if amount >= 30_000:
        band = "HIGH"
    elif amount >= 8_000:
        band = "MEDIUM"
    else:
        band = "LOW"
    if band == "LOW" and loss_type in SEVERITY_ESCALATORS:
        band = "MEDIUM"
    return band


def _fraud_risk(loss_type: str, amount: float, inc: str, rep: str, text: str) -> str:
    signals = 0
    lag = (date.fromisoformat(rep) - date.fromisoformat(inc)).days
    if lag > _LATE_DAYS:
        signals += 1
    if amount >= _ROUND_MIN and amount % _ROUND_MULT == 0:
        signals += 1
    # Negation is tested first: "no forced entry" contains "forced entry" as a substring.
    low = text.lower()
    if loss_type in THEFT_FAMILY and any(p in low for p in _NO_FORCED_ENTRY):
        signals += 1
    return "HIGH" if signals >= 2 else "MEDIUM" if signals == 1 else "LOW"


def _route(covered: bool, severity: str, fraud: str) -> str:
    if fraud == "HIGH":
        return "SIU"
    if not covered:
        return "INVESTIGATE"
    if severity == "LOW" and fraud == "LOW":
        return "FAST_TRACK"
    return "STANDARD"


# --------------------------------------------------------------------------- generation inputs
PAIRS = [
    ("MOT-100234", "motor_collision"), ("MOT-100234", "motor_theft"),
    ("HOM-205678", "home_fire"), ("HOM-205678", "home_storm"),
    ("HOM-205678", "water_damage"), ("HOM-205678", "home_burglary"),
    ("HOM-205678", "other"),
    ("HOM-205679", "home_fire"), ("HOM-205679", "home_storm"),
    ("HOM-205679", "home_burglary"), ("HOM-205679", "water_damage"),
    ("HOM-205679", "other"),
    ("MOT-100999", "motor_collision"), ("MOT-100999", "motor_theft"),
]

AMOUNTS = [
    1200, 1850, 2000, 2750, 3000, 3400, 4200, 5000, 5600, 6500, 7000, 7100,   # low
    8000, 8500, 9900, 10000, 11500, 12000, 13400, 15000, 17600, 18000,        # medium
    20000, 22300, 25000, 26700, 28000, 29900,                                 # medium
    30000, 32400, 40000, 41200, 50000, 55600, 80000,                          # high
]

# (incident, reported) pairs — first four on-time (<=30d), last four late (>30d).
LAGS = [
    ("2026-08-01", "2026-08-02"), ("2026-07-20", "2026-07-22"),
    ("2026-08-10", "2026-08-12"), ("2026-07-15", "2026-07-16"),
    ("2026-06-01", "2026-08-01"), ("2026-06-15", "2026-08-05"),
    ("2026-05-20", "2026-07-15"), ("2026-06-20", "2026-08-10"),
]

DESC = {
    "motor_collision": ["Collision damage to the vehicle.", "Vehicle damaged in a collision at an intersection.",
                        "Rear-end collision with panel damage.", "Front-end collision damage."],
    "motor_theft": ["Vehicle stolen.", "Car stolen from the street.",
                    "Motorbike stolen overnight.", "Vehicle taken from the driveway."],
    "home_fire": ["House fire with structural damage.", "Kitchen fire that spread through the home.",
                  "Electrical fire damaged the property.", "Fire caused extensive smoke damage."],
    "home_storm": ["Storm damaged the roof.", "Storm blew down fencing and guttering.",
                   "Wind damage to the building exterior.", "Storm tore roofing from the house."],
    "home_burglary": ["Contents stolen in a break-in.", "Burglary with electronics taken.",
                      "Break-in, several items stolen.", "Jewellery stolen from the home."],
    "water_damage": ["Water damage from flooding.", "Rainwater entered the property.",
                     "Flood damage to the ground floor.", "Storm flooding damaged contents."],
    "other": ["Accidental damage to personal property.", "Damage attributed to ground movement.",
              "Accidental damage claim."],
}
STMT = [
    "The insured has provided an initial account of the loss.",
    "Details were captured at first notice of loss.",
    "The claimant described the circumstances when lodging the claim.",
    "Supporting information was noted at intake.",
]


def _text(loss_type: str, evidence: bool, idx: int) -> tuple[str, str]:
    pool = DESC[loss_type]
    desc = pool[idx % len(pool)]
    if loss_type in THEFT_FAMILY:
        desc += " No sign of forced entry and no witnesses." if evidence \
            else " Forced entry was evident and it was reported to police."
    stmt = STMT[idx % len(STMT)]
    return desc, stmt


# --------------------------------------------------------------------------- build & balance
def _candidates() -> list[dict]:
    """Enumerate deterministic candidates, ordered so pair varies fastest (maximises variety
    within each queue bucket after even-spaced sampling)."""
    seen = set()
    out = []
    counter = 0
    for amount in AMOUNTS:
        for lag in LAGS:
            for policy_id, loss_type in PAIRS:
                evidences = [False, True] if loss_type in THEFT_FAMILY else [False]
                for evidence in evidences:
                    inc, rep = lag
                    desc, stmt = _text(loss_type, evidence, counter)
                    counter += 1
                    text = desc + " " + stmt
                    covered = _covered(policy_id, loss_type)
                    severity = _severity(loss_type, amount)
                    fraud = _fraud_risk(loss_type, amount, inc, rep, text)
                    queue = _route(covered, severity, fraud)
                    key = (policy_id, loss_type, amount, inc, rep, evidence)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({
                        "policy_id": policy_id, "loss_type": loss_type, "description": desc,
                        "estimated_amount": float(amount), "incident_date": inc,
                        "reported_date": rep, "claimant_statement": stmt,
                        "gold_queue": queue, "gold_severity": severity, "gold_covered": covered,
                    })
    return out


def _balanced(candidates: list[dict]) -> list[dict]:
    by_queue: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        by_queue[c["gold_queue"]].append(c)

    chosen: list[dict] = []
    for queue in ["FAST_TRACK", "STANDARD", "INVESTIGATE", "SIU"]:
        group = by_queue[queue]
        if len(group) <= PER_QUEUE:
            picks = group
        else:
            step = len(group) / PER_QUEUE          # even spread across the group
            picks = [group[int(i * step)] for i in range(PER_QUEUE)]
        chosen.extend(picks)

    for i, c in enumerate(chosen, start=1):        # stable, readable ids
        c["claim_id"] = f"CLM-{i:03d}"
    return chosen


def main() -> None:
    chosen = _balanced(_candidates())
    with OUT.open("w", encoding="utf-8") as f:
        for c in chosen:
            record = {
                "claim": {k: c[k] for k in ("claim_id", "policy_id", "loss_type", "description",
                                            "estimated_amount", "incident_date", "reported_date",
                                            "claimant_statement")},
                "gold_queue": c["gold_queue"],
                "gold_severity": c["gold_severity"],
                "gold_covered": c["gold_covered"],
            }
            f.write(json.dumps(record) + "\n")

    dist = Counter(c["gold_queue"] for c in chosen)
    sev = Counter(c["gold_severity"] for c in chosen)
    cov = Counter("covered" if c["gold_covered"] else "not_covered" for c in chosen)
    print(f"Wrote {len(chosen)} labeled claims to {OUT}")
    print("Queue:   ", dict(dist))
    print("Severity:", dict(sev))
    print("Coverage:", dict(cov))


if __name__ == "__main__":
    main()
