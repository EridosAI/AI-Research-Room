#!/usr/bin/env python3
"""Minimal stdio MCP server exposing Fusion diplomatic channel tools.

Launched by OpenCode from workspace opencode.json:
  command: [python3, engine/channel_mcp.py, <room_id>]

Protocol: MCP over stdio (JSON-RPC 2.0, Content-Length framing optional;
line-delimited JSON-RPC also accepted for simplicity). Tools block the
call when they must wait on outbox approval.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# allow `python engine/channel_mcp.py` from any cwd
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from engine import channel  # noqa: E402

ROOM_ID = sys.argv[1] if len(sys.argv) > 1 else ""

TOOLS = [
    {
        "name": "comment_to_main",
        "description": "Post a note into the main room transcript (from_code). May require approval.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "speaker": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "query_main_state",
        "description": "Read the synthesis-only forward view of the main transcript (windowed).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "window": {"type": "string", "enum": ["last_1", "last_3", "full"]},
            },
        },
    },
    {
        "name": "ask_design_question",
        "description": "Ask the room a design question and BLOCK until answered.",
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "workspace_status",
        "description": "Non-blocking workspace + git + recent code-note summary.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "request_compaction",
        "description": "Request context compaction via the room outbox.",
        "inputSchema": {
            "type": "object",
            "properties": {"note": {"type": "string"}},
        },
    },
]


def _read_message() -> dict | None:
    """Read one JSON-RPC message (Content-Length framed or single-line JSON)."""
    header = b""
    while True:
        ch = sys.stdin.buffer.read(1)
        if not ch:
            return None
        header += ch
        if header.endswith(b"\r\n\r\n") or header.endswith(b"\n\n"):
            break
        # line-delimited fallback: first byte was '{'
        if header.startswith(b"{") and header.endswith(b"\n"):
            return json.loads(header.decode("utf-8"))
    # parse Content-Length
    length = 0
    for line in header.decode("utf-8", "replace").splitlines():
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip())
    body = sys.stdin.buffer.read(length) if length else b""
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write_message(msg: dict) -> None:
    raw = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(
        f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw)
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
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fusion-channel", "version": "1"},
        })
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result(mid, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name") or ""
        args = params.get("arguments") or {}
        if not ROOM_ID:
            return _error(mid, -32000, "room_id not configured")
        try:
            out = channel.dispatch_tool(ROOM_ID, name, args)
            text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, default=str)
            return _result(mid, {"content": [{"type": "text", "text": text}]})
        except Exception as e:  # noqa: BLE001
            return _error(mid, -32000, f"{type(e).__name__}: {e}")
    if method == "ping":
        return _result(mid, {})
    if mid is not None:
        return _error(mid, -32601, f"method not found: {method}")
    return None


def main() -> int:
    while True:
        msg = _read_message()
        if msg is None:
            return 0
        resp = _handle(msg)
        if resp is not None:
            _write_message(resp)


if __name__ == "__main__":
    raise SystemExit(main())
