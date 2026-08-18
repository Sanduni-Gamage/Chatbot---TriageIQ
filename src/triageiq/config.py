"""Runtime config from .env. No key means MOCK mode."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv is optional at runtime
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"

# provider -> (env var holding its key, default model)
PROVIDERS: dict[str, tuple[str, str]] = {
    "anthropic": ("ANTHROPIC_API_KEY", "claude-sonnet-5"),
    "gemini": ("GEMINI_API_KEY", "gemini-3.6-flash"),
}


@dataclass(frozen=True)
class Config:
    api_key: str | None
    model: str
    mode: str                      # "live" or "mock"
    provider: str = "anthropic"    # which live backend to use

    @property
    def is_mock(self) -> bool:
        return self.mode == "mock"

    @property
    def label(self) -> str:
        """Label for reports and the UI badge."""
        return f"{self.provider}:{self.model}" if not self.is_mock else self.model


def _resolve_provider(explicit: str | None) -> str:
    """Provider precedence: argument, env var, then whichever key we have."""
    requested = (explicit or os.getenv("TRIAGEIQ_PROVIDER", "") or "").lower().strip()
    if requested in PROVIDERS:
        return requested
    if requested:
        raise ValueError(
            f"Unknown provider {requested!r}. Choose one of: {', '.join(PROVIDERS)}"
        )
    # Nothing specified, so use the first provider we have a key for.
    for name, (env_var, _) in PROVIDERS.items():
        if os.getenv(env_var):
            return name
    return "anthropic"


def load_config(provider: str | None = None, model: str | None = None) -> Config:
    """Build the config. Arguments win over env vars."""
    name = _resolve_provider(provider)
    env_var, default_model = PROVIDERS[name]

    api_key = os.getenv(env_var) or None
    chosen_model = model or os.getenv("TRIAGEIQ_MODEL") or default_model

    requested_mode = os.getenv("TRIAGEIQ_MODE", "auto").lower()
    if requested_mode == "mock":
        mode = "mock"
    elif requested_mode == "live":
        mode = "live"
    else:  # auto: live only if we actually have a key for this provider
        mode = "live" if api_key else "mock"

    # A model id from another provider is meaningless here.
    if model is None and not os.getenv("TRIAGEIQ_MODEL", "").startswith(_prefix(name)):
        if os.getenv("TRIAGEIQ_MODEL") and provider:
            chosen_model = default_model

    return Config(api_key=api_key, model=chosen_model, mode=mode, provider=name)


def _prefix(provider: str) -> str:
    return {"anthropic": "claude", "gemini": "gemini"}.get(provider, "")
