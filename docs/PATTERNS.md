# Reusable agentic patterns (learnings)

Patterns captured while building TriageIQ. They generalise well beyond claims triage.

### 1. Structured output as a contract, not a hope
Define the agent's output as a typed schema (Pydantic) and make the terminal action a
`submit_<x>` tool whose input schema *is* that contract. You get validation for free and
downstream systems can trust the shape.
→ `schemas.py`, `submit_triage` in `tools.py`.

### 2. Validate-and-repair, don't crash
LLMs occasionally emit an invalid field. Catch the `ValidationError`, feed the error back once,
and let the model fix it. Bounded (one retry) so failures still surface.
→ `agent.py::_finalize`.

### 3. Ground every claim to a source
For any factual assertion (here: "is it covered?"), require the agent to cite the retrieved
artefact (clause id). Then *measure* grounding programmatically — does the cited clause actually
support the claim? This turns "hallucination" from a vibe into a number.
→ `knowledge.determine_coverage`, `eval/judge.grounding_check`.

### 4. A mock backend keeps the whole system runnable
Put the LLM behind one interface with a deterministic stub. The pipeline, tools, schemas and
eval all run for free, offline, and in CI — you only spend tokens when you want live numbers.
→ `llm.MockClient`.

### 5. Prompts/architectures are hypotheses; test them on a labeled set
Don't argue about which prompt is better — run both against gold labels and read the table.
Evidence-based iteration beats intuition.
→ `prompts.VARIANTS`, `eval/run_eval.py`.

### 6. Measure the boring things too
Track latency, cost and tool-call count alongside accuracy. A model that's 1% more accurate but
3× the cost is often the wrong call for a high-volume workflow. Surface the tradeoff.
→ latency/cost/tool_calls in `TriageDecision`.

### 7. Bound the loop
Always cap agent turns. Autonomy without a ceiling is an outage waiting to happen.
→ `MAX_TURNS` in `agent.py`.

### 8. Separate deterministic rules from model judgement
Cheap, auditable rules (dates, amounts) run in code; the model adds narrative judgement on top.
Cheaper, more explainable, and easier to test.
→ `tools.detect_fraud_signals`.

### 9. Keep tunable business rules in data, not code
Thresholds and phrase lists are parameters, not logic. Holding them in `data/fraud_rules.json`
means a claims or business user can tune "late reporting" from 30 days to 14, or add a phrase
the rules missed, without a code change, a deploy, or an engineer. The code keeps the *logic*;
the file keeps the *parameters*. Same reason policy wording lives in `policies.json`.

It also removed a duplication bug: the phrase lists had been copy-pasted into both the agent's
tools and the evaluation oracle, so they could silently drift apart. They now read one file —
shared reference **data**, while each still implements its decision **logic** independently, so
the eval can still catch a real regression.
→ `data/fraud_rules.json`, `src/triageiq/rules.py`.

### 10. Match the tool to the requirement: rules for auditability, models for language
Amount thresholds and policy status must be deterministic — a regulator can ask "why was this
declined?" and the answer has to be reproducible. But *reading a claimant's narrative* is the
opposite problem: people write "the door lock was broken", never "there was no forced entry",
and no keyword list can enumerate the tail. Keyword rules are the cheap, auditable, offline
floor; the LLM handles what the rules cannot express. Neither is the answer on its own.
→ `tools.detect_fraud_signals` (rules) + the live-mode agent narrative judgement.

### 11. Treat the model provider as a swappable dependency
Putting the LLM behind one narrow interface (`complete(system, messages, tools) -> LLMResponse`)
meant adding a second provider touched exactly one file. The agent loop, tools, schemas, eval
harness and tests were unchanged. Each backend owns the translation into its own wire format —
Gemini uses "model" instead of "assistant" roles, passes the system prompt as config rather than
a message, matches tool results by name instead of call id, and rejects union types in schemas.
That mess belongs in the adapter, not in the agent.

The real payoff is evaluative, not architectural: the *same* labeled dataset and metrics can now
be run across providers, turning "which model should we use?" into a table instead of an opinion.
→ `llm.AnthropicClient` / `llm.GeminiClient`, `config.PROVIDERS`, `run_eval.py --provider`.

### 12. Test invariants, not just examples (metamorphic testing)
Accuracy on a fixed dataset can't cover every input. Assert *relationships* that must hold for
any claim under a transformation: "making a claim look more fraudulent never lowers its risk
band," "rewording the description never changes the routing," "a lapsed policy is never
fast-tracked." These need no gold labels, run for free, and catch regressions a fixed test set
misses. Pair them with an independent labeling oracle for scalable, defensible evaluation.
→ `tests/test_properties.py`, `data/generate_data.py` (oracle).
