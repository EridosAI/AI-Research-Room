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

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from engine import artifacts, export_md, margin, modes, providers, rooms, secrets, settings
from engine import transcript as T

app = FastAPI(title="research room")
STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.middleware("http")
async def _no_store_spa(request, call_next):
    """Never let the browser cache the SPA. The static assets otherwise ship with
    an ETag + Last-Modified but no Cache-Control, so browsers apply heuristic
    freshness and can serve a STALE app.js after an update — which silently breaks
    the UI (e.g. a cached page calling a since-removed endpoint). Localhost, tiny
    files: correctness over caching."""
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp

# _lock serializes app-global config writes (the provider registry). Per-ROOM
# work uses per-room locks instead, so a slow research round in room A never
# blocks a converse in room B — the concurrency model that makes multi-room real.
_lock = threading.Lock()
_room_locks: dict[str, threading.Lock] = {}
_margin_locks: dict[str, threading.Lock] = {}
_meta_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_last_test: dict[str, dict] = {}   # in-memory last test result per provider


def _room_lock(room_id: str) -> threading.Lock:
    """Serializes writers of a room's main.jsonl (research / converse / promote).
    Held for the full duration of a model call — so it must NOT guard quick ops
    like switching to the room or editing its settings (see _meta_lock)."""
    with _locks_guard:
        lk = _room_locks.get(room_id)
        if lk is None:
            lk = _room_locks[room_id] = threading.Lock()
        return lk


def _meta_lock(room_id: str) -> threading.Lock:
    """Serializes quick room.json writes (activate/mark-read, settings PUT). Kept
    SEPARATE from the main lock so switching to a room — or changing its settings —
    never blocks behind a slow research/converse round running in that same room."""
    with _locks_guard:
        lk = _meta_locks.get(room_id)
        if lk is None:
            lk = _meta_locks[room_id] = threading.Lock()
        return lk


def _margin_lock(room_id: str) -> threading.Lock:
    """A SEPARATE lock from the main per-room lock. A margin question reads main
    and writes only margin.jsonl — no conflict with a main round — so it must not
    queue behind a slow research round in the same room (that would kill the
    'understand this while the big thing runs' use case)."""
    with _locks_guard:
        lk = _margin_locks.get(room_id)
        if lk is None:
            lk = _margin_locks[room_id] = threading.Lock()
        return lk


# ---- request bodies ---------------------------------------------------------
class ResearchBody(BaseModel):
    prompt: str
    effort: str = "medium"
    panel: list[str] | None = None   # per-round model selection; None = all enabled
    judge: str | None = None         # per-round judge override; None = global research_judge


class ConverseBody(BaseModel):
    prompt: str
    addressed_to: str | None = None


class RoomCreate(BaseModel):
    title: str


class RoomUpdate(BaseModel):
    title: str | None = None
    participants: list[str] | None = None
    judge: str | None = None
    margin_model: str | None = None
    splitter_width: float | None = None
    last_read_pos: int | None = None
    tags: list[str] | None = None
    reasoning_effort: dict | None = None   # {panelist_key: "high"|"medium"|"low"} per-room overrides


class UIBody(BaseModel):
    sidebar_collapsed: bool | None = None
    sidebar_width: float | None = None
    composer_height: float | None = None   # dragged transcript↔composer split (px)
    export_dir: str | None = None   # Obsidian export folder; "" = off
    accent_hue: float | None = None   # theme accent hue (oklch degrees)
    theme_mode: str | None = None     # dark | light | system
    text_brightness: str | None = None   # soft | default | crisp
    font_scale: str | None = None        # compact | default | large
    display_name: str | None = None      # how the app addresses you; "" = human
    show_token_estimate: bool | None = None   # token-chip: ~X / Y fill piece
    show_model_pct: bool | None = None        # token-chip: per-model spend share
    artifacts_dir: str | None = None          # where to auto-write markdown artifacts; "" = off


class FileItem(BaseModel):
    filename: str
    content: str


class FilesBody(BaseModel):
    files: list[FileItem]   # staged .md/.txt; each becomes a file-turn (no model call)


