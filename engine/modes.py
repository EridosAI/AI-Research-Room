"""modes.py — interaction patterns as rounds + a gate over the substrate, per-room.

An interaction pattern is a CATEGORY, not a set of bespoke functions. A **Round** is
{participants, context, flow, instruction, role}; a **Mode** is an ordered list of rounds
+ a gate. `run_mode` is the single executor; `research`/`converse`/`side_by_side` are thin
wrappers that build a mode-spec and call it.

  - participants: all | subset | one | judge
  - context:      blind (prompt+docs+instruction only) | transcript (build_context, synthesis-only)
  - flow:         parallel (sequential is an extension point, not yet implemented)
  - instruction:  the appended prompt-modifier (blind rounds) / judge output guidance (judge rounds)
  - role:         ai (forward) | ai-raw (is_panelist_raw — OUT of forward context) | judge (forward)

Invariant by construction: the per-round `instruction` is a prompt-modifier (never stored,
like the no-search guard); model outputs + the judge synthesis are `turn.text` (forward as
normal); `ai-raw` outputs stay out of forward context. Modes shape HOW models are prompted,
never WHAT serializes forward.

Both wrappers resolve to the given room's main.jsonl and read participants/judge from
room.json. There is no engine-level "current" room.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

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

# Side-by-side (Phase 25): the judge does NOT synthesize — it reports divergence so the
# reader can choose which full answer to read. A distinct system (JUDGE_SYSTEM would fight
# "do not merge") + a distinct output instruction.
SIDE_SYSTEM = (
    "You are comparing several independent answers to the SAME task in a multi-model room. "
    "Report only where they differ; do not merge them and do not pick a winner."
)
DIVERGENCE_NOTE = (
    "The answers to the same task are above. Produce ONLY a brief note of where they differ "
    "— the key points of divergence — so the reader can choose which full answer to read. "
    "Do not merge them and do not pick a winner."
)


# ---- the round / mode model -------------------------------------------------
@dataclass(frozen=True)
class Round:
    participants: str            # all | subset | one | judge
    context: str | None = None   # blind | transcript | None (judge)
    flow: str = "parallel"       # parallel | sequential (sequential: extension point, not impl)
    instruction: str = ""        # appended prompt-modifier (ai) / judge output guidance (judge)
    role: str = "ai"             # ai | ai-raw | judge
    tools: bool = True           # api web-search / cli runner on this round
    max_tokens: int | None = None
    degrade: bool = True         # failure → absence + abort-if-all-fail (panel); False → propagate (converse)
    system: str | None = None    # judge system override (judge rounds)


@dataclass(frozen=True)
class Mode:
    name: str
    turn_mode: str               # "research" (grouped round in the UI) | "converse" (individual turns)
    rounds: tuple = field(default_factory=tuple)
    gate: str = "single"         # single | loop (loop = future: Debate)


FUSION_MODE = Mode("fusion", "research", (
    Round("all", "blind", "parallel", PANEL_INSTRUCTION, "ai-raw", degrade=True),
    Round("judge", None, "parallel", "", "judge", degrade=False),
), "single")

CONVERSE_MODE = Mode("converse", "converse", (
    Round("one", "transcript", "parallel", "", "ai", tools=False, degrade=False),
), "single")

SIDE_BY_SIDE_MODE = Mode("side_by_side", "research", (
    Round("subset", "blind", "parallel", PANEL_INSTRUCTION, "ai-raw", degrade=True),
    Round("judge", None, "parallel", DIVERGENCE_NOTE, "judge", degrade=False, system=SIDE_SYSTEM),
), "single")

MODES = {m.name: m for m in (FUSION_MODE, CONVERSE_MODE, SIDE_BY_SIDE_MODE)}


# ---- attached files (Phase 22) ----------------------------------------------
# A dropped .md/.txt becomes a file-turn whose `text` IS the content, so it rides
# the ordinary turn.text forward-context path (no new injection plumbing). Text
# only: .md/.txt read as text trivially; richer formats (pdf/docx) need extraction
# and stay out (DEFERRED).
TEXT_EXTS = {".md", ".txt"}
MAX_FILE_BYTES = 1_000_000   # 1 MB per file — a guard, not a product limit


def _file_ext(filename: str) -> str:
    name = (filename or "").strip().lower()
    return name[name.rfind("."):] if "." in name else ""


def attach_file(room_id: str, filename: str, content: str) -> dict:
    """Append a file-turn to a room (no model call). The turn's text is
    `[file: {filename}]\\n\\n{content}` — the lightweight header tells the panel
    it's an attached document; the content then flows forward exactly like a typed
    message (build_context serializes turn.text; research threads it into the blind
    payload). Raises ValueError on a non-text extension or oversize file."""
    ext = _file_ext(filename)
    if ext not in TEXT_EXTS:
        raise ValueError(f"text files only (.md/.txt) — got {filename!r}")
    if len((content or "").encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError(f"file too large: {filename!r} (> {MAX_FILE_BYTES} bytes)")
    path = rooms.main_path(room_id)
    meta = {"kind": "file", "filename": filename,
            "size": len((content or "").encode("utf-8"))}
    text = f"[file: {filename}]\n\n{content or ''}"
    return transcript.append(transcript.make_turn("converse", "human", "human", text, meta), path)


def _attached_docs(turns: list[dict]) -> list[str]:
    """The text of every file-turn in a transcript, in order — the documents loaded
    into the room. Re-sent to the panel every research round (see the cost note)."""
    return [t["text"] for t in turns if (t.get("meta") or {}).get("kind") == "file"]


# ---- shared primitives (extracted, not rewritten) --------------------------
def _panelist(speaker: str, payload: dict, effort: str, reasoning_effort: str | None = None,
              *, tools: bool = True, max_tokens: int | None = None):
    """Run one panelist. Returns (speaker, ModelReply|None, error). Never raises —
    a failure becomes an absence, captured for the judge prompt."""
    try:
        reply = providers.call_model(speaker, payload, tools=tools, effort=effort,
                                     max_tokens=(max_tokens or settings.RESEARCH_MAX_TOKENS),
                                     reasoning_effort=reasoning_effort)
        if not reply.text.strip():
            return speaker, None, "empty answer"
        return speaker, reply, None
    except Exception as e:  # noqa: BLE001 — any failure → absent, never agreement
        return speaker, None, str(e)


def _reply_meta(reply) -> dict:
    """meta fields carried from a reply: reasoning (best-effort), token usage (incl. cost),
    and the API-reported served_model. All live on the turn's meta, never in text — so
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
                        absent: list[tuple[str, str]], instruction: str | None = None) -> str:
    """The judge sees the task + every prior answer's TEXT (never reasoning) + absences.
    `instruction` is the judge round's output guidance: None → the synthesis rubric +
    standard fusion output (byte-identical to the pre-framework prompt); a string → that
    text as the OUTPUT section (e.g. side-by-side's divergence note)."""
    parts = ["===== ORIGINAL TASK =====", task, "", "===== PANEL ANSWERS ====="]
    for speaker, text in answers:
        parts += [f"--- Panelist: {speaker} ---", text, ""]
    if absent:
        parts += ["===== ABSENT PANELISTS (failed/dropped — NOT agreement) ====="]
        parts += [f"- {s}: {err}" for s, err in absent]
        parts += [""]
    if instruction is None:
        rubric_file = settings.REFS_DIR / "judge_rubric.md"
        rubric = rubric_file.read_text(encoding="utf-8") if rubric_file.is_file() else (
            "(rubric missing — synthesize: consensus, contradictions, partial coverage, "
            "unique insights, blind spots; for code, merge into one working artifact.)"
        )
        parts += ["===== HOW TO JUDGE =====", rubric, "", "===== OUTPUT ====="]
        parts.append(
            "Lead with the FINAL ANSWER (the deliverable). Then an AUDIT TRAIL per the "
            "rubric track, attributing each point to the panelist that raised it. Any "
            "panelist listed absent above failed or was dropped — treat it as absent, "
            "never as silent agreement."
        )
    else:
        parts += ["===== OUTPUT =====", instruction]
    return "\n".join(parts)


