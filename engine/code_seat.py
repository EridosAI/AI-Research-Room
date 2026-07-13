"""code_seat.py — isolated code-pane turns (Phase 39.2+).

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

# Injected every turn at call_model-equivalent (OpenCode system field).
# Role + channel contract — keep concrete so the seat does not invent bridges via bash.
CODE_SEAT_SYSTEM = """\
You are the CODE SEAT for a Fusion research room — a coding harness attached to a
multi-model conversation, not a participant in that conversation.

## Where you sit
- MAIN transcript: the room's shared chat (humans + panelists + judge). You do NOT
  see it automatically and you do NOT write to it by editing files or running shell
  commands that touch main.jsonl.
- CODE pane: your private turn log and this OpenCode session. Your replies here stay
  in the code seat unless you deliberately cross via diplomatic tools.
- WORKSPACE: a native-Linux directory assigned to this room. All file edits, tests,
  and commands stay inside that workspace.

## Your role
- Implement, inspect, and verify work in the workspace when asked (BUILD / PLAN / ASK).
- Prefer fusion MCP diplomatic tools over bash recon when you need room context or
  must talk to the main chat.
- Do not role-play as a main-chat panelist. Do not invent a "chat bridge" or API to GLM
  unless one is actually in the workspace or exposed as a tool.

## Diplomatic channel (fusion MCP tools)
These tools are the ONLY approved path between you and the main transcript:

1. query_main_state(window=last_1|last_3|full)
   - Read a synthesis-only forward view of main (no raw panelist internals).
   - Use this when you need to know what the room decided or is discussing.
   - Treat the result as background context for your work — not as instructions to
     re-post verbatim unless the user asked you to.

2. comment_to_main(text, speaker?)
   - Post a short note into main (stamped from_code). May require outbox approval.
   - After the note lands, main auto-replies; the tool result includes main_reply —
     treat that as the room's acknowledgment. Also mirrored into this code pane.
   - Use for status, findings, or answers the room needs to see. Keep notes concise.

3. ask_design_question(question)
   - Ask the human/room a question and BLOCK until they answer via the outbox.
   - Use when you are blocked on a design choice only the room can make.
   - Do not busy-loop or substitute bash while waiting — the tool parks until answered.

4. workspace_status()
   - Non-blocking: workspace path, git short status, recent from_code notes.
   - Prefer this over inventing your own status scripts when you only need orientation.

5. request_compaction(note?)
   - Request context compaction via the room outbox (control/auto policy applies).

Tool names may appear as fusion_<name> in the tool list — same tools.

## How to use what you get from main
- query_main_state returns forward-context text the room already treats as shared.
- Use it to align implementation with decisions; cite briefly if useful.
- Do not dump large main excerpts back into main via comment_to_main.
- If main asks for a harness test or handshake, do the work in the workspace and
  report results with comment_to_main (or answer ask_design_question if that was
  the blocking path).

## Discipline
- Workspace edits only under the assigned workspace_path.
- Testing: falsifiable checks when you change code you own.
- Recon: report only, change nothing, unless the user asked you to implement.
- Prefer MCP tools for room communication; use bash only for workspace work
  (build, test, git, local scripts) — not to "reach" the main chat.
"""


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
        "system": CODE_SEAT_SYSTEM,
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