class MarginBody(BaseModel):
    prompt: str
    window: str = "last_3"
    model: str | None = None


class ArtifactBody(BaseModel):
    content: str


class ProviderCreate(BaseModel):
    name: str
    base_url: str
    model: str = ""
    auth_mode: str = "api"
    backend: str = "openai"
    api_key: str | None = None   # write-only
    context_window: int | None = None   # seeded from the OR model dropdown (fill gauge window)
    reasoning: bool | None = None        # seeded from the OR model dropdown (reasoning-capable)


class ProviderUpdate(BaseModel):
    base_url: str | None = None
    model: str | None = None
    enabled: bool | None = None
    auth_mode: str | None = None
    reasoning: bool | None = None
    web_search: bool | None = None
    context_window: int | None = None
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


def _effort_options(p: providers.Provider) -> list[str] | None:
    """Reasoning-effort choices for the model-square selector (ASCENDING), per-model
    from OpenRouter's /models metadata (config override wins). None → no selector
    (proxy-Grok / direct / non-reasoning rows)."""
    return providers.effort_options(p)


def _window_view(p: providers.Provider) -> dict:
    """The context gauge's window facts for the UI: the effective routed window the ring
    calibrates to, the headline window, and the reduced/changed flags (Phase 24).
    Best-effort — never let a metadata lookup fail the participants list."""
    try:
        w = providers.window_info(p)
    except Exception:  # noqa: BLE001
        w = {"effective": p.context_window or 0, "headline": None, "reduced": False, "changed": False}
    return {"effective_window": w["effective"], "headline_window": w["headline"],
            "window_reduced": w["reduced"], "window_changed": w["changed"]}


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
        "reasoning": p.reasoning,
        "web_search": p.web_search,
        "effort_options": _effort_options(p),
        "context_window": p.context_window,
        "key_last4": None if p.auth_mode == "cli" else secrets.last4(name),
        "status": _status(name, p),
    }


# ---- active-room pointer ----------------------------------------------------
# The client's active room id lives in settings.CURRENT_PTR (a UI convenience).
# The engine itself is stateless about which room is current — every /rooms
# endpoint takes an explicit id; this just remembers the one on screen so a
# reload restores it.
def _active_room_id() -> str | None:
    try:
        rid = settings.CURRENT_PTR.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        rid = ""
    return rid if rid and rooms.room_exists(rid) else None


def _set_active(room_id: str) -> None:
    settings.ROOMS_DIR.mkdir(parents=True, exist_ok=True)
    settings.CURRENT_PTR.write_text(room_id, encoding="utf-8")


# ---- room views + app-level UI state ----------------------------------------
def _preview(turns: list[dict]) -> str:
    """Cheap room summary (no model call): the latest model answer's first line,
    else the first human prompt's first line, truncated."""
    pick = next((t for t in reversed(turns) if t.get("role") in ("judge", "ai")), None) \
        or next((t for t in turns if t.get("role") == "human"), None)
    if not pick:
        return ""
    first = (pick.get("text") or "").strip().splitlines()
    return (first[0][:160] if first else "")


def _room_view(meta: dict, turns: list[dict] | None = None) -> dict:
    """Per-room summary for the sidebar. `unread` flags a room whose transcript
    grew past what was last read (the background-activity dot)."""
    rid = meta["id"]
    if turns is None:
        turns = T.load(rooms.main_path(rid))
    last_read = meta.get("last_read_pos") or 0
    return {
        "id": rid,
        "title": meta["title"],
        "participants": meta.get("participants", []),
        "judge": meta.get("judge"),
        "margin_model": meta.get("margin_model"),
        "splitter_width": meta.get("splitter_width"),
        "tags": meta.get("tags", []),
        "reasoning_effort": meta.get("reasoning_effort", {}),
        "last_read_pos": last_read,
        "turn_count": len(turns),
        "unread": len(turns) > last_read,
        "mtime": meta.get("mtime"),
        "created": meta.get("ts"),                                  # room start
        "last_ts": (turns[-1].get("ts") if turns else meta.get("ts")),
        "preview": _preview(turns),                                 # cheap, no model call
    }


