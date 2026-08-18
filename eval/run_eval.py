"""Run the triage agent over the labeled dataset for one or more prompt variants and report:

  routing accuracy | routing macro-F1 | severity accuracy | coverage accuracy
  grounding rate (hallucination guard) | avg rationale score | avg latency | est. cost

Writes a markdown results table to eval/report.md.

Run:  python eval/run_eval.py --variants baseline,frugal,strict
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as a plain script without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from triageiq.agent import triage  # noqa: E402
from triageiq.config import DATA_DIR, PROVIDERS, load_config  # noqa: E402
from triageiq.llm import RateLimitedError, build_client  # noqa: E402
from triageiq.schemas import Claim, LabeledClaim  # noqa: E402

import metrics  # noqa: E402
import judge  # noqa: E402

QUEUES = ["FAST_TRACK", "STANDARD", "INVESTIGATE", "SIU"]
SEVERITIES = ["LOW", "MEDIUM", "HIGH"]


def load_dataset(limit: int | None = None) -> list[LabeledClaim]:
    path = DATA_DIR / "claims.jsonl"
    if not path.exists():
        sys.exit("No dataset. Run: python data/generate_data.py")
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
    dataset = [LabeledClaim.model_validate(r) for r in rows]
    if limit:
        # Even stride, so a short run still covers every queue.
        step = max(1, len(dataset) // limit)
        dataset = dataset[::step][:limit]
    return dataset


def evaluate_variant(variant: str, dataset, client, cfg) -> dict:
    q_pairs, s_pairs, c_pairs = [], [], []
    grounded, judge_scores, latencies, costs = 0, [], [], []
    errors: list[str] = []

    for i, item in enumerate(dataset, start=1):
        claim: Claim = item.claim
        try:
            decision = triage(claim, client, variant=variant, model=cfg.model)
        except RateLimitedError as exc:
            # Hitting a quota is not a model failure — score what finished.
            print(f"  [{variant}] stopped at claim {i}/{len(dataset)}: {exc}", file=sys.stderr)
            break
        except Exception as exc:
            # One bad claim should not sink a long run.
            errors.append(f"{claim.claim_id}: {type(exc).__name__}: {exc}")
            print(f"  [{variant}] claim {claim.claim_id} failed: {exc}", file=sys.stderr)
            continue

        q_pairs.append((item.gold_queue.value, decision.recommended_queue.value))
        s_pairs.append((item.gold_severity.value, decision.severity.value))
        c_pairs.append((str(item.gold_covered), str(decision.coverage.covered)))

        g = judge.grounding_check(claim, decision)
        grounded += int(g["grounded"])
        judge_scores.append(judge.rationale_score(decision, client, cfg.model, cfg.is_mock))
        if decision.latency_ms is not None:
            latencies.append(decision.latency_ms)
        if decision.cost_usd is not None:
            costs.append(decision.cost_usd)

    n = len(q_pairs)  # scored, not attempted
    return {
        "variant": variant,
        "routing_acc": metrics.accuracy(q_pairs),
        "routing_f1": metrics.macro_f1(q_pairs, QUEUES),
        "severity_acc": metrics.accuracy(s_pairs),
        "coverage_acc": metrics.accuracy(c_pairs),
        "grounding_rate": grounded / n if n else 0.0,
        "avg_judge": sum(judge_scores) / n if n else 0.0,
        "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
        "total_cost": sum(costs) if costs else 0.0,
        "confusion": metrics.confusion(q_pairs, QUEUES),
        "n": n,
        "attempted": len(dataset),
        "errors": errors,
    }


def render_report(results: list[dict], cfg) -> str:
    lines = ["# TriageIQ — Evaluation Report", ""]
    scored, attempted = results[0]["n"], results[0].get("attempted", results[0]["n"])
    size = (f"**{scored}** claims" if scored == attempted
            else f"**{scored}** of {attempted} claims scored (run stopped early)")
    lines.append(f"- Mode: **{cfg.mode.upper()}**  |  Provider: **{cfg.provider}**  |  "
                 f"Model: `{cfg.model}`  |  Dataset size: {size}")
    if cfg.is_mock:
        lines.append("")
        lines.append("> **NOTE — MOCK mode**: the stub LLM follows the same reference logic used to "
                     "define the gold labels, so scores are near-perfect by construction and "
                     "variants do not diverge. This run proves the *harness* works. Add an "
                     "`ANTHROPIC_API_KEY` and re-run in LIVE mode to get a real measurement where "
                     "prompt variants actually differ.")
    lines.append("")
    lines.append("| Variant | Routing acc | Routing F1 | Severity acc | Coverage acc | "
                 "Grounding | Judge (1-5) | Avg latency (ms) | Est. cost (USD) |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        lines.append(
            f"| `{r['variant']}` | {r['routing_acc']:.0%} | {r['routing_f1']:.2f} | "
            f"{r['severity_acc']:.0%} | {r['coverage_acc']:.0%} | {r['grounding_rate']:.0%} | "
            f"{r['avg_judge']:.2f} | {r['avg_latency_ms']:.0f} | {r['total_cost']:.4f} |"
        )
    lines.append("")
    for r in results:
        lines.append(f"### Routing confusion — `{r['variant']}`\n")
        lines.append("```\n" + r["confusion"] + "\n```\n")
    lines.append("> Grounding = share of decisions whose coverage claim cites a clause that "
                 "actually supports it (hallucination guard).")
    failed = [e for r in results for e in r.get("errors", [])]
    if failed:
        lines.append("")
        lines.append(f"### Claims that failed to score ({len(failed)})\n")
        for err in failed[:20]:
            lines.append(f"- `{err}`")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variants", default="baseline",
                        help="Comma-separated: baseline,frugal,strict")
    parser.add_argument("--provider", choices=sorted(PROVIDERS),
                        help="LLM provider (default: from TRIAGEIQ_PROVIDER / whichever key is set)")
    parser.add_argument("--model", help="Override the model id for the chosen provider")
    parser.add_argument("--limit", type=int,
                        help="Score only N claims, evenly spread across the dataset. Useful for a cheap live smoke test before committing to a full run.")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # keep unicode safe on Windows consoles
    except Exception:
        pass

    cfg = load_config(provider=args.provider, model=args.model)
    client = build_client(cfg)
    dataset = load_dataset(args.limit)

    results = [evaluate_variant(v.strip(), dataset, client, cfg)
               for v in args.variants.split(",") if v.strip()]

    report = render_report(results, cfg)
    out = Path(__file__).resolve().parent / "report.md"
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
