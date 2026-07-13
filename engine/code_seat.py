"""code_seat.py — isolated code-pane turns (Phase 39.2).

The code pane talks ONLY to its OpenCode session. Turns land in code.jsonl —
never main.jsonl. Crossing into main requires the diplomatic channel/outbox.
"""

from __future__ import annotations

from . import providers, rooms, transcript
from .adapters import opencode

MODE_PREFIX = {
    "build": (
        "Mode: BUILD. Implement the request in the workspace. Prefer concrete edits, "
        "tests, and verification over long prose.\n\n"
    ),
    "ask": (
        "Mode: ASK. Answer the question about the codebase; do not make edits unless "
        "explicitly requested.\n\n"
    ),
}


def code_turn(room_id: str, prompt: str, *, seat: str | None = None,
              mode: str = "build", on_delta=None, abort=None) -> str:
    """Run one harness turn against the OpenCode adapter; append Q+A to code.jsonl."""
    room = rooms.load_room(room_id)
    seat = seat or ((room.get("code_seats") or [None])[0])
    if not seat:
        raise ValueError("no code seat selected for this room")
    p = providers.provider(seat)   # validate
    mode = mode if mode in MODE_PREFIX else "build"
    text = (prompt or "").strip()
    if not text:
        raise ValueError("prompt required")

    cpath = rooms.code_path(room_id)
    qmeta = {"code_mode": mode, "seat": seat}
    transcript.append(
        transcript.make_turn("code", "human", "human", text, qmeta), cpath)

    payload = {
        "system": (
            "You are the room's code seat. Work only inside the assigned workspace. "
            "Use diplomatic MCP tools for any crossing into the main transcript."
        ),
        "messages": [{"role": "user", "content": MODE_PREFIX[mode] + text}],
    }
    reply_text, usage = opencode.chat(
        p, payload, room_id=room_id, on_delta=on_delta, abort=abort)
    meta = {"model": p.model, "seat": seat, "code_mode": mode}
    if usage:
        meta["usage"] = usage
    transcript.append(
        transcript.make_turn("code", "ai", seat, reply_text, meta), cpath)
    return reply_text


def load_turns(room_id: str) -> list[dict]:
    return transcript.load(rooms.code_path(room_id))
