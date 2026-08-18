"""Loads the tunable fraud rules from data/fraud_rules.json.

Thresholds and phrase lists live in data so they can change without a code edit.
Keys starting with _ are notes and get dropped.
"""

from __future__ import annotations

import json
from functools import lru_cache

from .config import DATA_DIR

RULES_PATH = DATA_DIR / "fraud_rules.json"


@lru_cache(maxsize=1)
def load_rules() -> dict:
    """Read the rules file once."""
    raw = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


class FraudRules:
    """Typed access, so nobody indexes raw dict keys."""

    def __init__(self, data: dict | None = None):
        self._d = data if data is not None else load_rules()

    @property
    def late_reporting_days(self) -> int:
        return int(self._d["late_reporting_days"])

    @property
    def round_amount_minimum(self) -> float:
        return float(self._d["round_amount_minimum"])

    @property
    def round_amount_multiple(self) -> float:
        return float(self._d["round_amount_multiple"])

    @property
    def theft_loss_types(self) -> set[str]:
        return set(self._d["theft_loss_types"])

    @property
    def forced_entry_evidence(self) -> tuple[str, ...]:
        return tuple(self._d["forced_entry_evidence"])

    @property
    def no_forced_entry(self) -> tuple[str, ...]:
        return tuple(self._d["no_forced_entry"])


RULES = FraudRules()
