"""server.py — thin FastAPI over the headless engine (in-process calls).

Hard requirements honored here:
  - bound to 127.0.0.1 only (single-user localhost tool).
  - keys are write-only: GET /providers returns last-4 + status, never the key.
  - provider/config endpoints are additionally localhost-guarded (defence in depth
    if someone overrides the bind host).
  - /research and /converse degrade gracefully — one model down ≠ a crash.

Run:  python -m web.server   (http://127.0.0.1:8765)
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine import modes, providers, secrets, settings
from engine import transcript as T

app = FastAPI(title="research room")
STATIC_DIR = Path(__file__).resolve().parent / "static"

# serialize transcript-appends and config writes (localhost, single researcher)
_lock = threading.Lock()
_last_test: dict[str, dict] = {}   # in-memory last test result per provider


# ---- request bodies ---------------------------------------------------------
class ResearchBody(BaseModel):
    prompt: str
    effort: str = "medium"


class ConverseBody(BaseModel):
    prompt: str
    addressed_to: str | None = None


class NewBody(BaseModel):
    title: str


class SelectBody(BaseModel):
    path: str


class ProviderCreate(BaseModel):
    name: str
    base_url: str
    model: str = ""
    auth_mode: str = "api"
    backend: str = "openai"
    api_key: str | None = None   # write-only


class ProviderUpdate(BaseModel):
    base_url: str | None = None
    model: str | None = None
    enabled: bool | None = None
    auth_mode: str | None = None
    api_key: str | None = None   # write-only; never returned


class JudgeBody(BaseModel):
    name: str


# ---- localhost guard (config endpoints touch secrets) -----------------------
def localhost_only(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(403, "provider/config endpoints are localhost-only")


# ---- views ------------------------------------------------------------------
def _status(name: str, p: providers.Provider) -> str:
    if not p.enabled:
        return "disabled"
    if p.auth_mode == "cli":
        lt = _last_test.get(name)
        return ("ok" if lt["ok"] else "error") if lt else "subscription"
    if not secrets.has_key(name):
        return "no_key"
    lt = _last_test.get(name)
    return ("ok" if lt["ok"] else "error") if lt else "ready"


def _provider_view(name: str, p: providers.Provider) -> dict:
    return {
        "name": name,
        "auth_mode": p.auth_mode,
        "backend": p.backend,
        "base_url": p.base_url,
        "model": p.model,
        "enabled": p.enabled,
        "runner": p.runner,
        "color": p.color,
        "key_last4": None if p.auth_mode == "cli" else secrets.last4(name),
        "status": _status(name, p),
    }


def _transcript_state() -> dict:
    try:
        path = T.current()
    except FileNotFoundError:
        return {"active": False}
    return {"active": True, "title": T.title(path), "path": str(path), "turns": T.load(path)}


# ---- modes ------------------------------------------------------------------
@app.post("/research")
def post_research(body: ResearchBody) -> dict:
    if not body.prompt.strip():
        raise HTTPException(400, "prompt required")
    with _lock:
        try:
            synthesis = modes.research(body.prompt, effort=body.effort)
        except FileNotFoundError as e:
            raise HTTPException(400, str(e)) from e        # no active transcript
        except RuntimeError as e:
            raise HTTPException(502, str(e)) from e         # every panelist down
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"{type(e).__name__}: {e}") from e
    return {"synthesis": synthesis, "transcript": _transcript_state()}


@app.post("/converse")
def post_converse(body: ConverseBody) -> dict:
    if not body.prompt.strip():
        raise HTTPException(400, "prompt required")
    with _lock:
        try:
            reply = modes.converse(body.prompt, addressed_to=body.addressed_to)
        except (FileNotFoundError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:  # noqa: BLE001 — addressed model down/unauthed
            raise HTTPException(502, f"{type(e).__name__}: {e}") from e
    return {"reply": reply, "transcript": _transcript_state()}


# ---- transcript -------------------------------------------------------------
@app.get("/participants")
def get_participants() -> dict:
    """Speaker colours + addressee list for the UI. No secrets — not guarded."""
    return {"participants": [
        {"name": k, "color": p.color, "enabled": p.enabled, "auth_mode": p.auth_mode}
        for k, p in providers.registry().items()
    ], "research_judge": providers.research_judge()}


@app.get("/transcript")
def get_transcript() -> dict:
    return _transcript_state()


@app.get("/transcripts")
def list_transcripts() -> dict:
    settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)
    items = [{"path": str(f), "title": T.title(f), "mtime": f.stat().st_mtime}
             for f in sorted(settings.VAULT_DIR.glob("*.jsonl"),
                             key=lambda p: p.stat().st_mtime, reverse=True)]
    return {"transcripts": items}


@app.post("/transcript")
def new_transcript(body: NewBody) -> dict:
    if not body.title.strip():
        raise HTTPException(400, "title required")
    with _lock:
        T.new(body.title)
    return _transcript_state()


@app.post("/transcript/select")
def select_transcript(body: SelectBody) -> dict:
    path = Path(body.path)
    if path.resolve().parent != settings.VAULT_DIR.resolve() or not path.is_file():
        raise HTTPException(400, f"not a vault transcript: {path}")
    with _lock:
        T.set_current(path)
    return _transcript_state()


# ---- providers (localhost-only; keys write-only) ----------------------------
@app.get("/providers", dependencies=[Depends(localhost_only)])
def get_providers() -> dict:
    return {
        "providers": [_provider_view(k, p) for k, p in providers.registry().items()],
        "research_judge": providers.research_judge(),
    }


@app.post("/providers", dependencies=[Depends(localhost_only)])
def create_provider(body: ProviderCreate) -> dict:
    if not body.name.strip() or not body.base_url.strip():
        raise HTTPException(400, "name and base_url required")
    with _lock:
        key = providers.create_provider(body.name, body.base_url, body.model,
                                        auth_mode=body.auth_mode, backend=body.backend)
        if body.api_key:
            secrets.set(key, body.api_key)
    return _provider_view(key, providers.provider(key))


@app.delete("/providers/{name}", dependencies=[Depends(localhost_only)])
def remove_provider(name: str) -> dict:
    with _lock:
        try:
            providers.delete_provider(name)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        _last_test.pop(name, None)
    return {"deleted": name}


@app.put("/providers/{name}", dependencies=[Depends(localhost_only)])
def put_provider(name: str, body: ProviderUpdate) -> dict:
    with _lock:
        try:
            providers.update_provider(
                name, base_url=body.base_url, model=body.model,
                enabled=body.enabled, auth_mode=body.auth_mode)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        if body.api_key is not None:           # write-only; "" clears
            secrets.set(name, body.api_key or None)
            _last_test.pop(name, None)
    return _provider_view(name, providers.provider(name))


@app.post("/providers/{name}/test", dependencies=[Depends(localhost_only)])
def test_provider(name: str) -> dict:
    try:
        providers.provider(name)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    result = providers.test_provider(name)     # never raises; key-redacted
    _last_test[name] = result
    return result


@app.get("/providers/{name}/models", dependencies=[Depends(localhost_only)])
def provider_models(name: str) -> dict:
    try:
        providers.provider(name)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    try:
        return {"models": providers.list_models(name)}
    except Exception as e:  # noqa: BLE001 — already key-redacted; UI falls back to typed id
        raise HTTPException(502, str(e)) from e


@app.put("/research-judge", dependencies=[Depends(localhost_only)])
def put_judge(body: JudgeBody) -> dict:
    with _lock:
        try:
            providers.set_judge(body.name)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
    return {"research_judge": providers.research_judge()}


# ---- static SPA (Phase 6) ---------------------------------------------------
@app.get("/")
def index():
    idx = STATIC_DIR / "index.html"
    if idx.is_file():
        return FileResponse(idx)
    return {"ok": True, "note": "engine up; UI lands in Phase 6"}


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main() -> None:
    import uvicorn
    host = os.environ.get("RESEARCH_ROOM_HOST", "127.0.0.1")   # localhost only
    port = int(os.environ.get("RESEARCH_ROOM_PORT", "8765"))
    print(f"research room → http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
