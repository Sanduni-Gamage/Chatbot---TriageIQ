# TriageIQ — Agentic Claims Triage & Coverage Assistant

> An LLM agent that reads a general-insurance claim (First Notice of Loss), checks coverage
> against policy wording, scores severity, flags fraud signals, and routes the claim to the
> right queue — with a rationale grounded in citations. Ships with a full **evaluation harness**
> that measures accuracy, grounding, latency and cost across prompt/model variants.

Built as a working demonstration of the skills in IAG's **Agentic Discovery Analyst** role:
turning an ambiguous business problem into a validated, measurable agentic prototype.

---

## Why this project

General insurance runs on claims. When a claim comes in, a human has to decide, fast:
*is it covered, how serious is it, does it smell fraudulent, and where should it go?* This is
exactly the kind of high-volume, judgement-heavy workflow where an agentic system can reduce
cycle time and delivery risk — **if** you can prove it's reliable. This project builds the agent
*and* the evidence.

It deliberately mirrors the job's "What You'll Do":

| Job responsibility | Where it lives in this repo |
|---|---|
| Building and running AI/agentic prototypes | `src/triageiq/agent.py` |
| Designing workflows combining LLMs, tools & enterprise knowledge | `src/triageiq/tools.py`, `src/triageiq/knowledge.py` |
| Experimenting with models, prompts and architectures | `src/triageiq/prompts.py`, `eval/run_eval.py` (variant sweep) |
| Evaluating performance, reliability & quality | `eval/` (metrics, LLM-as-judge, grounding checks) |
| Capturing learnings, reusable patterns and best practices | `docs/PATTERNS.md` |
| Helping shape solutions before production | `docs/ARCHITECTURE.md`, `docs/IAG_ALIGNMENT.md` |

---

## What it does (end to end)

```
FNOL claim ─▶ Triage Agent (Claude + tool loop)
                 ├─ lookup_policy(policy_id)          → enterprise knowledge store
                 ├─ check_coverage(loss_type)         → RAG over policy wording (citations)
                 ├─ assess_severity(claim)            → severity band + drivers
                 ├─ detect_fraud_signals(claim)       → rule + LLM hybrid risk flags
                 └─ route_claim(...)                  → FAST_TRACK | STANDARD | INVESTIGATE | SIU
              ─▶ Structured TriageDecision (validated JSON) + human-readable rationale
```

## Quickstart

```bash
python -m venv .venv && . .venv/Scripts/activate    # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .                                      # install the triageiq package (editable)
cp .env.example .env                                  # add your ANTHROPIC_API_KEY (optional)
```

Run the agent on a sample claim (works **offline** in mock mode with no API key):

```bash
python -m triageiq.agent --demo
```

Generate the labeled dataset and run the evaluation harness:

```bash
python data/generate_data.py
python eval/run_eval.py --variants baseline,frugal,strict
```

This prints a results table and writes `eval/report.md` — the artifact you show in interviews.

Run the test suite (unit + metamorphic/property tests — all free, no key needed):

```bash
pytest -q
```

Launch the **web chat UI** — a React app served by the FastAPI backend. Build it once
(requires Node 18+), then start the server:

```bash
npm --prefix frontend install
npm --prefix frontend run build      # emits web/dist/, which the server serves
uvicorn triageiq.webapp:app --reload
```

Then open http://127.0.0.1:8000 — pick a sample claim or fill the form, and the agent replies
with a routed decision, the policy clause it relied on, fraud signals, and its rationale.

The UI source lives in [`frontend/`](frontend/README.md) (React + Vite). `web/dist/` is build
output and is not committed, so build it after cloning; the server shows a reminder if you
forget. The API works with or without the UI built.

> **No API key?** Everything runs in `MOCK` mode (deterministic stub LLM) so the pipeline,
> tools, schemas and eval harness all work end to end for free. Add a real key to see live
> model behaviour and true cost/latency numbers.

### Choosing a model provider

The agent is provider-agnostic. Set a key for whichever you have — **Google Gemini has a free
tier**, so it costs nothing to run live:

| Provider | Key | Default model | Get a key |
|---|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-5` | console.anthropic.com |
| `gemini` | `GEMINI_API_KEY` | `gemini-2.5-flash` | aistudio.google.com (free tier) |

```bash
pip install google-genai            # only needed for the Gemini backend
python -m triageiq.agent --demo --provider gemini
```

Because the eval harness is shared, the same 100-claim dataset can be scored across providers —
turning "which model should we use?" into a measurement:

```bash
python eval/run_eval.py --variants baseline --provider anthropic
python eval/run_eval.py --variants baseline --provider gemini
```

> **Mind the free-tier quota.** Each claim costs roughly 5 API calls (4 tools + the final
> decision), and Gemini's free tier currently allows only ~20 requests per day per model — about
> 4 claims. Use `--limit` for a cheap smoke test, and expect a full 100-claim run to need a paid
> tier. The runner retries transient 429s and stops cleanly on a daily quota wall, scoring
> whatever completed rather than losing the run.

```bash
python eval/run_eval.py --variants baseline --limit 4     # fits inside a free daily quota
```

## Repo layout

```
src/triageiq/   agent loop, tools, knowledge store, schemas, prompts, LLM wrapper, web server
frontend/       React + Vite chat UI (source)
web/dist/       built UI assets, emitted by `npm run build` (not committed)
data/           synthetic policy wordings + labeled claim dataset generator (100 claims)
eval/           metrics, LLM-as-judge, grounding check, variant runner, report
docs/           ARCHITECTURE, PATTERNS, IAG_ALIGNMENT
cv/             CV bullet points + cover-letter paragraph you can lift straight in
tests/          unit tests + metamorphic/property tests
```

## Design principles

1. **Structured output, always validated.** Every agent decision is a Pydantic model; invalid
   output triggers a bounded repair retry, not a crash.
2. **Grounded, not guessed.** Coverage decisions must cite retrieved policy clauses; the eval
   harness measures how often the rationale is actually supported.
3. **Measure before you believe.** No prompt or model change ships without a number moving in
   `eval/report.md`.
4. **Runs for free.** Mock mode keeps the whole thing demoable and CI-friendly without spend.

See [`docs/IAG_ALIGNMENT.md`](docs/IAG_ALIGNMENT.md) for how each piece maps to the role, and
[`docs/TESTING.md`](docs/TESTING.md) for a full manual + automated test checklist.
