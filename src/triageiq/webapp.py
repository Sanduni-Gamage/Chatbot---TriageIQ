"""FastAPI server: the triage API plus the built React UI.

Run: npm --prefix frontend run build && uvicorn triageiq.webapp:app --reload
"""

from __future__ import annotations

import json
import threading

from fastapi import FastAPI, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .agent import triage
from .config import PROVIDERS, DATA_DIR, REPO_ROOT, Config, load_config
from .llm import RateLimitedError, build_client
from .models import list_models
from .schemas import Claim, LossType

app = FastAPI(title="TriageIQ", version=__version__)

# Startup config is the default; a request can pick something else.
_CFG = load_config()

# Cached per (provider, model) so we build each SDK client once.
_clients: dict[tuple[str, str, str], object] = {}
_clients_lock = threading.Lock()


class TriageRequest(BaseModel):
    """A claim, plus whichever model the UI picked."""

    claim: Claim
    provider: str | None = None
    model: str | None = None


def _config_for(provider: str | None, model: str | None) -> Config:
    if not provider and not model:
        return _CFG
    return load_config(provider=provider or _CFG.provider, model=model or None)


def _client_for(cfg: Config):
    key = (cfg.provider, cfg.model, cfg.mode)
    with _clients_lock:
        client = _clients.get(key)
        if client is None:
            client = build_client(cfg)
            _clients[key] = client
        return client

DIST_DIR = REPO_ROOT / "web" / "dist"   # produced by `npm run build` in frontend/
_HAS_REACT_BUILD = (DIST_DIR / "index.html").exists()

_BUILD_HINT = """<!doctype html>
<title>TriageIQ — build the UI</title>
<style>body{font:15px/1.6 system-ui,sans-serif;max-width:38rem;margin:12vh auto;padding:0 1.5rem}
code{background:#8883;padding:.15em .4em;border-radius:4px}</style>
<h1>TriageIQ</h1>
<p>The API is running, but the React UI has not been built yet
(<code>web/dist/</code> is missing — it is a build artifact and is not committed).</p>
<p>Build it once, then restart this server:</p>
<pre><code>npm --prefix frontend install
npm --prefix frontend run build</code></pre>
<p>The API works regardless — try <a href="/api/health">/api/health</a>.</p>
"""


@app.get("/")
def index():
    """Serve the built React app, or tell them how to build it."""
    if not _HAS_REACT_BUILD:
        return HTMLResponse(_BUILD_HINT, status_code=503)
    return FileResponse(DIST_DIR / "index.html")


# The page links an inline SVG icon; this covers clients that probe /favicon.ico anyway.
_FAVICON_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
    "<rect width='100' height='100' rx='22' fill='#2b6cb0'/>"
    "<path d='M50 20l24 10v18c0 15-10 27-24 32-14-5-24-17-24-32V30z' fill='none' "
    "stroke='#fff' stroke-width='7' stroke-linejoin='round'/>"
    "<path d='M38 51l9 9 17-18' fill='none' stroke='#fff' stroke-width='7' "
    "stroke-linecap='round' stroke-linejoin='round'/></svg>"
)


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(_FAVICON_SVG, media_type="image/svg+xml")


@app.get("/api/health")
def health() -> dict:
    return {"mode": _CFG.mode, "provider": _CFG.provider, "model": _CFG.model,
            "version": __version__}


@app.get("/api/meta")
def meta() -> dict:
    """Dropdown options and a few sample claims for the UI."""
    policies = [
        {"policy_id": p["policy_id"], "product": p["product"], "status": p["status"]}
        for p in json.loads((DATA_DIR / "policies.json").read_text("utf-8"))
    ]
    loss_types = [lt.value for lt in LossType]

    samples: list[dict] = []
    claims_file = DATA_DIR / "claims.jsonl"
    if claims_file.exists():
        rows = [json.loads(line) for line in claims_file.read_text("utf-8").splitlines() if line.strip()]
        # spread them out so every queue shows up
        step = max(1, len(rows) // 6)
        samples = [rows[i]["claim"] for i in range(0, len(rows), step)][:6]

    return {"policies": policies, "loss_types": loss_types, "samples": samples}


@app.get("/api/models")
def models() -> dict:
    """Models the UI can offer. Only providers we have a key for."""
    available: list[dict] = []
    for name in PROVIDERS:
        cfg = load_config(provider=name)
        if cfg.is_mock:
            continue
        available.append({"provider": name, "models": list_models(cfg)})

    return {
        "providers": available,
        "current": {"provider": _CFG.provider, "model": _CFG.model, "mode": _CFG.mode},
        "mock": _CFG.is_mock,
    }


@app.post("/api/triage")
def do_triage(request: TriageRequest) -> JSONResponse:
    """Run the agent on a claim, optionally on a chosen model."""
    try:
        cfg = _config_for(request.provider, request.model)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    try:
        decision = triage(request.claim, _client_for(cfg), model=cfg.model)
        payload = decision.model_dump()
        payload["provider"] = cfg.provider
        payload["model"] = cfg.model
        return JSONResponse(payload)
    except RateLimitedError as exc:
        return JSONResponse(
            {"error": f"{exc} Pick a different model above and try again."},
            status_code=429,
        )
    except Exception as exc:  # keep the UI responsive on any agent/model failure
        return JSONResponse({"error": str(exc)}, status_code=500)


# Mounted last so the /api routes above always win.
if _HAS_REACT_BUILD:
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")
