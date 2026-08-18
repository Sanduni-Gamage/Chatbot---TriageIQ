"""One interface, several backends, so agent.py never cares who serves the model.

Anthropic and Gemini hit real APIs. MockClient fakes the same tool-use protocol,
so the whole thing runs offline for free.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import Config

# USD per 1M tokens (input, output). Rough estimates — check the provider's
# pricing page before quoting these anywhere.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5": (15.0, 75.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "gemini-3.7-flash": (0.30, 2.50),
    "gemini-3.6-flash": (0.30, 2.50),
    "gemini-3.5-flash": (0.30, 2.50),
    "gemini-3.5-flash-lite": (0.10, 0.40),
    "gemini-3.1-flash-lite": (0.10, 0.40),
    "gemini-3.1-flash-lite-preview": (0.10, 0.40),
    "gemini-3-flash-preview": (0.30, 2.50),
    "gemini-3.1-pro-preview": (1.25, 10.0),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-pro": (1.25, 10.0),
}

# Fallback by family, so a brand-new model id still shows a cost.
_PRICE_FAMILIES: tuple[tuple[str, tuple[float, float]], ...] = (
    ("flash-lite", (0.10, 0.40)),
    ("haiku", (1.0, 5.0)),
    ("flash", (0.30, 2.50)),
    ("sonnet", (3.0, 15.0)),
    ("pro", (1.25, 10.0)),
    ("opus", (15.0, 75.0)),
)


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class LLMResponse:
    text: str = ""
    tool_uses: list[ToolUse] = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: Usage = field(default_factory=Usage)

    @property
    def wants_tools(self) -> bool:
        return self.stop_reason == "tool_use" or bool(self.tool_uses)


def estimate_cost(model: str, usage: Usage) -> float:
    """Rough spend for a call: exact id, then family guess, then zero."""
    rates = PRICES.get(model)
    if rates is None:
        lowered = model.lower()
        rates = next((r for token, r in _PRICE_FAMILIES if token in lowered), (0.0, 0.0))
    in_rate, out_rate = rates
    return (usage.input_tokens * in_rate + usage.output_tokens * out_rate) / 1_000_000


class LLMClient(Protocol):
    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse: ...


# --------------------------------------------------------------------------- live
class AnthropicClient:
    def __init__(self, cfg: Config):
        from anthropic import Anthropic

        self._client = Anthropic(api_key=cfg.api_key)
        self._model = cfg.model

    def complete(self, system, messages, tools):
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=1500,
            system=system,
            messages=messages,
            tools=tools,
        )
        text_parts, tool_uses = [], []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(ToolUse(id=block.id, name=block.name, input=block.input))
        return LLMResponse(
            text="".join(text_parts),
            tool_uses=tool_uses,
            stop_reason=resp.stop_reason,
            usage=Usage(resp.usage.input_tokens, resp.usage.output_tokens),
        )


# --------------------------------------------------------------------------- gemini
class RateLimitedError(RuntimeError):
    """Quota is gone and waiting won't help."""


def _retry_delay_seconds(message: str) -> float | None:
    """The wait the server asked for, if it said."""
    match = re.search(r"['\"]?retryDelay['\"]?[:=]\s*['\"]?(\d+(?:\.\d+)?)s", message)
    if match:
        return float(match.group(1))
    match = re.search(r"retry in (\d+(?:\.\d+)?)s", message)
    return float(match.group(1)) if match else None


