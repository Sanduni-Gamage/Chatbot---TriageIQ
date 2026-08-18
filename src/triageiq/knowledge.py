"""Policy records, plus retrieval over the policy wording.

Retrieval is keyword matching for now — swap retrieve_clauses for a vector store
and nothing above it has to change.
"""

from __future__ import annotations

import json
from functools import lru_cache

from .config import DATA_DIR


@lru_cache(maxsize=1)
def _policies() -> dict[str, dict]:
    raw = json.loads((DATA_DIR / "policies.json").read_text(encoding="utf-8"))
    return {p["policy_id"]: p for p in raw}


def lookup_policy(policy_id: str) -> dict | None:
    """The policy record, or None if we don't have it."""
    p = _policies().get(policy_id)
    if not p:
        return None
    return {
        "policy_id": p["policy_id"],
        "product": p["product"],
        "holder": p["holder"],
        "status": p["status"],
        "excess": p["excess"],
        "num_clauses": len(p["clauses"]),
    }


def retrieve_clauses(policy_id: str, loss_type: str) -> list[dict]:
    """Clauses ranked by relevance to the loss type — the retrieval step."""
    p = _policies().get(policy_id)
    if not p:
        return []
    ranked = []
    for clause in p["clauses"]:
        is_exclusion = clause["id"].split("-")[-1].startswith("X") or "not cover" in clause["text"].lower()
        covers = loss_type in clause.get("covers", [])
        # rank: direct match > exclusion > everything else
        score = 2 if covers else (1 if is_exclusion else 0)
        if score > 0:
            ranked.append({**clause, "_score": score, "_exclusion": is_exclusion})
    ranked.sort(key=lambda c: c["_score"], reverse=True)
    return ranked


def determine_coverage(policy_id: str, loss_type: str) -> dict:
    """Decide coverage, always naming the clause it relied on."""
    policy = _policies().get(policy_id)
    if not policy:
        return {"covered": False, "clause_id": None, "clause_text": None,
                "reason": f"Policy {policy_id} not found."}
    if policy["status"] != "active":
        return {"covered": False, "clause_id": None, "clause_text": None,
                "reason": f"Policy {policy_id} is {policy['status']}; no cover in force."}

    clauses = retrieve_clauses(policy_id, loss_type)
    covering = next((c for c in clauses if not c["_exclusion"] and loss_type in c["covers"]), None)
    if covering:
        return {"covered": True, "clause_id": covering["id"], "clause_text": covering["text"],
                "reason": f"Loss type '{loss_type}' is covered by clause {covering['id']}."}

    exclusion = next((c for c in clauses if c["_exclusion"]), None)
    if exclusion:
        return {"covered": False, "clause_id": exclusion["id"], "clause_text": exclusion["text"],
                "reason": f"No covering clause found; nearest relevant clause is exclusion {exclusion['id']}."}
    return {"covered": False, "clause_id": None, "clause_text": None,
            "reason": f"No clause in policy {policy_id} addresses loss type '{loss_type}'."}
