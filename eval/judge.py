"""Quality checks that go past label accuracy.

grounding_check is the hallucination guard — does the cited clause actually back the
coverage call? rationale_score is an LLM judge, with a heuristic fallback in mock mode.
"""

from __future__ import annotations

import json

from triageiq import knowledge
from triageiq.config import DATA_DIR
from triageiq.schemas import Claim, TriageDecision

_POLICIES = {p["policy_id"]: p for p in json.loads((DATA_DIR / "policies.json").read_text("utf-8"))}


def grounding_check(claim: Claim, decision: TriageDecision) -> dict:
    """Grounded means the cited clause actually supports the coverage call."""
    cov = decision.coverage
    policy = _POLICIES.get(claim.policy_id)

    if cov.clause_id is None:
        # Only OK when no covering clause exists (lapsed, unknown policy).
        det = knowledge.determine_coverage(claim.policy_id, claim.loss_type.value)
        if det["covered"]:
            return {"grounded": False, "issue": "No clause cited though coverage exists"}
        return {"grounded": not cov.covered, "issue": "" if not cov.covered else "Claimed covered with no clause"}

    if not policy:
        return {"grounded": False, "issue": f"Cited clause {cov.clause_id} but policy unknown"}

    clause = next((c for c in policy["clauses"] if c["id"] == cov.clause_id), None)
    if clause is None:
        return {"grounded": False, "issue": f"Cited non-existent clause {cov.clause_id}"}

    if cov.covered and claim.loss_type.value not in clause.get("covers", []):
        return {"grounded": False,
                "issue": f"Clause {cov.clause_id} does not cover {claim.loss_type.value}"}
    return {"grounded": True, "issue": ""}


_JUDGE_PROMPT = """Rate this insurance triage rationale from 1 (poor) to 5 (excellent) on whether
it is clear, internally consistent, and justified by the stated coverage/severity/fraud findings.
Reply with only a single integer 1-5.

Decision:
{decision}
"""


def rationale_score(decision: TriageDecision, client, model: str, is_mock: bool) -> int:
    if is_mock:
        # Heuristic so mock runs still finish.
        score = 3
        if decision.coverage.clause_id:
            score += 1
        if len(decision.rationale) > 40:
            score += 1
        return min(score, 5)

    resp = client.complete(
        system="You are a strict evaluator. Output only an integer 1-5.",
        messages=[{"role": "user", "content": _JUDGE_PROMPT.format(
            decision=decision.model_dump_json(indent=2))}],
        tools=[],
    )
    for token in resp.text.split():
        if token.strip().isdigit():
            return max(1, min(5, int(token.strip())))
    return 3