def _full_room(room_id: str) -> dict:
    meta = rooms.load_room(room_id)
    turns = T.load(rooms.main_path(room_id))
    view = _room_view(meta, turns)
    view["turns"] = turns
    view["margin_turns"] = T.load(rooms.margin_path(room_id))
    view["active"] = True
    return view


def _require_room(room_id: str) -> None:
    if not rooms.room_exists(room_id):
        raise HTTPException(404, f"no such room: {room_id}")


def _maybe_export(room_id: str) -> None:
    """Best-effort Obsidian export after a turn lands. Unset export_dir → skip;
    any failure is swallowed so it can NEVER fail the turn that just succeeded."""
    try:
        export_md.export_room(room_id, _load_ui().get("export_dir"))
    except Exception:  # noqa: BLE001 — export is a side-effect, never load-bearing
        pass


def _maybe_artifacts(room_id: str, text: str) -> None:
    """Best-effort auto-write of any ```markdown blocks in a model's answer. Unset
    artifacts_dir → skip; failures swallowed (never fail the turn). Manual save +
    copy in the UI work regardless."""
    try:
        artifacts.auto_write(room_id, text, _load_ui().get("artifacts_dir"))
    except Exception:  # noqa: BLE001
        pass


_UI_DEFAULT = {"sidebar_collapsed": False, "sidebar_width": 260, "composer_height": None,
               "export_dir": "",
               "accent_hue": 233,            # navy default
               "theme_mode": "dark",         # dark (default) | light | system
               "text_brightness": "default", "font_scale": "default", "display_name": "",
               "show_token_estimate": True, "show_model_pct": False, "artifacts_dir": ""}