def _with_rate_limit_retry(call, attempts: int = 3, max_wait: float = 65.0):
    """Retry a 429, waiting as long as the server asks.

    A daily quota can't be waited out, so raise straight away instead.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return call()
        except Exception as exc:  # provider SDKs raise their own error types
            message = str(exc)
            if "429" not in message and "RESOURCE_EXHAUSTED" not in message:
                raise
            last = exc
            if "PerDay" in message or "per day" in message.lower():
                raise RateLimitedError(
                    "Daily free-tier quota exhausted for this model. Try again tomorrow, "
                    "switch model with --model, or use --provider anthropic."
                ) from exc
            wait = _retry_delay_seconds(message) or (2.0 ** attempt)
            if attempt == attempts - 1 or wait > max_wait:
                break
            time.sleep(wait + 0.5)
    raise RateLimitedError(f"Rate limited after {attempts} attempts: {last}") from last


def _gemini_schema(schema: dict) -> dict:
    """Trim a tool schema down to what Gemini accepts.

    It rejects union types like {"type": ["string", "null"]}, so collapse them.
    """
    if not isinstance(schema, dict):
        return schema

    out: dict = {}
    for key, value in schema.items():
        if key in {"additionalProperties", "$schema", "default"}:
            continue
        if key == "type" and isinstance(value, list):
            non_null = [t for t in value if t != "null"]
            out["type"] = non_null[0] if non_null else "string"
        elif key == "properties" and isinstance(value, dict):
            out["properties"] = {k: _gemini_schema(v) for k, v in value.items()}
        elif key == "items":
            out["items"] = _gemini_schema(value)
        else:
            out[key] = value

    # Gemini insists object schemas declare properties.
    if out.get("type") == "object" and "properties" not in out:
        out["properties"] = {}
    return out


class GeminiClient:
    """Gemini backend.

    Converts the Anthropic-shaped transcript to Gemini's format and back: "model" role
    instead of "assistant", system prompt as config, tool results matched by name.
    """

    def __init__(self, cfg: Config):
        from google import genai  # imported lazily so the dep is optional

        self._genai = genai
        self._client = genai.Client(api_key=cfg.api_key)
        self._model = cfg.model
        # Gemini 3.x wants each call's thought signature echoed back on replay.
        # Provider-specific, so it stays here rather than in the shared format.
        self._signatures: dict[str, object] = {}
        self._call_seq = 0

    def complete(self, system, messages, tools):
        from google.genai import types

        declarations = [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": _gemini_schema(t["input_schema"]),
            }
            for t in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            tools=[types.Tool(function_declarations=declarations)] if declarations else None,
        )
        contents = self._to_contents(messages)

        resp = _with_rate_limit_retry(
            lambda: self._client.models.generate_content(
                model=self._model, contents=contents, config=config,
            )
        )
        return self._from_response(resp)

    # -- request translation -------------------------------------------------
    def _to_contents(self, messages: list[dict]) -> list[dict]:
        """Anthropic-style messages -> Gemini `contents`."""
        id_to_name = {
            block["id"]: block["name"]
            for msg in messages
            if isinstance(msg.get("content"), list)
            for block in msg["content"]
            if isinstance(block, dict) and block.get("type") == "tool_use"
        }

        contents: list[dict] = []
        for msg in messages:
            content = msg.get("content")
            role = "model" if msg.get("role") == "assistant" else "user"

            if isinstance(content, str):
                contents.append({"role": role, "parts": [{"text": content}]})
                continue

            parts: list[dict] = []
            for block in content or []:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text" and block.get("text"):
                    parts.append({"text": block["text"]})
                elif btype == "tool_use":
                    part: dict = {"function_call": {
                        "name": block["name"],
                        "args": block.get("input") or {},
                    }}
                    signature = self._signatures.get(block.get("id", ""))
                    if signature is not None:
                        part["thought_signature"] = signature
                    parts.append(part)
                elif btype == "tool_result":
                    name = id_to_name.get(block.get("tool_use_id", ""), "unknown_tool")
                    parts.append({"function_response": {
                        "name": name,
                        "response": _as_dict(block.get("content")),
                    }})
            if parts:
                contents.append({"role": role, "parts": parts})
        return contents

    # -- response translation ------------------------------------------------
    def _from_response(self, resp) -> LLMResponse:
        text_parts: list[str] = []
        tool_uses: list[ToolUse] = []

        candidates = getattr(resp, "candidates", None) or []
        for part in _parts_of(candidates):
            call = getattr(part, "function_call", None)
            if call is not None and getattr(call, "name", None):
                self._call_seq += 1
                # Ids must stay unique — a repeat replays the wrong signature.
                call_id = getattr(call, "id", None) or f"gemini_{call.name}_{self._call_seq}"
                signature = getattr(part, "thought_signature", None)
                if signature is not None:
                    self._signatures[call_id] = signature
                tool_uses.append(ToolUse(
                    id=call_id,
                    name=call.name,
                    input=dict(getattr(call, "args", None) or {}),
                ))
            elif getattr(part, "text", None):
                text_parts.append(part.text)

        meta = getattr(resp, "usage_metadata", None)
        usage = Usage(
            input_tokens=getattr(meta, "prompt_token_count", 0) or 0,
            output_tokens=getattr(meta, "candidates_token_count", 0) or 0,
        )
        return LLMResponse(
            text="".join(text_parts),
            tool_uses=tool_uses,
            stop_reason="tool_use" if tool_uses else "end_turn",
            usage=usage,
        )


def _parts_of(candidates) -> list:
    content = getattr(candidates[0], "content", None) if candidates else None
    return list(getattr(content, "parts", None) or [])


def _as_dict(raw) -> dict:
    """Gemini requires a function response to be a JSON object."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"result": raw}
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    return {"result": raw}


