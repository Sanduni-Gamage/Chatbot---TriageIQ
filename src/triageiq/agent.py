"""Turns a Claim into a validated TriageDecision via a bounded tool loop.

Works with any backend (see llm.py). Turns are capped so it can't spin forever,
and the final payload is schema-checked with one retry if the model gets it wrong.
"""

from __future__ import annotations

import argparse
import json
import time

from pydantic import ValidationError

from .config import PROVIDERS, load_config
from .llm import LLMClient, Usage, build_client, estimate_cost
from .prompts import system_prompt
from .schemas import Claim, TriageDecision
from .tools import TOOL_SCHEMAS, ToolExecutor

MAX_TURNS = 8


def triage(claim: Claim, client: LLMClient, variant: str = "baseline", model: str = "") -> TriageDecision:
    system = system_prompt(variant)
    executor = ToolExecutor(claim)
    messages: list[dict] = [{
        "role": "user",
        "content": f"Triage this claim. CLAIM_JSON: {claim.model_dump_json()}",
    }]

    start = time.perf_counter()
    in_tok = out_tok = 0

    for _ in range(MAX_TURNS):
        resp = client.complete(system, messages, TOOL_SCHEMAS)
        in_tok += resp.usage.input_tokens
        out_tok += resp.usage.output_tokens

        if not resp.tool_uses:
            # Finished without deciding — nudge it once.
            messages.append({"role": "assistant", "content": resp.text or "(no content)"})
            messages.append({"role": "user", "content": "Call submit_triage to finish."})
            continue

        # Keep the assistant turn, or the transcript goes invalid.
        assistant_blocks: list[dict] = []
        if resp.text:
            assistant_blocks.append({"type": "text", "text": resp.text})
        for tu in resp.tool_uses:
            assistant_blocks.append({"type": "tool_use", "id": tu.id, "name": tu.name, "input": tu.input})
        messages.append({"role": "assistant", "content": assistant_blocks})

        # Terminal tool?
        final = next((tu for tu in resp.tool_uses if tu.name == "submit_triage"), None)
        if final is not None:
            decision = _finalize(claim, final.input, executor, client, messages, system)
            elapsed = (time.perf_counter() - start) * 1000
            decision.latency_ms = round(elapsed, 1)
            decision.cost_usd = round(estimate_cost(model, Usage(in_tok, out_tok)), 6) if model else None
            decision.tool_calls = executor.calls
            return decision

        # Run whatever it asked for and hand the results back.
        tool_results = []
        for tu in resp.tool_uses:
            result = executor.run(tu.name, tu.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result),
            })
        messages.append({"role": "user", "content": tool_results})

    raise RuntimeError(f"Agent exceeded {MAX_TURNS} turns without submitting a decision.")


def _finalize(claim, payload, executor, client, messages, system) -> TriageDecision:
    """Validate the payload. One retry if the model got the shape wrong."""
    payload = {**payload, "claim_id": payload.get("claim_id") or claim.claim_id}
    try:
        return TriageDecision.model_validate(payload)
    except ValidationError as e:
        messages.append({
            "role": "user",
            "content": f"Your submit_triage payload was invalid: {e}. "
                       f"Call submit_triage again with corrected fields.",
        })
        resp = client.complete(system, messages, TOOL_SCHEMAS)
        retry = next((tu for tu in resp.tool_uses if tu.name == "submit_triage"), None)
        if retry is None:
            raise RuntimeError("Repair attempt did not resubmit a decision.") from e
        fixed = {**retry.input, "claim_id": retry.input.get("claim_id") or claim.claim_id}
        return TriageDecision.model_validate(fixed)


# ------------------------------------------------------------------
DEMO_CLAIM = Claim(
    claim_id="CLM-DEMO-1",
    policy_id="HOM-205678",
    loss_type="home_burglary",
    description="Contents stolen overnight. No forced entry found, no witnesses.",
    estimated_amount=12000.0,
    incident_date="2026-06-01",
    reported_date="2026-07-20",
    claimant_statement="I was away. Came back to missing TV and jewellery. No sign of break-in.",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TriageIQ on a claim.")
    parser.add_argument("--demo", action="store_true", help="Run the built-in demo claim.")
    parser.add_argument("--variant", default="baseline", choices=["baseline", "frugal", "strict"])
    parser.add_argument("--claim-file", help="Path to a claim JSON file.")
    parser.add_argument("--provider", choices=sorted(PROVIDERS),
                        help="LLM provider to use (default: from TRIAGEIQ_PROVIDER / whichever "
                             "API key is set).")
    parser.add_argument("--model", help="Override the model id for the chosen provider.")
    args = parser.parse_args()

    cfg = load_config(provider=args.provider, model=args.model)
    client = build_client(cfg)

    if args.claim_file:
        claim = Claim.model_validate_json(open(args.claim_file, encoding="utf-8").read())
    else:
        claim = DEMO_CLAIM

    print(f"Mode: {cfg.mode.upper()}  |  Provider: {cfg.provider}  |  Model: {cfg.model}  "
          f"|  Variant: {args.variant}\n")
    decision = triage(claim, client, variant=args.variant, model=cfg.model)
    print(decision.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
