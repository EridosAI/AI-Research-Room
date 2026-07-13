#!/usr/bin/env python3
"""Minimal stdio MCP server exposing Fusion diplomatic channel tools.

Launched by OpenCode from workspace opencode.json.

OpenCode 1.17 speaks newline-delimited JSON-RPC on stdio (NDJSON), NOT
Content-Length framing. We accept both, and reply in the same style as the
request (NDJSON if the request was a bare line).

Lazy-import engine.channel only on tools/call so initialize is instant.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

_LOG = Path(os.environ.get("FUSION_MCP_LOG", "/tmp/fusion-channel-mcp.log"))
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
# when running from ~/fusion-mcp/channel_mcp.py, parents[1] is home — prefer env
_REPO_ENV = os.environ.get("FUSION_REPO") or os.environ.get("PYTHONPATH", "").split(os.pathsep)[0]
if _REPO_ENV and _REPO_ENV not in sys.path:
    sys.path.insert(0, _REPO_ENV)

ROOM_ID = sys.argv[1] if len(sys.argv) > 1 else ""
# reply framing: "ndjson" | "content-length"
_REPLY_MODE = "ndjson"


def _log(msg: str) -> None:
    try:
        with _LOG.open("a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")
    except Exception:
        pass


TOOLS = [
    {
        "name": "comment_to_main",
        "description": (
            "Diplomatic: post a short note into the MAIN room transcript (meta.from_code). "
            "May wait for outbox approval in control mode. After posting, main auto-replies; "
            "the tool result includes main_reply (acknowledgment from the room). "
            "Use that reply as confirmation the room received you. Do not use bash to fake a bridge."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "speaker": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "query_main_state",
        "description": (
            "Diplomatic: read a synthesis-only forward view of the MAIN transcript "
            "(windowed last_1|last_3|full). Use as background for implementation; "
            "not raw panelist internals."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "window": {"type": "string", "enum": ["last_1", "last_3", "full"]},
            },
        },
    },
    {
        "name": "ask_design_question",
        "description": (
            "Diplomatic: ask the human/room a design question and BLOCK until they answer "
            "in the code-pane outbox. Prefer this when blocked on a choice only the room "
            "can make. Do not busy-loop with bash while waiting."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "workspace_status",
        "description": (
            "Diplomatic: non-blocking orientation — workspace_path, channel_mode, "
            "git status --short, recent from_code notes, outbox pending count. "
            "Prefer over ad-hoc bash for 'where am I'."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "request_compaction",
        "description": (
            "Diplomatic: request context compaction via the room outbox "
            "(auto-ack or control approval)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"note": {"type": "string"}},
        },
    },
]


def _read_message() -> dict | None:
    """Read one JSON-RPC message: NDJSON line OR Content-Length framed."""
    global _REPLY_MODE
    # Peek first byte
    first = sys.stdin.buffer.read(1)
    if not first:
        return None

    # Content-Length framing starts with 'C' or 'c' of "Content-Length"
    if first in (b"C", b"c"):
        _REPLY_MODE = "content-length"
        header = first
        while True:
            ch = sys.stdin.buffer.read(1)
            if not ch:
                return None
            header += ch
            if header.endswith(b"\r\n\r\n") or header.endswith(b"\n\n"):
                break
        length = 0
        for line in header.decode("utf-8", "replace").splitlines():
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        body = sys.stdin.buffer.read(length) if length else b""
        if not body:
            return None
        return json.loads(body.decode("utf-8"))

    # NDJSON: rest of line after first byte
    _REPLY_MODE = "ndjson"
    rest = sys.stdin.buffer.readline()
    line = (first + rest).decode("utf-8", "replace").strip()
    if not line:
        return _read_message()  # blank line — try next
    return json.loads(line)


def _write_message(msg: dict) -> None:
    raw = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    if _REPLY_MODE == "content-length":
        sys.stdout.buffer.write(
            f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw)
    else:
        # NDJSON (OpenCode 1.17 default)
        sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()


def _result(id_, result) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _handle(msg: dict) -> dict | None:
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "initialize":
        return _result(mid, {
            # echo a protocol OpenCode accepts; 2024-11-05 is widely supported
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fusion-channel", "version": "1"},
        })
    if method == "notifications/initialized":
        return None
    if method == "notifications/cancelled":
        return None
    if method == "tools/list":
        return _result(mid, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name") or ""
        args = params.get("arguments") or {}
        if not ROOM_ID:
            return _error(mid, -32000, "room_id not configured")
        try:
            from engine import channel  # noqa: WPS433 — lazy
            out = channel.dispatch_tool(ROOM_ID, name, args)
            if isinstance(out, str):
                text = out
            elif isinstance(out, dict) and name == "comment_to_main":
                # Make the room's acknowledgment obvious to the code seat in the tool result.
                parts = [f"status={out.get('status') or 'posted'}"]
                if out.get("text"):
                    parts.append(f"posted: {out.get('text')}")
                if out.get("main_reply"):
                    who = out.get("main_speaker") or "main"
                    parts.append(f"main_reply from [{who}]:\n{out.get('main_reply')}")
                elif out.get("status") == "pending":
                    parts.append("awaiting outbox approval")
                text = "\n".join(parts)
            else:
                text = json.dumps(out, ensure_ascii=False, default=str)
            return _result(mid, {"content": [{"type": "text", "text": text}]})
        except Exception as e:  # noqa: BLE001
            _log(f"tools/call {name}: {type(e).__name__}: {e}\n{traceback.format_exc()}")
            return _error(mid, -32000, f"{type(e).__name__}: {e}")
    if method == "ping":
        return _result(mid, {})
    if mid is not None:
        return _error(mid, -32601, f"method not found: {method}")
    return None


def main() -> int:
    _log(f"start room={ROOM_ID!r} vault={os.environ.get('RESEARCH_ROOM_VAULT')!r} pid={os.getpid()}")
    while True:
        try:
            msg = _read_message()
        except Exception as e:  # noqa: BLE001
            _log(f"read error: {e}\n{traceback.format_exc()}")
            return 1
        if msg is None:
            _log("stdin closed")
            return 0
        try:
            resp = _handle(msg)
            if resp is not None:
                _write_message(resp)
        except Exception as e:  # noqa: BLE001
            _log(f"handle error: {e}\n{traceback.format_exc()}")
            mid = msg.get("id") if isinstance(msg, dict) else None
            if mid is not None:
                _write_message(_error(mid, -32603, f"{type(e).__name__}: {e}"))


if __name__ == "__main__":
    raise SystemExit(main())