def _call_judge(judge: str, payload: dict, effort: str, reasoning_effort: str | None = None):
    try:
        return providers.call_model(judge, payload, tools=True, effort=effort,
                                    max_tokens=settings.RESEARCH_MAX_TOKENS,
                                    reasoning_effort=reasoning_effort)
    except providers.RunnerUnavailable:
        return providers.call_model(judge, payload, tools=False,
                                    max_tokens=settings.RESEARCH_MAX_TOKENS,
                                    reasoning_effort=reasoning_effort)


# ---- the executor -----------------------------------------------------------
def _resolve_participants(rnd: Round, selection: dict, room: dict, target: str | None) -> list[str]:
    if rnd.participants == "subset":
        return list(selection["seats"])
    if rnd.participants == "one":
        return [target]
    return list(selection.get("panel") or room["participants"])      # "all"


def _round_payload(rnd: Round, speaker: str, prompt: str, doc_block: str,
                   path, room: dict, human_label: str) -> dict:
    if rnd.context == "transcript":
        return build_context(transcript.load(path), speaker, "converse",
                             participants=room["participants"], human_label=human_label)
    # blind: prompt + attached docs + the round's instruction only (no transcript)
    return {"system": "", "messages": [
        {"role": "user", "content": f"{doc_block}{prompt}\n\n---\n{rnd.instruction}"}]}


