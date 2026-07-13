"""code_seat.py — isolated code-pane turns (Phase 39.2).

The code pane talks ONLY to its OpenCode session. Turns land in code.jsonl —
never main.jsonl. Crossing into main requires the diplomatic channel/outbox.
"""

from __future__ import annotations

from . import providers, rooms, transcript
from .adapters import opencode

# Harness modes map to OpenCode primary agents + a light prompt prefix.
# build → agent "build" (tools/edits); plan/ask → agent "plan" (no edits).
MODE_SPEC = {
    "build": {
        "agent": "build",
        "prefix": (
            "Mode: BUILD. Implement the request in the workspace. Prefer concrete edits, "
            "tests, and verification over long prose.\n\n"
        ),
    },
    "plan": {
        "agent": "plan",
        "prefix": (
            "Mode: PLAN. Think through the approach and outline steps; do not edit files "
            "or run mutating commands.\n\n"
        ),
    },
    "ask": {
        "agent": "plan",
        "prefix": (
            "Mode: ASK. Answer the question about the codebase; do not make edits unless "
            "explicitly requested.\n\n"
        ),
    },
}

# Reasoning effort → OpenCode message `variant` when the model supports it.
REASONING_VARIANTS = ("", "low", "medium", "high", "max")


def code_turn(room_id: str, prompt: str, *, seat: str | None = None,
              mode: str = "build", reasoning: str = "",
              on_delta=None, abort=None) -> str:
    """Run one harness turn against the OpenCode adapter; append Q+A to code.jsonl."""
    room = rooms.load_room(room_id)
    seat = seat or ((room.get("code_seats") or [None])[0])
    if not seat:
        raise ValueError("no code seat selected for this room")
    p = providers.provider(seat)   # validate
    spec = MODE_SPEC.get(mode) or MODE_SPEC["build"]
    mode = mode if mode in MODE_SPEC else "build"
    variant = reasoning if reasoning in REASONING_VARIANTS and reasoning else None
    text = (prompt or "").strip()
    if not text:
        raise ValueError("prompt required")

    cpath = rooms.code_path(room_id)
    qmeta = {"code_mode": mode, "seat": seat, "reasoning": reasoning or "default"}
    transcript.append(
        transcript.make_turn("code", "human", "human", text, qmeta), cpath)

    payload = {
        "system": (
            "You are the room's code seat. Work only inside the assigned workspace. "
            "Use diplomatic MCP tools for any crossing into the main transcript."
        ),
        "messages": [{"role": "user", "content": spec["prefix"] + text}],
    }
    reply_text, usage = opencode.chat(
        p, payload, room_id=room_id, on_delta=on_delta, abort=abort,
        agent=spec["agent"], variant=variant)
    meta = {"model": p.model, "seat": seat, "code_mode": mode,
            "agent": spec["agent"], "reasoning": reasoning or "default"}
    if usage:
        meta["usage"] = usage
    transcript.append(
        transcript.make_turn("code", "ai", seat, reply_text or "(no text)", meta), cpath)
    return reply_text


def load_turns(room_id: str) -> list[dict]:
    return transcript.load(rooms.code_path(room_id))


def clear_turns(room_id: str) -> None:
    """Wipe the isolated code-pane log (code.jsonl only — never main)."""
    path = rooms.code_path(room_id)
    if path.is_file():
        path.write_text("", encoding="utf-8")
