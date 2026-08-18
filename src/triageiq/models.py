"""Which models the current key can actually use.

Gemini's list is fetched and cached; Anthropic's is hardcoded. Feeds the UI picker.
"""

from __future__ import annotations

import re
import time

from .config import PROVIDERS, Config

# Families that can't run a tool-using text agent.
_UNSUITABLE = re.compile(
    r"(embedding|aqa|tts|image|imagen|veo|lyria|robotics|computer-use|deep-research|"
    r"nano-banana|omni|live)",
    re.IGNORECASE,
)

_ANTHROPIC_MODELS = [
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-4-5-20251001",
]

_CACHE: dict[str, tuple[float, list[str]]] = {}
_TTL_SECONDS = 600


def list_models(cfg: Config) -> list[str]:
    """Usable model ids, falling back to the provider default if the lookup fails."""
    default = PROVIDERS.get(cfg.provider, (None, cfg.model))[1]

    if cfg.provider == "anthropic":
        return _ANTHROPIC_MODELS
    if cfg.provider != "gemini" or not cfg.api_key:
        return [default]

    cached = _CACHE.get(cfg.provider)
    if cached and (time.time() - cached[0]) < _TTL_SECONDS:
        return cached[1]

    try:
        from google import genai

        client = genai.Client(api_key=cfg.api_key)
        found = []
        for model in client.models.list():
            actions = getattr(model, "supported_actions", None) or []
            if "generateContent" not in actions:
                continue
            name = (model.name or "").removeprefix("models/")
            if not name or _UNSUITABLE.search(name):
                continue
            found.append(name)
        models = sorted(set(found), reverse=True) or [default]
    except Exception:
        # Nice to have, not essential.
        models = [default]

    _CACHE[cfg.provider] = (time.time(), models)
    return models


def clear_cache() -> None:
    _CACHE.clear()