def run_mode(room_id: str, mode: Mode, prompt: str, selection: dict,
             *, effort: str = "medium", human_label: str = "human") -> str:
    """Execute a mode (ordered rounds + gate) over a room. The single path under every
    interaction pattern — degradation, both judge fallbacks, meta-isolation, and the
    ai-raw forward-context exclusion all live here, exercised by the wrappers + new modes.

    selection = {panel?, seats?, target?, judge?} — the mode-selection object (the UI
    dropdown is its v1 producer; a future trajectory-graph is a second producer of the
    SAME object, so nothing here changes when the graph lands)."""
    room = rooms.load_room(room_id)
    path = rooms.main_path(room_id)
    efforts = room.get("reasoning_effort") or {}
    round_id = str(uuid.uuid4())

    # attached documents (Phase 22) for blind rounds — read before the human turn
    docs = _attached_docs(transcript.load(path))
    doc_block = ("\n\n".join(docs) + "\n\n===== END ATTACHED FILES =====\n\n") if docs else ""

    # a single-seat target (converse): resolve for the human-turn meta + the "one" round
    target = selection.get("target")
    if mode.turn_mode == "converse" and not target:
        target = (transcript.last_ai_speaker(path)
                  or (room["participants"] or providers.enabled() or providers.provider_keys())[0])

    human_meta = {"addressed_to": target} if mode.turn_mode == "converse" else {"round_id": round_id}
    transcript.append(transcript.make_turn(mode.turn_mode, "human", "human", prompt, human_meta), path)

    prior: list[tuple[str, str]] = []   # (speaker, text) from the latest ai round — judge sees TEXT only
    absent: list[tuple[str, str]] = []
    last = ""
    for rnd in mode.rounds:
        if rnd.role == "judge":
            judge = selection.get("judge") or room["judge"]
            jpayload = {"system": rnd.system or JUDGE_SYSTEM, "messages": [
                {"role": "user", "content": _build_judge_prompt(prompt, prior, absent,
                                                                rnd.instruction or None)}]}
            meta: dict = {"round_id": round_id}
            judge_used = judge
            try:
                reply = _call_judge(judge, jpayload, effort, efforts.get(judge))
            except Exception:  # noqa: BLE001 — judge down → fall back to a seat that answered
                fallbacks = [s for s, _ in prior if s != judge]
                if not fallbacks:
                    raise
                judge_used = fallbacks[0]
                reply = _call_judge(judge_used, jpayload, effort, efforts.get(judge_used))
                meta["judge_fallback_from"] = judge
            meta["model"] = providers.provider(judge_used).model
            meta.update(_reply_meta(reply))
            transcript.append(transcript.make_turn(mode.turn_mode, "judge", judge_used, reply.text, meta), path)
            last = reply.text
            continue

        # ai / ai-raw round
        speakers = _resolve_participants(rnd, selection, room, target)
        if rnd.degrade:
            with ThreadPoolExecutor(max_workers=max(1, len(speakers))) as ex:
                results = list(ex.map(
                    lambda s: _panelist(s, _round_payload(rnd, s, prompt, doc_block, path, room, human_label),
                                        effort, efforts.get(s), tools=rnd.tools, max_tokens=rnd.max_tokens),
                    speakers))
        else:   # non-degrading single seat (converse): a failure propagates, as before
            s0 = speakers[0]
            reply0 = providers.call_model(
                s0, _round_payload(rnd, s0, prompt, doc_block, path, room, human_label),
                tools=rnd.tools, effort=effort, max_tokens=rnd.max_tokens, reasoning_effort=efforts.get(s0))
            results = [(s0, reply0, None)]

        prior, absent = [], []
        for speaker, reply, err in results:
            if err is not None:
                absent.append((speaker, err))
                continue
            p = providers.provider(speaker)
            meta = {"model": p.model, **_reply_meta(reply)}
            if mode.turn_mode != "converse":
                meta = {"round_id": round_id, **meta}
            if rnd.role == "ai-raw":
                meta["is_panelist_raw"] = True
                meta["tools"] = (p.auth_mode == "cli")      # only cli actually searched
            transcript.append(transcript.make_turn(mode.turn_mode, "ai", speaker, reply.text, meta), path)
            prior.append((speaker, reply.text))             # judge sees text only — never reasoning
            last = reply.text
        if rnd.degrade and not prior:
            raise RuntimeError("every panelist failed — nothing to judge")
    return last