def _load_ui() -> dict:
    try:
        data = json.loads(settings.UI_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        data = {}
    return {**_UI_DEFAULT, **(data if isinstance(data, dict) else {})}


def _save_ui(patch: dict) -> dict:
    ui = {**_load_ui(), **patch}
    settings.UI_FILE.parent.mkdir(parents=True, exist_ok=True)
    settings.UI_FILE.write_text(json.dumps(ui, indent=2), encoding="utf-8")
    return ui


# ---- participants -----------------------------------------------------------
@app.get("/participants")
def get_participants() -> dict:
    """Speaker colours + addressee list for the UI. No secrets — not guarded."""
    return {"participants": [
        {"name": k, "color": p.color, "enabled": p.enabled, "auth_mode": p.auth_mode,
         "model": p.model, "base_url": p.base_url,
         "context_window": p.context_window, "effort_options": _effort_options(p),
         **_window_view(p)}
        for k, p in providers.registry().items()
    ], "research_judge": providers.research_judge()}


# ---- rooms (first-class) ----------------------------------------------------
@app.get("/rooms")
def get_rooms() -> dict:
    """All rooms (newest first) + which is active. Each carries an `unread` flag
    for the background-activity dot. Reconstructed from disk — no browser state."""
    return {"rooms": [_room_view(m) for m in rooms.list_rooms()],
            "active": _active_room_id()}


@app.post("/rooms")
def make_room(body: RoomCreate) -> dict:
    """Create a room with the EMPTY/forced-decision default (no participants, no
    judge) and make it active. The UI must gather a roster + judge before research."""
    if not body.title.strip():
        raise HTTPException(400, "title required")
    with _lock:
        rid = rooms.create_room(body.title)
        _set_active(rid)
    return {"room": _full_room(rid), "active": rid}


@app.get("/rooms/{room_id}")
def get_room(room_id: str) -> dict:
    """Pure read of a room's transcript + state (no mutation — used for reload
    and to inspect a background room without marking it read/active)."""
    _require_room(room_id)
    return _full_room(room_id)


@app.post("/rooms/{room_id}/activate")
def activate_room(room_id: str) -> dict:
    """Switch to a room: make it active and mark it read (clears its dot). Uses the
    META lock, not the main lock, so you can switch INTO a room whose research round
    is still in flight (the bug: it used to block behind the round)."""
    _require_room(room_id)
    with _meta_lock(room_id):
        _set_active(room_id)
        turns = T.load(rooms.main_path(room_id))
        rooms.update_room(room_id, last_read_pos=len(turns))
    return _full_room(room_id)


@app.put("/rooms/{room_id}")
def put_room(room_id: str, body: RoomUpdate) -> dict:
    _require_room(room_id)
    fields = {k: v for k, v in body.dict().items() if v is not None}
    if "participants" in fields:
        unknown = [p for p in fields["participants"] if p not in providers.registry()]
        if unknown:
            raise HTTPException(400, f"unknown providers: {', '.join(unknown)}")
    if "judge" in fields and fields["judge"] not in providers.registry():
        raise HTTPException(400, f"unknown judge: {fields['judge']}")
    # room.json write → meta lock (never blocks behind an in-flight round).
    with _meta_lock(room_id):
        meta = rooms.update_room(room_id, **fields)
    return _room_view(meta)


@app.post("/rooms/{room_id}/research")
def room_research(room_id: str, body: ResearchBody) -> dict:
    _require_room(room_id)
    if not body.prompt.strip():
        raise HTTPException(400, "prompt required")
    if body.panel is not None:
        unknown = [p for p in body.panel if p not in providers.registry()]
        if unknown:
            raise HTTPException(400, f"unknown providers: {', '.join(unknown)}")
        if not body.panel:
            raise HTTPException(400, "select at least one model for the research panel")
    if body.judge is not None and body.judge not in providers.registry():
        raise HTTPException(400, f"unknown judge: {body.judge}")
    with _room_lock(room_id):
        try:
            synthesis = modes.research(room_id, body.prompt, panel=body.panel,
                                       judge=body.judge, effort=body.effort)
        except (FileNotFoundError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        except RuntimeError as e:
            raise HTTPException(502, str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"{type(e).__name__}: {e}") from e
        view = _full_room(room_id)
    _maybe_export(room_id)
    _maybe_artifacts(room_id, synthesis)
    # room_id lets the client decide whether this belongs on the active screen.
    return {"synthesis": synthesis, "room_id": room_id, "transcript": view}


@app.post("/rooms/{room_id}/converse")
def room_converse(room_id: str, body: ConverseBody) -> dict:
    _require_room(room_id)
    if not body.prompt.strip():
        raise HTTPException(400, "prompt required")
    with _room_lock(room_id):
        try:
            reply = modes.converse(room_id, body.prompt, addressed_to=body.addressed_to,
                                    human_label=(_load_ui().get("display_name") or "human"))
        except (FileNotFoundError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"{type(e).__name__}: {e}") from e
        view = _full_room(room_id)
    _maybe_export(room_id)
    _maybe_artifacts(room_id, reply)
    return {"reply": reply, "room_id": room_id, "transcript": view}


# ---- attached files (Phase 22) ----------------------------------------------
@app.post("/rooms/{room_id}/files")
def post_files(room_id: str, body: FilesBody) -> dict:
    """Append staged .md/.txt files as file-turns (no model call) — the content rides
    turn.text into forward context. Emitted BEFORE the message turn the client sends
    next, so the panel reads 'here's the document, now my question'. Empty-message
    sends (files only) are allowed: the client just doesn't follow with research/
    converse. Takes the MAIN room lock — it's a main.jsonl write."""
    _require_room(room_id)
    if not body.files:
        raise HTTPException(400, "no files")
    with _room_lock(room_id):
        try:
            for f in body.files:
                modes.attach_file(room_id, f.filename, f.content)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        view = _full_room(room_id)
    _maybe_export(room_id)
    return {"room_id": room_id, "transcript": view}


# ---- margin (the in-room side-channel; Phase 10) ----------------------------
@app.post("/rooms/{room_id}/margin")
def post_margin(room_id: str, body: MarginBody) -> dict:
    _require_room(room_id)
    if not body.prompt.strip():
        raise HTTPException(400, "prompt required")
    if body.model is not None and body.model not in providers.registry():
        raise HTTPException(400, f"unknown margin model: {body.model}")
    # NOTE: margin lock, NOT the main room lock — runs concurrently with a main round.
    with _margin_lock(room_id):
        try:
            answer = margin.margin_turn(room_id, body.prompt,
                                        window=body.window, model=body.model)
        except (FileNotFoundError, ValueError) as e:
            raise HTTPException(400, str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"{type(e).__name__}: {e}") from e
        m = T.load(rooms.margin_path(room_id))
    return {"answer": answer, "room_id": room_id, "margin_turns": m}


@app.post("/rooms/{room_id}/margin/{turn_id}/promote")
def promote_margin(room_id: str, turn_id: str) -> dict:
    """Copy one margin answer into main — an explicit MAIN write, so it takes the
    main room lock (it must serialize with main rounds, unlike asking the margin)."""
    _require_room(room_id)
    with _room_lock(room_id):
        try:
            note = margin.promote(room_id, turn_id)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        view = _full_room(room_id)
    _maybe_export(room_id)
    return {"promoted": note, "room_id": room_id, "transcript": view}


# ---- markdown artifacts (Phase 14D) -----------------------------------------
@app.post("/rooms/{room_id}/artifact")
def save_artifact(room_id: str, body: ArtifactBody) -> dict:
    """Manually save one markdown artifact to the artifacts dir. Copy works without
    a dir (client-side); this save needs one set."""
    _require_room(room_id)
    if not body.content.strip():
        raise HTTPException(400, "empty artifact")
    adir = _load_ui().get("artifacts_dir")
    if not adir or not str(adir).strip():
        raise HTTPException(400, "no artifacts directory set (Settings → Data)")
    try:
        path = artifacts.save_artifact(room_id, body.content, adir)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"{type(e).__name__}: {e}") from e
    return {"path": str(path)}


# ---- app-level UI state (server-side; honours the no-localStorage rule) ------
@app.get("/ui")
def get_ui() -> dict:
    return _load_ui()


@app.put("/ui")
def put_ui(body: UIBody) -> dict:
    patch = {k: v for k, v in body.dict().items() if v is not None}
    with _lock:
        return _save_ui(patch)


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
                                        auth_mode=body.auth_mode, backend=body.backend,
                                        context_window=body.context_window, reasoning=body.reasoning)
        if body.api_key:
            secrets.set(key, body.api_key)
    return _provider_view(key, providers.provider(key))


