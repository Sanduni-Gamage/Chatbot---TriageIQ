# TriageIQ frontend (React + Vite)

React chat UI for the claims-triage agent. Talks to the FastAPI backend in
`src/triageiq/webapp.py`.

## Prerequisites
Node.js 18+ (includes npm) — https://nodejs.org (LTS installer).
Verify with `node --version && npm --version`.

## Install
```bash
cd frontend
npm install
```

## Develop (hot reload)
Run the backend and the Vite dev server in two terminals:

```bash
# terminal 1 — API on :8000
uvicorn triageiq.webapp:app --reload

# terminal 2 — UI on :5173 (proxies /api to :8000)
cd frontend && npm run dev
```
Open http://localhost:5173.

## Build for production
```bash
cd frontend && npm run build
```
This emits `web/dist/`, which the FastAPI server serves — so afterwards you only need:

```bash
uvicorn triageiq.webapp:app
```
and http://127.0.0.1:8000 serves the React UI.

> `web/dist/` is build output and is not committed. After cloning, run the build before
> starting the server; if you forget, the server responds with a short reminder page instead
> of the UI. The `/api/*` endpoints work either way.

## Structure
```
src/main.jsx                  entry point
src/App.jsx                   chat state, message list, submit flow
src/api.js                    fetch wrappers for the backend
src/components/ClaimForm.jsx  sample chips + claim entry fields
src/components/DecisionCard.jsx  renders a TriageDecision
src/styles.css                design tokens, light/dark theming
```
