"""modes.py — the two call patterns over the substrate.

research(prompt)  — blind parallel fan-out to all enabled participants, then a
                    judge synthesizes. Degrades gracefully: a failed panelist is
                    dropped and marked absent (never silent agreement); abort only
                    if zero panelists return.
converse(prompt, addressed_to) — one model answers, seeing the synthesis-only
                    context (raw panel answers never flow forward).
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import providers, settings, transcript
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


def _resolve_path(path: str | Path | None) -> Path:
    return Path(path) if path is not None else transcript.current()


# ---- research ---------------------------------------------------------------
def _panelist(speaker: str, blind_payload: dict, effort: str):
    """Run one panelist. Returns (speaker, text, error). Never raises — a failure
    becomes an absence, captured for the judge prompt."""
    try:
        text = providers.call_model(speaker, blind_payload, tools=True, effort=effort)
        if not text.strip():
            return speaker, None, "empty answer"
        return speaker, text, None
    except Exception as e:  # noqa: BLE001 — any failure → absent, never agreement
        return speaker, None, str(e)


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


def research(prompt: str, panel: list[str] | None = None, judge: str | None = None,
             effort: str = "medium", path: str | Path | None = None) -> str:
    path = _resolve_path(path)
    panel = panel if panel is not None else providers.enabled()
    judge = judge or providers.research_judge()
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
    for speaker, text, err in results:
        if err is not None:
            absent.append((speaker, err))
            continue
        p = providers.provider(speaker)
        transcript.append(transcript.make_turn(
            "research", "ai", speaker, text,
            {"round_id": round_id, "is_panelist_raw": True, "model": p.model,
             "tools": p.auth_mode == "cli"}), path)   # only cli actually searched
        answers.append((speaker, text))

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
        synthesis = _call_judge(judge, judge_payload, effort)
    except Exception:  # noqa: BLE001
        fallbacks = [s for s, _ in answers if s != judge]
        if not fallbacks:
            raise
        judge_used = fallbacks[0]
        synthesis = _call_judge(judge_used, judge_payload, effort)
        meta["judge_fallback_from"] = judge

    # 5. append synthesis (role=judge, same round_id) and return
    meta["model"] = providers.provider(judge_used).model
    transcript.append(transcript.make_turn(
        "research", "judge", judge_used, synthesis, meta), path)
    return synthesis


def _call_judge(judge: str, payload: dict, effort: str) -> str:
    try:
        return providers.call_model(judge, payload, tools=True, effort=effort)
    except providers.RunnerUnavailable:
        return providers.call_model(judge, payload, tools=False)


# ---- converse ---------------------------------------------------------------
def converse(prompt: str, addressed_to: str | None = None,
             path: str | Path | None = None) -> str:
    path = _resolve_path(path)
    if not addressed_to:
        addressed_to = (transcript.last_ai_speaker(path)
                        or (providers.enabled() or providers.provider_keys())[0])
    providers.provider(addressed_to)   # validate; raises ValueError if unknown

    transcript.append(transcript.make_turn(
        "converse", "human", "human", prompt, {"addressed_to": addressed_to}), path)

    ctx = build_context(transcript.load(path), addressed_to, "converse")
    reply = providers.call_model(addressed_to, ctx, tools=False)

    transcript.append(transcript.make_turn(
        "converse", "ai", addressed_to, reply,
        {"model": providers.provider(addressed_to).model}), path)
    return reply
