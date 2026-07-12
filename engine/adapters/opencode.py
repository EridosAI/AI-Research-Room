"""opencode.py — OpenCode serve adapter (Phase 39).

Session lifecycle per room-seat:
  start_serve(room_id) → opencode serve --cwd workspace_path
  attach_or_create_session → POST /session
  chat(turn) → POST /session/{id}/message + SSE /event → on_delta
  interrupt() → POST /session/{id}/abort (+ /api/.../interrupt)

Workspace enforcement is structural: serve is launched with cwd = workspace_path
(native ext4). Engine stays on /mnt/c; only agent edits hit the fast FS.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# generous read for long agent turns; connect stays tight
_HTTP_TIMEOUT = 30
_SERVE_READY_S = 20
_DEFAULT_MODEL = {
    "providerID": "openrouter",
    "modelID": "deepseek/deepseek-v4-flash",
}


@dataclass
class ServeHandle:
    room_id: str
    workspace: Path
    port: int
    proc: subprocess.Popen | None
    session_id: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_handles: dict[str, ServeHandle] = {}
_handles_guard = threading.Lock()

# test seam: when set, chat() never touches the network
_MOCK_CHAT: Callable | None = None


def _base(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _req(method: str, url: str, body: dict | None = None,
         timeout: float = _HTTP_TIMEOUT) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    r = Request(url, data=data, method=method,
                headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urlopen(r, timeout=timeout) as resp:
        raw = resp.read()
        if not raw:
            return None
        return json.loads(raw)


def _healthy(port: int) -> bool:
    try:
        r = _req("GET", f"{_base(port)}/global/health", timeout=2)
        return bool(r and r.get("healthy"))
    except Exception:  # noqa: BLE001
        return False


def default_workspace(room_id: str) -> Path:
    home = Path(os.environ.get("HOME") or Path.home())
    return home / "rooms" / room_id / "workspace"


def ensure_workspace(room_id: str, workspace_path: str | None = None) -> Path:
    """mkdir -p workspace; git init if absent; write minimal AGENTS.md if missing."""
    from .. import rooms
    room = rooms.load_room(room_id)
    raw = workspace_path if workspace_path is not None else room.get("workspace_path")
    if not raw:
        raw = str(default_workspace(room_id))
        try:
            rooms.update_room(room_id, workspace_path=raw)
        except ValueError:
            pass
    ws = Path(raw).expanduser().resolve()
    ws.mkdir(parents=True, exist_ok=True)
    if not (ws / ".git").exists():
        subprocess.run(["git", "init"], cwd=ws, capture_output=True, check=False)
    agents = ws / "AGENTS.md"
    if not agents.is_file():
        agents.write_text(_AGENTS_MD, encoding="utf-8")
    # project opencode.json: permissions + fusion channel MCP (stdio)
    oc = ws / "opencode.json"
    if not oc.is_file():
        mcp_cmd = _channel_mcp_command(room_id)
        oc.write_text(json.dumps({
            "$schema": "https://opencode.ai/config.json",
            "mcp": {
                "fusion": {
                    "type": "local",
                    "command": mcp_cmd,
                    "enabled": True,
                }
            },
            "permission": {
                "bash": "allow",
                "edit": "allow",
                "webfetch": "allow",
            },
        }, indent=2), encoding="utf-8")
    return ws


def _channel_mcp_command(room_id: str) -> list[str]:
    """stdio MCP launcher for the diplomatic channel tools."""
    repo = Path(__file__).resolve().parents[2]
    py = shutil.which("python3") or "python3"
    script = str(repo / "engine" / "channel_mcp.py")
    return [py, script, room_id]


def _pick_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_serve(room_id: str, workspace: Path | None = None) -> ServeHandle:
    """Launch `opencode serve` with cwd = workspace (native FS). One process per room."""
    ws = workspace or ensure_workspace(room_id)
    with _handles_guard:
        existing = _handles.get(room_id)
        if existing and existing.proc and existing.proc.poll() is None and _healthy(existing.port):
            return existing
        if existing and existing.proc and existing.proc.poll() is None:
            try:
                existing.proc.terminate()
            except Exception:  # noqa: BLE001
                pass

    port = _pick_port()
    env = os.environ.copy()
    # non-interactive: OpenRouter key already in env for the service user
    log_path = ws / ".opencode-serve.log"
    logf = open(log_path, "ab", buffering=0)  # noqa: SIM115 — owned by process lifetime
    proc = subprocess.Popen(
        ["opencode", "serve", "--port", str(port), "--hostname", "127.0.0.1"],
        cwd=str(ws), env=env, stdout=logf, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    deadline = time.time() + _SERVE_READY_S
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"opencode serve exited early (code {proc.returncode}); see {log_path}")
        if _healthy(port):
            break
        time.sleep(0.2)
    else:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"opencode serve not healthy on :{port} within {_SERVE_READY_S}s")

    h = ServeHandle(room_id=room_id, workspace=ws, port=port, proc=proc)
    with _handles_guard:
        _handles[room_id] = h
    # persist port for re-attach
    try:
        from .. import rooms
        rooms.update_room(room_id, opencode_port=port)
    except Exception:  # noqa: BLE001
        pass
    return h


def attach_or_create_session(room_id: str, *, model: dict | None = None) -> ServeHandle:
    """Ensure serve + session. Re-uses healthy port/session from room.json when possible."""
    from .. import rooms
    room = rooms.load_room(room_id)
    ws = ensure_workspace(room_id, room.get("workspace_path") or None)

    port = room.get("opencode_port")
    sid = room.get("opencode_session_id")
    if port and _healthy(int(port)):
        h = ServeHandle(room_id=room_id, workspace=ws, port=int(port), proc=None, session_id=sid)
        if sid:
            try:
                _req("GET", f"{_base(h.port)}/session/{sid}", timeout=5)
                with _handles_guard:
                    _handles[room_id] = h
                return h
            except Exception:  # noqa: BLE001
                sid = None
        # healthy serve, no session → create
        sess = _req("POST", f"{_base(h.port)}/session", {})
        h.session_id = sess.get("id")
        rooms.update_room(room_id, opencode_session_id=h.session_id, opencode_port=h.port)
        with _handles_guard:
            _handles[room_id] = h
        return h

    h = start_serve(room_id, ws)
    sess = _req("POST", f"{_base(h.port)}/session", {})
    h.session_id = sess.get("id")
    rooms.update_room(room_id, opencode_session_id=h.session_id, opencode_port=h.port)
    return h


def interrupt(room_id: str) -> None:
    """Cancel an in-flight OpenCode turn + wake channel waiters."""
    from .. import channel
    channel.cancel_pending(room_id, reason="interrupted")
    with _handles_guard:
        h = _handles.get(room_id)
    if not h or not h.session_id:
        return
    for path in (
        f"/session/{h.session_id}/abort",
        f"/api/session/{h.session_id}/interrupt",
    ):
        try:
            _req("POST", f"{_base(h.port)}{path}", {})
            return
        except Exception:  # noqa: BLE001
            continue


def _parse_model(p) -> dict:
    """Provider.model may be 'provider/model' or bare model id."""
    m = (getattr(p, "model", None) or "").strip()
    if "/" in m:
        prov, mid = m.split("/", 1)
        return {"providerID": prov, "modelID": mid}
    if m:
        return {"providerID": "openrouter", "modelID": m}
    return dict(_DEFAULT_MODEL)


def _payload_to_prompt(payload: dict) -> str:
    """Flatten Fusion payload into a single user message for the agent turn."""
    parts = []
    sys = (payload.get("system") or "").strip()
    if sys:
        parts.append(f"[system]\n{sys}")
    for m in payload.get("messages") or []:
        role = m.get("role") or "user"
        content = m.get("content") or ""
        parts.append(f"[{role}]\n{content}")
    return "\n\n".join(parts).strip() or "(empty)"


def _usage_from_session(port: int, sid: str) -> dict:
    try:
        sess = _req("GET", f"{_base(port)}/session/{sid}", timeout=10)
    except Exception:  # noqa: BLE001
        return {"input": 0, "output": 0, "exact": False}
    tokens = sess.get("tokens") or {}
    return {
        "input": int(tokens.get("input") or 0),
        "output": int(tokens.get("output") or 0),
        "reasoning": int(tokens.get("reasoning") or 0),
        "cost": sess.get("cost"),
        "exact": True,
    }


def chat(provider, payload: dict, *, room_id: str,
         on_delta: Callable | None = None,
         abort: threading.Event | None = None) -> tuple[str, dict]:
    """Drive ONE OpenCode message; bridge SSE deltas → on_delta; return (text, usage).

    Window mode: one forward answer per turn. Heartbeat/tool/delta frames keep the
    stream alive during long parks (R2).
    """
    if _MOCK_CHAT is not None:
        return _MOCK_CHAT(provider, payload, room_id=room_id, on_delta=on_delta, abort=abort)

    h = attach_or_create_session(room_id)
    assert h.session_id
    prompt = _payload_to_prompt(payload)
    model = _parse_model(provider)

    # SSE listener: collect text + forward deltas/heartbeats
    text_parts: list[str] = []
    seen_text = ""
    idle = threading.Event()
    err_box: list[BaseException] = []

    def sse_loop():
        nonlocal seen_text
        try:
            r = Request(f"{_base(h.port)}/event")
            with urlopen(r, timeout=600) as resp:
                for raw in resp:
                    if abort is not None and abort.is_set():
                        break
                    if idle.is_set():
                        break
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    try:
                        ev = json.loads(line[5:].strip())
                    except Exception:  # noqa: BLE001
                        continue
                    typ = ev.get("type") or ""
                    props = ev.get("properties") or {}
                    if typ == "server.heartbeat":
                        if on_delta is not None:
                            try:
                                on_delta("")   # keep Fusion SSE alive (R2)
                            except Exception:  # noqa: BLE001 — abort raises
                                idle.set()
                                return
                        continue
                    if typ == "message.part.delta":
                        delta = props.get("delta") or props.get("text") or ""
                        if delta and on_delta is not None:
                            try:
                                on_delta(delta)
                            except Exception:  # noqa: BLE001
                                idle.set()
                                return
                        if delta:
                            text_parts.append(delta)
                        continue
                    if typ == "message.part.updated":
                        part = props.get("part") or {}
                        if part.get("type") == "text":
                            full = part.get("text") or ""
                            if full and full != seen_text:
                                # emit only the growth when delta frames were missing
                                if full.startswith(seen_text):
                                    chunk = full[len(seen_text):]
                                    if chunk and on_delta is not None and not text_parts:
                                        try:
                                            on_delta(chunk)
                                        except Exception:  # noqa: BLE001
                                            idle.set()
                                            return
                                seen_text = full
                        continue
                    if typ == "session.idle":
                        idle.set()
                        return
        except Exception as e:  # noqa: BLE001
            err_box.append(e)
            idle.set()

    th = threading.Thread(target=sse_loop, daemon=True)
    th.start()
    time.sleep(0.3)  # let the SSE connect before the message

    body = {"parts": [{"type": "text", "text": prompt}], "model": model}
    try:
        resp = _req("POST", f"{_base(h.port)}/session/{h.session_id}/message", body, timeout=600)
    except HTTPError as e:
        idle.set()
        raise RuntimeError(f"opencode message failed: HTTP {e.code}") from e
    except URLError as e:
        idle.set()
        raise RuntimeError(f"opencode message failed: {e}") from e

    # wait for idle (or abort)
    deadline = time.time() + 600
    while not idle.is_set() and time.time() < deadline:
        if abort is not None and abort.is_set():
            interrupt(room_id)
            break
        time.sleep(0.2)
    idle.set()

    # final text: prefer streamed parts; fall back to response body
    text = "".join(text_parts) or seen_text
    if not text and isinstance(resp, dict):
        for p in resp.get("parts") or []:
            if p.get("type") == "text":
                text += p.get("text") or ""
    usage = _usage_from_session(h.port, h.session_id)
    if err_box and not text:
        raise RuntimeError(f"opencode SSE error: {err_box[0]}")
    return text.strip(), usage


def park_on_blocking_mcp(room_id: str) -> None:
    """No-op marker: OpenCode parks naturally on blocking MCP tools (bake-off)."""
    return None


def get_handle(room_id: str) -> ServeHandle | None:
    with _handles_guard:
        return _handles.get(room_id)


def shutdown(room_id: str) -> None:
    with _handles_guard:
        h = _handles.pop(room_id, None)
    if h and h.proc and h.proc.poll() is None:
        try:
            h.proc.terminate()
        except Exception:  # noqa: BLE001
            pass


_AGENTS_MD = """# AGENTS.md — code seat contract

This seat operates under the invariants in CLAUDE.md. Key rules restated below for every turn.

- Bright line = forward context exactly (never include raw panelist turns unless meta.is_panelist_raw).
- Origin colour: stroke = voice of last speaker.
- Guard-layer injection is the only way to reach the model.
- Any crossing into main transcript goes through outbox/approval.
- Workspace edits only inside the assigned native-Linux workspace_path.
- Testing discipline: falsifiable fixtures + discriminating mutations for anything you write.
- "Report only, change nothing" on recon tasks.
- Use the 5 MCP diplomatic tools for communication with main chat:
  comment_to_main, query_main_state, ask_design_question, workspace_status, request_compaction.

See the repo-root CLAUDE.md for complete discipline + paint conventions.
"""