# --------------------------------------------------------------------------- mock
class MockClient:
    """Deterministic stand-in for the real agent loop.

    Walks the transcript, asks for whichever tool hasn't run, then builds the final
    submit_triage call from what it gathered.
    """

    _ORDER = ["lookup_policy", "check_coverage", "assess_severity", "detect_fraud_signals"]

    def __init__(self, cfg: Config):
        self._model = cfg.model

    def complete(self, system, messages, tools):
        results = _collect_tool_results(messages)
        claim = _find_claim(messages)

        for tool_name in self._ORDER:
            if tool_name not in results:
                return self._request(tool_name, claim, results)

        decision = _synthesize_decision(claim, results)
        usage = _rough_usage(system, messages, decision)
        return LLMResponse(
            tool_uses=[ToolUse(id="mock_final", name="submit_triage", input=decision)],
            stop_reason="tool_use",
            usage=usage,
        )

    def _request(self, name: str, claim: dict, results: dict) -> LLMResponse:
        args: dict[str, Any] = {}
        if name == "lookup_policy":
            args = {"policy_id": claim.get("policy_id", "")}
        elif name == "check_coverage":
            args = {"policy_id": claim.get("policy_id", ""), "loss_type": claim.get("loss_type", "")}
        else:  # assess_severity / detect_fraud_signals both take the claim
            args = {"claim_id": claim.get("claim_id", "")}
        return LLMResponse(
            tool_uses=[ToolUse(id=f"mock_{name}", name=name, input=args)],
            stop_reason="tool_use",
        )


# --------------------------------------------------------------------------- helpers
def _collect_tool_results(messages: list[dict]) -> dict[str, Any]:
    """Tool name -> result, resolved through the ids on the tool_use blocks."""
    id_to_name: dict[str, str] = {}
    results: dict[str, Any] = {}
    for msg in messages:
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                id_to_name[block["id"]] = block["name"]
            elif isinstance(block, dict) and block.get("type") == "tool_result":
                name = id_to_name.get(block.get("tool_use_id", ""))
                if name:
                    raw = block.get("content", "")
                    try:
                        results[name] = json.loads(raw) if isinstance(raw, str) else raw
                    except json.JSONDecodeError:
                        results[name] = raw
    return results


def _find_claim(messages: list[dict]) -> dict:
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str) and "CLAIM_JSON:" in content:
            return json.loads(content.split("CLAIM_JSON:", 1)[1].strip())
    return {}