# ---- wrappers (thin mode-specs over run_mode; signatures preserved) ---------
def research(room_id: str, prompt: str, panel: list[str] | None = None,
             judge: str | None = None, effort: str = "medium") -> str:
    """Fusion: blind parallel panel + a judge synthesis. Degrades gracefully (a failed
    panelist → absent, never silent agreement; abort only if zero return)."""
    room = rooms.load_room(room_id)
    panel = panel if panel is not None else room["participants"]
    judge = judge or room["judge"]
    if not panel:
        raise ValueError("no panelists selected for this room")
    if not judge:
        raise ValueError("no judge selected for this room")
    return run_mode(room_id, FUSION_MODE, prompt, {"panel": panel, "judge": judge}, effort=effort)


def converse(room_id: str, prompt: str, addressed_to: str | None = None,
             human_label: str = "human") -> str:
    """One model answers, seeing the room's synthesis-only forward context (raw panel
    answers never flow forward)."""
    room = rooms.load_room(room_id)
    path = rooms.main_path(room_id)
    if not addressed_to:
        addressed_to = (transcript.last_ai_speaker(path)
                        or (room["participants"] or providers.enabled()
                            or providers.provider_keys())[0])
    providers.provider(addressed_to)   # validate; raises ValueError if unknown
    return run_mode(room_id, CONVERSE_MODE, prompt, {"target": addressed_to}, human_label=human_label)


def side_by_side(room_id: str, prompt: str, seats: list[str],
                 judge: str | None = None, effort: str = "medium") -> str:
    """Two seats answer the same task blind (ai-raw); the judge produces a short
    divergence note (does NOT merge) so the reader can choose which full answer to read."""
    room = rooms.load_room(room_id)
    judge = judge or room["judge"]
    if not seats or len(seats) != 2:
        raise ValueError("side-by-side needs exactly two models")
    if not judge:
        raise ValueError("no judge selected for this room")
    for s in seats:
        providers.provider(s)          # validate each; raises ValueError if unknown
    return run_mode(room_id, SIDE_BY_SIDE_MODE, prompt,
                    {"seats": list(seats), "judge": judge}, effort=effort)
