"""Shared test setup: pin every test to MOCK mode so none can reach a live API."""

from __future__ import annotations

import pytest

from triageiq.config import PROVIDERS


@pytest.fixture(autouse=True)
def offline_by_default(monkeypatch):
    monkeypatch.setenv("TRIAGEIQ_MODE", "mock")
    monkeypatch.delenv("TRIAGEIQ_PROVIDER", raising=False)
    monkeypatch.delenv("TRIAGEIQ_MODEL", raising=False)
    for env_var, _ in PROVIDERS.values():
        monkeypatch.delenv(env_var, raising=False)
