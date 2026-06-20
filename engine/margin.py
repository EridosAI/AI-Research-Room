"""margin.py — the in-room side-channel.

A margin is a per-room side conversation stored in its OWN file (margin.jsonl).
Its whole reason to exist is that it never pollutes the main thread: information
flows ONE way by default — main → margin (read-only background) — and margin →
main only when the user explicitly promotes a single answer.

Background construction (the property flag 2 cares about): the margin sees the
SAME forward view the reader sees — main filtered through the synthesis-only
filter (raw panel answers excluded), then windowed. The window is defined in
LOGICAL turns (filtered turns), never raw JSONL lines, so a multi-object research
round is never split mid-window.
"""

from __future__ import annotations

from . import context, providers, rooms, transcript

# Window options shipped now (last `current view` is deferred). Defined over the
# FILTERED forward turns, so "last 1" is the last synthesis/answer, not a raw line.
WINDOWS = {"last_1": 1, "last_3": 3, "full": None}


def _system(model: str) -> str:
    return (
        f"You are [{model}], a side assistant. Below is BACKGROUND — the conversation "
        "the user is reading (read-only, you are not part of it). Then the user's "
        "side-questions to you. Answer the latest side-question; you may reference "
        "the background."
    )


def windowed_background(main_turns: list[dict], window: str) -> str:
    """Synthesis-only filtered main, then the last-N logical turns (or all)."""
    fwd = context.forward_turns(main_turns)
    n = WINDOWS.get(window, WINDOWS["last_3"])
    if n is not None:
        fwd = fwd[-n:]
    return context.format_turns(fwd)


def margin_turn(room_id: str, prompt: str, window: str = "last_3",
                model: str | None = None) -> str:
    """Ask the margin a side-question. Reads main (windowed, filtered) as
    background + the prior margin Q&A, calls the margin model (tools=False), and
    appends BOTH the question and the answer to margin.jsonl. Never writes main."""
    room = rooms.load_room(room_id)
    model = model or room.get("margin_model")
    if not model:
        raise ValueError("no margin model selected for this room")
    providers.provider(model)   # validate; raises ValueError if unknown

    mpath = rooms.margin_path(room_id)
    background = windowed_background(transcript.load(rooms.main_path(room_id)), window)
    side = context.format_turns(transcript.load(mpath))
    body = ("=== BACKGROUND (main transcript) ===\n" + (background or "(empty)\n")
            + "\n=== SIDE CONVERSATION ===\n" + (side or "(none yet)\n")
            + f"\n[human]: {prompt}\n")
    payload = {"system": _system(model),
               "messages": [{"role": "user", "content": body}]}

    transcript.append(transcript.make_turn(
        "margin", "human", "human", prompt, {"window": window}), mpath)
    reply = providers.call_model(model, payload, tools=False)
    meta = {"model": providers.provider(model).model}
    if reply.reasoning:
        meta["reasoning"] = reply.reasoning
        if reply.reasoning_kind:
            meta["reasoning_kind"] = reply.reasoning_kind
    if reply.served_model:
        meta["served_model"] = reply.served_model   # provenance kept consistent with main
    if reply.finish_reason:
        meta["finish_reason"] = reply.finish_reason
    transcript.append(transcript.make_turn(
        "margin", "ai", model, reply.text, meta), mpath)
    return reply.text


def promote(room_id: str, turn_id: str) -> dict:
    """Copy exactly ONE margin answer into main as a clearly-attributed turn
    (role `note`, mode `converse` so it flows into forward context — the one
    deliberate margin → main path). Never the whole exchange, never automatic."""
    margin_turns = transcript.load(rooms.margin_path(room_id))
    turn = next((t for t in margin_turns
                 if t.get("id") == turn_id and t.get("role") == "ai"), None)
    if turn is None:
        raise ValueError("no such margin answer to promote")
    note = transcript.make_turn(
        "converse", "note", turn["speaker"], turn["text"],
        {"from_margin": True, "margin_turn_id": turn_id,
         "model": (turn.get("meta") or {}).get("model")})
    transcript.append(note, rooms.main_path(room_id))
    return note