def _explain(claim, queue, covered, coverage, sev_band, fraud_risk, signals) -> str:
    """Plain-English rationale: the facts, the decision, and the rule behind it."""
    loss = str(claim.get("loss_type", "claim")).replace("_", " ")
    amount = float(claim.get("estimated_amount") or 0)
    opening = f"{loss.capitalize()} claim for ${amount:,.0f}."

    # --- coverage
    clause_id = coverage.get("clause_id")
    if covered and clause_id:
        cover_bit = f"Cover is confirmed under clause {clause_id}."
    elif covered:
        cover_bit = "Cover is confirmed."
    else:
        cover_bit = f"Cover could not be confirmed: {coverage.get('reason', 'no matching clause')}"
        if not cover_bit.endswith("."):
            cover_bit += "."

    # --- fraud
    fired = [s["name"].replace("_", " ") for s in signals if s.get("triggered")]
    if fired:
        fraud_bit = (
            f"Fraud risk is {fraud_risk} — {len(fired)} indicator"
            f"{'s' if len(fired) > 1 else ''} triggered ({', '.join(fired)})."
        )
    else:
        fraud_bit = "No fraud indicators were triggered."

    # --- the decision, and the rule that produced it
    if queue == "SIU":
        why = ("High fraud risk overrides all other routing, so this goes to the Special "
               "Investigations Unit for review before any payment is considered.")
    elif queue == "INVESTIGATE":
        why = ("Because cover is not established, the claim needs manual review to determine "
               "whether any policy response applies.")
    elif queue == "FAST_TRACK":
        why = (f"Cover is clear, exposure is {sev_band.lower()} and nothing looks suspicious, "
               "so it meets the fast-track criteria and can be settled without assessor review.")
    else:  # STANDARD
        if sev_band != "LOW" and fraud_risk == "LOW":
            why = (f"{sev_band.capitalize()} severity puts this above the fast-track threshold, "
                   "so it is queued for a claims assessor.")
        elif fraud_risk == "MEDIUM":
            why = ("A single fraud indicator rules out fast-tracking, so a claims assessor "
                   "should review it.")
        else:
            why = "It is queued for standard assessor handling."

    return " ".join([opening, cover_bit, f"Severity is {sev_band}.", fraud_bit, why])


def _synthesize_decision(claim: dict, results: dict) -> dict:
    coverage = results.get("check_coverage", {})
    severity = results.get("assess_severity", {})
    fraud = results.get("detect_fraud_signals", {})

    covered = bool(coverage.get("covered", False))
    sev_band = severity.get("severity", "MEDIUM")
    fraud_risk = fraud.get("fraud_risk", "LOW")
    signals = fraud.get("signals", [])

    if fraud_risk == "HIGH":
        queue = "SIU"
    elif not covered:
        queue = "INVESTIGATE"
    elif sev_band == "LOW" and fraud_risk == "LOW":
        queue = "FAST_TRACK"
    else:
        queue = "STANDARD"

    rationale = _explain(claim, queue, covered, coverage, sev_band, fraud_risk, signals)
    return {
        "claim_id": claim.get("claim_id", "unknown"),
        "severity": sev_band,
        "coverage": {
            "covered": covered,
            "clause_id": coverage.get("clause_id"),
            "clause_text": coverage.get("clause_text"),
            "reason": coverage.get("reason", ""),
        },
        "fraud_signals": signals,
        "fraud_risk": fraud_risk,
        "recommended_queue": queue,
        "rationale": rationale,
    }


def _rough_usage(system: str, messages: list, decision: dict) -> Usage:
    text = system + json.dumps(messages) + json.dumps(decision)
    approx = max(1, len(text) // 4)  # ~4 chars/token
    return Usage(input_tokens=approx, output_tokens=max(1, len(json.dumps(decision)) // 4))


_BACKENDS = {"anthropic": AnthropicClient, "gemini": GeminiClient}


def build_client(cfg: Config) -> LLMClient:
    """Pick a backend. Mock short-circuits, so no SDK or key needed."""
    if cfg.is_mock:
        return MockClient(cfg)
    try:
        backend = _BACKENDS[cfg.provider]
    except KeyError:
        raise ValueError(
            f"No backend for provider {cfg.provider!r}. Known: {', '.join(_BACKENDS)}"
        ) from None
    return backend(cfg)
