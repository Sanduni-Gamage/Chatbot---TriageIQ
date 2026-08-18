# How to test TriageIQ

Everything below runs **free in MOCK mode** — no API key required.
Prefix commands with the venv python (`.venv\Scripts\python.exe` on Windows) or activate the
venv first: `.venv\Scripts\Activate.ps1`.

---

## 1. Automated tests (fastest signal)

```bash
pytest -q
```
Expect **26 passed**: 9 unit tests + 17 metamorphic/property tests.

See what each one checks:
```bash
pytest -v
```

Run just one group:
```bash
pytest tests/test_pipeline.py -v      # unit: knowledge, tools, agent
pytest tests/test_properties.py -v    # invariants & metamorphic properties
```

## 2. The agent from the command line

```bash
python -m triageiq.agent --demo
```
Expect a JSON `TriageDecision`. The demo claim (late-reported burglary, no forced entry) should
route to **SIU** with `fraud_risk: HIGH` and cite clause **HOM-C3**.

Try a different prompt variant:
```bash
python -m triageiq.agent --demo --variant strict
```

Run your own claim:
```bash
python -m triageiq.agent --claim-file my_claim.json
```
where `my_claim.json` looks like:
```json
{
  "claim_id": "TEST-1",
  "policy_id": "MOT-100234",
  "loss_type": "motor_collision",
  "description": "Minor rear-end collision.",
  "estimated_amount": 1800,
  "incident_date": "2026-08-01",
  "reported_date": "2026-08-02",
  "claimant_statement": ""
}
```

## 3. Dataset + evaluation harness

```bash
python data/generate_data.py
```
Expect **100 claims**, 25 per queue.

```bash
python eval/run_eval.py --variants baseline,frugal,strict
```
Expect a results table and `eval/report.md`. In MOCK mode scores are ~100% by construction
(the report says so) — this proves the *harness* works. Real numbers require LIVE mode.

## 4. The web UI

Build the React app once (Node 18+), then start the server:
```bash
npm --prefix frontend install
npm --prefix frontend run build
uvicorn triageiq.webapp:app --reload
```
Open <http://127.0.0.1:8000>.

**Manual test checklist:**

| # | Action | Expected |
|---|---|---|
| 1 | Page loads | Header shows `MOCK · claude-sonnet-5` badge |
| 2 | Click a sample chip | Form fields populate |
| 3 | Click **Triage claim →** | Your claim appears right-aligned; decision card appears left |
| 4 | Read the card | Queue badge, severity, coverage, cited clause, fraud signals, rationale, metadata |
| 5 | Policy `MOT-100999` (lapsed) + any loss | **INVESTIGATE**, coverage "Not confirmed ✗" |
| 6 | `HOM-205679` + `home_burglary` | **INVESTIGATE** — building-only policy excludes contents |
| 7 | Incident 2026-06-01, reported 2026-08-01, amount 12000, `home_burglary`, "no forced entry, no witnesses" | **SIU**, fraud HIGH, 3 signals triggered |
| 8 | Amount 1850, `motor_collision`, `MOT-100234`, reported next day | **FAST_TRACK** |
| 9 | Submit several claims | Each is appended; chat scrolls; claim ID auto-increments |

**API endpoints directly:**
```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/meta
```

## 5. Expected routing reference

Use these to sanity-check any change:

| Policy | Loss type | Amount | Reporting lag | Expected |
|---|---|---|---|---|
| `MOT-100234` | motor_collision | 1,850 | 1 day | **FAST_TRACK** |
| `HOM-205678` | home_fire | 45,000 | 1 day | **STANDARD** |
| `MOT-100999` (lapsed) | motor_collision | 9,000 | 1 day | **INVESTIGATE** |
| `HOM-205679` (building only) | home_burglary | 5,000 | 1 day | **INVESTIGATE** |
| `HOM-205678` | home_burglary + "no forced entry, no witnesses" | 12,000 | 61 days | **SIU** |

Rules being exercised: HIGH fraud (2+ signals) → SIU overrides everything; not covered →
INVESTIGATE; covered + LOW severity + LOW fraud → FAST_TRACK; else STANDARD.

## 6. React frontend dev mode

For hot reload while editing the UI, run two terminals:
```bash
uvicorn triageiq.webapp:app --reload    # :8000  (API)
npm --prefix frontend run dev           # :5173  (UI, proxies /api to :8000)
```
Use <http://localhost:5173> for development; changes reload instantly.

Re-run `npm --prefix frontend run build` to update the production bundle served on :8000.

## 7. LIVE mode (optional, costs cents)

Put a real key in `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
```
Then re-run any command above. The web UI badge turns green and reads `LIVE`. Re-running
`eval/run_eval.py` now produces genuine accuracy, grounding, latency and cost numbers, and the
three prompt variants will actually diverge.