@app.get("/or-models", dependencies=[Depends(localhost_only)])
def or_models() -> dict:
    """OpenRouter model catalog (id + context_length + reasoning + efforts) for the
    add-a-model dropdown. [] when no OR row has a key — the UI falls back to a typed id."""
    return {"models": providers.or_model_catalog()}


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
                enabled=body.enabled, auth_mode=body.auth_mode, reasoning=body.reasoning,
                web_search=body.web_search, context_window=body.context_window)
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


def open_browser(host: str, port: int, timeout: float = 30) -> None:
    """Open the UI in the default browser once the server is accepting connections.
    Opt-in (the `--open` flag) so headless/test runs stay browser-free. Polls the
    port rather than sleeping a fixed time (importing off /mnt/c can be slow)."""
    url = f"http://{host}:{port}"

    def _open() -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with socket.socket() as s:
                s.settimeout(0.5)
                if s.connect_ex((host, port)) == 0:
                    break
            time.sleep(0.3)
        try:
            if shutil.which("wslview"):
                subprocess.Popen(["wslview", url])
            elif shutil.which("explorer.exe"):
                subprocess.Popen(["explorer.exe", url])   # returns nonzero even on success
            else:
                import webbrowser
                webbrowser.open(url)
        except Exception as e:  # noqa: BLE001
            print(f"(auto-open failed: {e}) — open {url} yourself")

    threading.Thread(target=_open, daemon=True).start()


def main() -> None:
    import uvicorn
    host = os.environ.get("RESEARCH_ROOM_HOST", "127.0.0.1")   # localhost only
    port = int(os.environ.get("RESEARCH_ROOM_PORT", "8765"))
    print(f"research room → http://{host}:{port}")
    if "--open" in sys.argv:
        open_browser(host, port)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
