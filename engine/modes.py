"""modes.py — the two call patterns over the substrate, operating per-room.

research(room_id, prompt)  — blind parallel fan-out to the room's participants,
                    then a judge synthesizes. Degrades gracefully: a failed
                    panelist is dropped and marked absent (never silent
                    agreement); abort only if zero panelists return.
converse(room_id, prompt, addressed_to) — one model answers, seeing the room's
                    synthesis-only context (raw panel answers never flow forward).

Both resolve to the given room's main.jsonl and read that room's
participants/judge from room.json. There is no engine-level "current" room.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from . import providers, rooms, settings, transcript
from .context import build_context

# Panelists answer the task straight, blind to each other.
PANEL_INSTRUCTION = (
    "You are one of several independent experts answering the task above. You will "
    "NOT see the others' work, and they will not see yours. Answer the task straight, "
    "in full — research with web search and shell as needed, and return a complete, "
    "self-contained answer. Do not hedge about being part of a panel; just give your "
    "best independent answer."
)

JUDGE_SYSTEM = (
    "You are the JUDGE in a multi-model fusion pipeline. Several independent expert "
    "panelists each answered the SAME task below, without seeing each other's work. "
    "Synthesize their answers into a single, higher-quality final answer."
)


# ---- research ---------------------------------------------------------------
def _panelist(speaker: str, blind_payload: dict, effort: str):
    """Run one panelist. Returns (speaker, ModelReply|None, error). Never raises —
    a failure becomes an absence, captured for the judge prompt."""
    try:
        reply = providers.call_model(speaker, blind_payload, tools=True, effort=effort,
                                     max_tokens=settings.RESEARCH_MAX_TOKENS)
        if not reply.text.strip():
            return speaker, None, "empty answer"
        return speaker, reply, None
    except Exception as e:  # noqa: BLE001 — any failure → absent, never agreement
        return speaker, None, str(e)


def _reply_meta(reply) -> dict:
    """meta fields carried from a reply: reasoning (best-effort), token usage, and the
    API-reported served_model. All live on the turn's meta, never in text — so
    build_context never re-sends them to a model. One helper → every call site (panel,
    judge, converse) gets served_model with no further change."""
    m: dict = {}
    if getattr(reply, "reasoning", None):
        m["reasoning"] = reply.reasoning
        if reply.reasoning_kind:
            m["reasoning_kind"] = reply.reasoning_kind
    if getattr(reply, "usage", None):
        m["usage"] = reply.usage
    if getattr(reply, "served_model", None):
        m["served_model"] = reply.served_model
    s = getattr(reply, "search", None)
    if s:
        if s.get("searches"):
            m["search"] = s["searches"]
        if s.get("citations"):
            m["citations"] = s["citations"]
    if getattr(reply, "finish_reason", None):
        m["finish_reason"] = reply.finish_reason
    return m


def _build_judge_prompt(task: str, answers: list[tuple[str, str]],
                        absent: list[tuple[str, str]]) -> str:
    rubric_file = settings.REFS_DIR / "judge_rubric.md"
    rubric = rubric_file.read_text(encoding="utf-8") if rubric_file.is_file() else (
        "(rubric missing — synthesize: consensus, contradictions, partial coverage, "
        "unique insights, blind spots; for code, merge into one working artifact.)"
    )
    parts = ["===== ORIGINAL TASK =====", task, "", "===== PANEL ANSWERS ====="]
    for speaker, text in answers:
        parts += [f"--- Panelist: {speaker} ---", text, ""]
    if absent:
        parts += ["===== ABSENT PANELISTS (failed/dropped — NOT agreement) ====="]
        parts += [f"- {s}: {err}" for s, err in absent]
        parts += [""]
    parts += ["===== HOW TO JUDGE =====", rubric, "", "===== OUTPUT ====="]
    parts.append(
        "Lead with the FINAL ANSWER (the deliverable). Then an AUDIT TRAIL per the "
        "rubric track, attributing each point to the panelist that raised it. Any "
        "panelist listed absent above failed or was dropped — treat it as absent, "
        "never as silent agreement."
    )
    return "\n".join(parts)


def research(room_id: str, prompt: str, panel: list[str] | None = None,
             judge: str | None = None, effort: str = "medium") -> str:
    room = rooms.load_room(room_id)
    path = rooms.main_path(room_id)
    panel = panel if panel is not None else room["participants"]
    judge = judge or room["judge"]
    if not panel:
        raise ValueError("no panelists selected for this room")
    if not judge:
        raise ValueError("no judge selected for this room")
    round_id = str(uuid.uuid4())

    # 1. append human turn
    transcript.append(transcript.make_turn(
        "research", "human", "human", prompt, {"round_id": round_id}), path)

    # 2. fan out — parallel, blind (only the prompt + panel instruction)
    blind = {"system": "", "messages": [
        {"role": "user", "content": f"{prompt}\n\n---\n{PANEL_INSTRUCTION}"}]}
    with ThreadPoolExecutor(max_workers=max(1, len(panel))) as ex:
        results = list(ex.map(lambda s: _panelist(s, blind, effort), panel))

    # 3. append each raw answer; collect absences
    answers: list[tuple[str, str]] = []
    absent: list[tuple[str, str]] = []
    for speaker, reply, err in results:
        if err is not None:
            absent.append((speaker, err))
            continue
        p = providers.provider(speaker)
        meta = {"round_id": round_id, "is_panelist_raw": True, "model": p.model,
                "tools": p.auth_mode == "cli", **_reply_meta(reply)}   # only cli actually searched
        transcript.append(transcript.make_turn(
            "research", "ai", speaker, reply.text, meta), path)
        answers.append((speaker, reply.text))   # judge sees text only — never reasoning

    if not answers:
        raise RuntimeError("every panelist failed — nothing to judge")

    # 4. judge synthesizes (prompt + all answers + rubric). Judge fallback: if the
    #    configured judge is unavailable (no key / down), fall back to a panelist
    #    that demonstrably answered this round — a bad judge can't sink a round
    #    that otherwise succeeded.
    judge_prompt = _build_judge_prompt(prompt, answers, absent)
    judge_payload = {"system": JUDGE_SYSTEM,
                     "messages": [{"role": "user", "content": judge_prompt}]}
    judge_used = judge
    meta = {"round_id": round_id}
    try:
        reply = _call_judge(judge, judge_payload, effort)
    except Exception:  # noqa: BLE001
        fallbacks = [s for s, _ in answers if s != judge]
        if not fallbacks:
            raise
        judge_used = fallbacks[0]
        reply = _call_judge(judge_used, judge_payload, effort)
        meta["judge_fallback_from"] = judge

    # 5. append synthesis (role=judge, same round_id) and return
    meta["model"] = providers.provider(judge_used).model
    meta.update(_reply_meta(reply))
    transcript.append(transcript.make_turn(
        "research", "judge", judge_used, reply.text, meta), path)
    return reply.text


def _call_judge(judge: str, payload: dict, effort: str):
    try:
        return providers.call_model(judge, payload, tools=True, effort=effort,
                                    max_tokens=settings.RESEARCH_MAX_TOKENS)
    except providers.RunnerUnavailable:
        return providers.call_model(judge, payload, tools=False,
                                    max_tokens=settings.RESEARCH_MAX_TOKENS)


# ---- converse ---------------------------------------------------------------
def converse(room_id: str, prompt: str, addressed_to: str | None = None,
             human_label: str = "human") -> str:
    room = rooms.load_room(room_id)
    path = rooms.main_path(room_id)
    if not addressed_to:
        addressed_to = (transcript.last_ai_speaker(path)
                        or (room["participants"] or providers.enabled()
                            or providers.provider_keys())[0])
    providers.provider(addressed_to)   # validate; raises ValueError if unknown

    transcript.append(transcript.make_turn(
        "converse", "human", "human", prompt, {"addressed_to": addressed_to}), path)

    ctx = build_context(transcript.load(path), addressed_to, "converse",
                        participants=room["participants"], human_label=human_label)
    reply = providers.call_model(addressed_to, ctx, tools=False)

    meta = {"model": providers.provider(addressed_to).model, **_reply_meta(reply)}
    transcript.append(transcript.make_turn(
        "converse", "ai", addressed_to, reply.text, meta), path)
    return reply.text
