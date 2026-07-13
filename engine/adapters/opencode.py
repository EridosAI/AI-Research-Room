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
# OpenCode turns can run 10–20+ min (tools + thinking). POST /message blocks until
# the turn completes; SSE needs the same ceiling. 30 min matches a long Build.
_TURN_TIMEOUT_S = 1800
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
    # Always refresh seat contract so upgrades land in existing workspaces.
    agents.write_text(_AGENTS_MD, encoding="utf-8")
    # project opencode.json: permissions + fusion channel MCP (stdio).
    # Always refresh so vault env + room_id stay correct after room moves / upgrades.
    mcp_cmd = _channel_mcp_command(room_id)
    from .. import settings
    mcp_env = {
        "PYTHONPATH": str(settings.REPO_ROOT),
        "RESEARCH_ROOM_VAULT": str(settings.VAULT_DIR),
        "RESEARCH_ROOM_CONFIG": str(settings.CONFIG_TOML),
        "RESEARCH_ROOM_HOME": str(settings.CONFIG_DIR),
        "RESEARCH_ROOM_SECRETS": str(settings.SECRETS_FILE),
        "FUSION_MCP_LOG": "/tmp/fusion-channel-mcp.log",
        "FUSION_REPO": str(settings.REPO_ROOT),
    }
    oc = ws / "opencode.json"
    oc.write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "fusion": {
                "type": "local",
                "command": mcp_cmd,
                "enabled": True,
                "environment": mcp_env,
                # OpenCode default connect timeout is 30s; give cold starts headroom
                "timeout": 120000,
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
    """stdio MCP launcher for the diplomatic channel tools.

    Prefer a native-ext4 copy of channel_mcp.py under ~/fusion-mcp so OpenCode's
    30s MCP connect budget isn't burned on /mnt/c spawn. PYTHONPATH still points
    at the repo for engine.channel.
    """
    home = Path(os.environ.get("HOME") or Path.home())
    native_py = home / "fusion-mcp" / "channel_mcp.py"
    repo = Path(__file__).resolve().parents[2]
    # keep native copy in sync with repo
    src = repo / "engine" / "channel_mcp.py"
    try:
        native_py.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file() and (
            not native_py.is_file()
            or native_py.stat().st_mtime < src.stat().st_mtime
        ):
            native_py.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            native_py.chmod(0o755)
    except Exception:  # noqa: BLE001
        pass
    py = shutil.which("python3") or "/usr/bin/python3"
    if native_py.is_file():
        return [py, str(native_py), room_id]
    venv_py = repo / ".venv" / "bin" / "python"
    if venv_py.is_file():
        py = str(venv_py)
    return [py, str(src), room_id]


def _opencode_bin() -> str:
    """Resolve the opencode CLI for the service user.

    systemd's PATH is minimal (/usr/bin…) and does not include nvm. Prefer a known
    absolute path, then PATH, then common nvm locations.
    """
    env = os.environ.get("OPENCODE_BIN")
    if env and Path(env).is_file():
        return env
    found = shutil.which("opencode")
    if found:
        return found
    home = Path(os.environ.get("HOME") or Path.home())
    for cand in (
        home / ".nvm/versions/node/v20.20.0/bin/opencode",
        home / ".local/bin/opencode",
        Path("/usr/local/bin/opencode"),
    ):
        if cand.is_file() or cand.is_symlink():
            return str(cand)
    # last resort: let Popen raise FileNotFoundError with a clear name
    return "opencode"


def _openrouter_key() -> str | None:
    """Pull an OpenRouter-compatible key from Fusion secrets (never log it).

    OpenCode serve only auto-loads OPENROUTER_API_KEY from the environment —
    it does not read Fusion's secrets.json. Without this, every message 500s
    with UnknownError (0 credentials in opencode auth list).
    """
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    try:
        from .. import secrets
        # Prefer an OR-named seat; any key works (Jason's secrets share one OR key).
        for k in ("deepseek-v4-flash-or", "glm-5-2-or", "claude-or",
                  "chat-gpt-5-5-or", "deepseek", "openrouter"):
            v = secrets.get(k)
            if v:
                return v
        # last resort: first non-empty secret
        from .. import settings
        if settings.SECRETS_FILE.is_file():
            import json
            data = json.loads(settings.SECRETS_FILE.read_text(encoding="utf-8"))
            for v in (data or {}).values():
                if isinstance(v, str) and v.strip():
                    return v
    except Exception:  # noqa: BLE001
        pass
    return None


def _serve_env() -> dict:
    """Environment for `opencode serve` — PATH + auth keys OpenCode recognizes."""
    env = os.environ.copy()
    oc = _opencode_bin()
    oc_dir = str(Path(oc).resolve().parent)
    env["PATH"] = oc_dir + os.pathsep + env.get("PATH", "")
    key = _openrouter_key()
    if key:
        env["OPENROUTER_API_KEY"] = key
        # some OpenCode builds also accept these aliases
        env.setdefault("OPENAI_API_KEY", key)
    return env


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
    env = _serve_env()
    if not env.get("OPENROUTER_API_KEY"):
        raise RuntimeError(
            "no OpenRouter key for OpenCode — set OPENROUTER_API_KEY or add an "
            "OpenRouter seat key in ⚙ Providers / secrets.json")
    oc = _opencode_bin()
    log_path = ws / ".opencode-serve.log"
    logf = open(log_path, "ab", buffering=0)  # noqa: SIM115 — owned by process lifetime
    proc = subprocess.Popen(
        [oc, "serve", "--port", str(port), "--hostname", "127.0.0.1"],
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


def _mcp_status(port: int) -> str:
    """Return fusion MCP status string: connected|failed|disabled|unknown."""
    try:
        st = _req("GET", f"{_base(port)}/mcp", timeout=5) or {}
        return (st.get("fusion") or {}).get("status") or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _mcp_connected(port: int) -> bool:
    return _mcp_status(port) == "connected"


def _wait_mcp(port: int, *, tries: int = 40, delay: float = 0.25) -> bool:
    """Poll + reconnect until fusion MCP is connected (or tries exhausted)."""
    for i in range(tries):
        if _mcp_connected(port):
            return True
        if i % 4 == 1:  # reconnect periodically, not every tick
            try:
                _req("POST", f"{_base(port)}/mcp/fusion/connect", {})
            except Exception:  # noqa: BLE001
                pass
        time.sleep(delay)
    return _mcp_connected(port)


def attach_or_create_session(room_id: str, *, model: dict | None = None,
                             force_new: bool = False) -> ServeHandle:
    """Ensure serve + session with fusion MCP connected.

    Always rewrites workspace opencode.json (native MCP launcher). Prefers a
    healthy handle this process started. force_new only when MCP is missing or
    the caller insists — avoid thrashing a good session on every pane open.
    """
    from .. import rooms
    room = rooms.load_room(room_id)
    ws = ensure_workspace(room_id, room.get("workspace_path") or None)

    # Prefer a handle we started in this process (known good env + MCP config).
    with _handles_guard:
        owned = _handles.get(room_id)
    if owned and owned.proc and owned.proc.poll() is None and _healthy(owned.port):
        if force_new and not _mcp_connected(owned.port):
            # only force-kill when MCP is actually broken
            shutdown(room_id)
            owned = None
        elif owned:
            if not owned.session_id:
                sess = _req("POST", f"{_base(owned.port)}/session", {})
                owned.session_id = sess.get("id")
                rooms.update_room(room_id, opencode_session_id=owned.session_id,
                                  opencode_port=owned.port)
            _wait_mcp(owned.port, tries=12)
            return owned

    if force_new:
        shutdown(room_id)
        try:
            rooms.update_room(room_id, opencode_port=None, opencode_session_id=None)
        except Exception:  # noqa: BLE001
            pass
        room = rooms.load_room(room_id)

    # Re-use a healthy port from room.json only if fusion MCP is already connected
    # (avoids attaching to orphan keyless serves).
    port = room.get("opencode_port")
    sid = room.get("opencode_session_id")
    if port and _healthy(int(port)) and _mcp_connected(int(port)):
        h = ServeHandle(room_id=room_id, workspace=ws, port=int(port),
                        proc=None, session_id=sid)
        if not sid:
            sess = _req("POST", f"{_base(h.port)}/session", {})
            h.session_id = sess.get("id")
            rooms.update_room(room_id, opencode_session_id=h.session_id, opencode_port=h.port)
        with _handles_guard:
            _handles[room_id] = h
        return h

    # Stale / unconnected — clear and spawn fresh
    if room.get("opencode_port") or room.get("opencode_session_id"):
        try:
            rooms.update_room(room_id, opencode_port=None, opencode_session_id=None)
        except Exception:  # noqa: BLE001
            pass

    h = start_serve(room_id, ws)
    # OpenCode loads MCP async — wait up to ~10s before reporting status
    _wait_mcp(h.port, tries=40, delay=0.25)
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
    """Map a Fusion Provider to OpenCode's {providerID, modelID}.

    OpenRouter seats must use providerID=openrouter with the FULL model string as
    modelID (e.g. deepseek/deepseek-v4-pro). Splitting on '/' would send
    providerID=deepseek, which OpenCode has no credentials for → HTTP 500.
    """
    m = (getattr(p, "model", None) or "").strip()
    base = (getattr(p, "base_url", None) or "") or ""
    # Jason's registry is OpenRouter-first; treat OR base_url or vendor/slug as OR.
    if "openrouter.ai" in base or "/" in m or not m:
        mid = m or _DEFAULT_MODEL["modelID"]
        if mid.startswith("openrouter/"):
            mid = mid[len("openrouter/"):]
        return {"providerID": "openrouter", "modelID": mid}
    return {"providerID": "openrouter", "modelID": m}


def _payload_to_prompt(payload: dict) -> str:
    """User-facing prompt only. System goes in the OpenCode `system` field, not the body text.

    Never wrap as `[system]/…` / `[user]\\n…` — those markers were ending up in the
    streamed transcript when user-message parts were mirrored as deltas (39.3d).
    """
    parts = []
    for m in payload.get("messages") or []:
        content = (m.get("content") or "").strip()
        if content:
            parts.append(content)
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


# OpenCode primary agents (native): build executes tools; plan is read-only planning.
_AGENT_BY_MODE = {
    "build": "build",
    "plan": "plan",
    "ask": "plan",   # ask ≈ plan: answer without edits
}


def chat(provider, payload: dict, *, room_id: str,
         on_delta: Callable | None = None,
         abort: threading.Event | None = None,
         agent: str | None = None,
         variant: str | None = None) -> tuple[str, dict]:
    """Drive ONE OpenCode message; bridge SSE deltas → on_delta; return (text, usage).

    Window mode: one forward answer per turn. Heartbeat/tool/delta frames keep the
    stream alive during long parks (R2). `agent` selects OpenCode primary agent
    (build|plan); `variant` is reasoning effort when the model supports it.
    """
    if _MOCK_CHAT is not None:
        return _MOCK_CHAT(provider, payload, room_id=room_id, on_delta=on_delta,
                          abort=abort, agent=agent, variant=variant)

    h = attach_or_create_session(room_id)
    assert h.session_id
    prompt = _payload_to_prompt(payload)
    model = _parse_model(provider)
    agent_name = agent or "build"

    # SSE listener: collect ASSISTANT text + tool notes only (never re-echo user prompt).
    text_parts: list[str] = []
    tool_lines: list[str] = []
    seen_text = ""
    idle = threading.Event()
    err_box: list[BaseException] = []
    last_tool_key = ""
    # messageID → role (filled by message.updated); only assistant parts stream to the pane
    msg_role: dict[str, str] = {}
    assistant_ids: set[str] = set()

    def _emit(chunk: str) -> bool:
        """Forward to on_delta; return False if abort raised."""
        if not chunk:
            # heartbeat / keep-alive
            if on_delta is not None:
                try:
                    on_delta("")
                except Exception:  # noqa: BLE001
                    return False
            return True
        text_parts.append(chunk)
        if on_delta is not None:
            try:
                on_delta(chunk)
            except Exception:  # noqa: BLE001
                return False
        return True

    def _is_assistant(mid: str | None) -> bool:
        if not mid:
            return False
        if mid in assistant_ids:
            return True
        return msg_role.get(mid) == "assistant"

    def sse_loop():
        nonlocal seen_text, last_tool_key
        try:
            # timeout is per-read idle; heartbeats keep it alive during long thinks
            r = Request(f"{_base(h.port)}/event")
            with urlopen(r, timeout=_TURN_TIMEOUT_S) as resp:
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
                        if not _emit(""):
                            idle.set()
                            return
                        continue
                    if typ == "message.updated":
                        info = props.get("info") or {}
                        mid = info.get("id") or ""
                        role = info.get("role") or ""
                        if mid and role:
                            msg_role[mid] = role
                            if role == "assistant":
                                assistant_ids.add(mid)
                        continue
                    if typ == "message.part.delta":
                        mid = props.get("messageID") or ""
                        if not _is_assistant(mid):
                            continue  # skip user/system echo
                        delta = props.get("delta") or props.get("text") or ""
                        if delta and not _emit(delta):
                            idle.set()
                            return
                        continue
                    if typ == "message.part.updated":
                        part = props.get("part") or {}
                        mid = part.get("messageID") or props.get("messageID") or ""
                        ptype = part.get("type")
                        if ptype == "text":
                            if not _is_assistant(mid):
                                continue
                            full = part.get("text") or ""
                            if full and full != seen_text:
                                if full.startswith(seen_text):
                                    chunk = full[len(seen_text):]
                                    # only emit growth when no delta frames arrived
                                    if chunk and not text_parts:
                                        if not _emit(chunk):
                                            idle.set()
                                            return
                                seen_text = full
                        elif ptype == "tool":
                            # tools are always on the assistant side
                            tool = part.get("tool") or "tool"
                            state = (part.get("state") or {}).get("status") or ""
                            key = f"{tool}:{state}"
                            if key != last_tool_key and state:
                                last_tool_key = key
                                note = f"\n`[{tool} · {state}]`\n"
                                tool_lines.append(note)
                                if not _emit(note):
                                    idle.set()
                                    return
                        elif ptype == "reasoning":
                            if not _is_assistant(mid):
                                continue
                            # keep-alive only — full reasoning stays in OpenCode
                            if not _emit(""):
                                idle.set()
                                return
                        continue
                    if typ in ("session.error", "message.error"):
                        msg = props.get("message") or props.get("error") or typ
                        err_box.append(RuntimeError(str(msg)))
                        idle.set()
                        return
                    if typ == "session.idle":
                        idle.set()
                        return
        except Exception as e:  # noqa: BLE001
            err_box.append(e)
            idle.set()

    th = threading.Thread(target=sse_loop, daemon=True)
    th.start()
    time.sleep(0.3)  # let the SSE connect before the message

    body: dict[str, Any] = {
        "parts": [{"type": "text", "text": prompt}],
        "model": model,
        "agent": agent_name,
    }
    if variant:
        body["variant"] = variant
    sys = (payload.get("system") or "").strip()
    if sys:
        body["system"] = sys

    # POST /message is blocking until the turn finishes — must match turn budget.
    try:
        resp = _req("POST", f"{_base(h.port)}/session/{h.session_id}/message",
                    body, timeout=_TURN_TIMEOUT_S)
    except TimeoutError as e:
        idle.set()
        raise RuntimeError(
            f"opencode turn timed out after {_TURN_TIMEOUT_S // 60} min — "
            "the agent was still working; try a shorter prompt or retry") from e
    except HTTPError as e:
        idle.set()
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:400]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"opencode message failed: HTTP {e.code} {detail}") from e
    except URLError as e:
        idle.set()
        # urllib wraps socket.timeout as URLError(TimeoutError(...))
        reason = getattr(e, "reason", e)
        if isinstance(reason, TimeoutError) or "timed out" in str(e).lower():
            raise RuntimeError(
                f"opencode turn timed out after {_TURN_TIMEOUT_S // 60} min — "
                "the agent was still working; try a shorter prompt or retry") from e
        raise RuntimeError(f"opencode message failed: {e}") from e

    # wait for idle (or abort) — POST may return before final SSE idle
    deadline = time.time() + 30  # short grace after POST returns
    while not idle.is_set() and time.time() < deadline:
        if abort is not None and abort.is_set():
            interrupt(room_id)
            break
        time.sleep(0.2)
    idle.set()

    # final text: streamed assistant deltas, then POST body (assistant only), then seen_text
    text = "".join(text_parts) or seen_text
    if isinstance(resp, dict):
        info = resp.get("info") or {}
        if info.get("role") == "assistant" or not text:
            body_text = ""
            for p in resp.get("parts") or []:
                if p.get("type") == "text":
                    body_text += p.get("text") or ""
            # Prefer POST body when it is the assistant reply and longer than stream crumbs
            if body_text and (info.get("role") == "assistant" or not text):
                if info.get("role") == "assistant":
                    text = body_text
                elif not text:
                    text = body_text
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

You are the CODE SEAT for a Fusion room (coding harness), not a main-chat panelist.

## Where you sit
- Main transcript: shared room chat — do not write it except via fusion MCP tools.
- Code pane: your private harness session.
- Workspace: this directory — all edits and shell stay here.

## Diplomatic tools (fusion MCP)
- query_main_state — read forward-only main context
- comment_to_main — post a short from_code note (may need approval)
- ask_design_question — block until the room answers in the outbox
- workspace_status — path / git / recent code notes
- request_compaction — request compaction via outbox

Prefer these over bash for room communication. Bash is for workspace work only.

## Discipline
- Forward context only; no raw panelist dumps.
- Report-only on recon unless asked to implement.
- Falsifiable tests when you change code you own.

Full contract: repo AGENTS.md + CLAUDE.md.
"""
