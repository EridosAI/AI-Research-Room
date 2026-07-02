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

from . import artifacts, providers, rooms, settings, transcript
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

# The standard fusion OUTPUT instruction (was hardcoded in _build_judge_prompt; now the
# fusion judge round carries it, so the prompt stays byte-identical post-Phase-26).
FUSION_OUTPUT = (
    "Lead with the FINAL ANSWER (the deliverable). Then an AUDIT TRAIL per the "
    "rubric track, attributing each point to the panelist that raised it. Any "
    "panelist listed absent above failed or was dropped — treat it as absent, "
    "never as silent agreement."
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

# Mapping (Phase 26): fusion's panel, but the judge EXPOSES the landscape (four-part map)
# instead of merging. Rubric in references/mapping_rubric.md; a neutral-self system note so
# a judge that is also a panelist treats its own answer as one voice among many.
MAPPING_SYSTEM = (
    "You are MAPPING several independent expert answers to the SAME task in a multi-model "
    "room. Expose the landscape of agreement and disagreement; do NOT merge them into one "
    "answer and do NOT pick a winner. If one of the answers below is your own, treat it as "
    "one voice among many — neutral, never self-favoring."
)
MAPPING_OUTPUT = (
    "Output the MAP in the four sections from the guidance above — Consensus, Divergences, "
    "Unique signal, Takeaway. Map the divergences (the positions AND why they differ), don't "
    "merely list that they exist; do not merge into one answer and do not pick a winner."
)

# Yes-and (Phase 26): B builds on A. A panelist prompt-modifier (like PANEL_INSTRUCTION),
# appended to B's transcript-aware payload — A's answer is already a forward turn B sees.
YES_AND_INSTRUCTION = (
    "The previous expert's answer is above. Respond in the spirit of 'yes, and' — accept it "
    "and build: extend it with what they missed, a complementary angle, or a next step. Add, "
    "don't merely agree or restate; don't contradict or critique. This is additive."
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
    rubric_file: str | None = None  # judge HOW-TO-JUDGE rubric file (references/), if any
    judge_kind: str | None = None   # judge turn label kind: synthesis | map | divergence
    seat: int | None = None      # "one" rounds: index into selection["seats"] (yes-and's ordered pair)


@dataclass(frozen=True)
class Mode:
    name: str
    turn_mode: str               # "research" (grouped round in the UI) | "converse" (individual turns)
    rounds: tuple = field(default_factory=tuple)
    gate: str = "single"         # single | loop (loop = future: Debate)


FUSION_MODE = Mode("fusion", "research", (
    Round("all", "blind", "parallel", PANEL_INSTRUCTION, "ai-raw", degrade=True),
    Round("judge", None, "parallel", FUSION_OUTPUT, "judge", degrade=False,
          rubric_file="judge_rubric.md", judge_kind="synthesis"),
), "single")

CONVERSE_MODE = Mode("converse", "converse", (
    Round("one", "transcript", "parallel", "", "ai", tools=False, degrade=False),
), "single")

SIDE_BY_SIDE_MODE = Mode("side_by_side", "research", (
    Round("subset", "blind", "parallel", PANEL_INSTRUCTION, "ai-raw", degrade=True),
    Round("judge", None, "parallel", DIVERGENCE_NOTE, "judge", degrade=False,
          system=SIDE_SYSTEM, judge_kind="divergence"),
), "single")

# Mapping: fusion's panel, a judge that EXPOSES (four-part map) instead of merging.
MAPPING_MODE = Mode("mapping", "research", (
    Round("all", "blind", "parallel", PANEL_INSTRUCTION, "ai-raw", degrade=True),
    Round("judge", None, "parallel", MAPPING_OUTPUT, "judge", degrade=False,
          system=MAPPING_SYSTEM, rubric_file="mapping_rubric.md", judge_kind="map"),
), "single")

# Yes-and: two transcript ai rounds (an ordered pair). B sees A via forward context — A's
# turn is a normal forward `ai` turn, so build_context shows it to B (no intra-round thread).
YES_AND_MODE = Mode("yes_and", "converse", (
    Round("one", "transcript", "parallel", "", "ai", tools=False, degrade=False, seat=0),
    Round("one", "transcript", "parallel", YES_AND_INSTRUCTION, "ai", tools=False, degrade=False, seat=1),
), "single")

MODES = {m.name: m for m in (FUSION_MODE, CONVERSE_MODE, SIDE_BY_SIDE_MODE, MAPPING_MODE, YES_AND_MODE)}


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
              *, tools: bool = True, max_tokens: int | None = None, cache: bool = False,
              artifacts_dir: str | None = None):
    """Run one panelist. Returns (speaker, ModelReply|None, error). Never raises —
    a failure becomes an absence, captured for the judge prompt."""
    try:
        reply = providers.call_model(speaker, payload, tools=tools, effort=effort,
                                     max_tokens=(max_tokens or settings.RESEARCH_MAX_TOKENS),
                                     reasoning_effort=reasoning_effort, cache=cache,
                                     artifacts_dir=artifacts_dir)
        if not reply.text.strip():
            return speaker, None, "empty answer"
        return speaker, reply, None
    except Exception as e:  # noqa: BLE001 — any failure → absent, never agreement
        return speaker, None, str(e)


def _effort_label(speaker: str, override: str | None) -> str:
    """The thinking level actually REQUESTED for a seat this turn, for the turn meta:
    'off' when the provider's reasoning toggle is off (so no reasoning param is sent —
    the effort dial is inert), the override value when set, else 'default' (reasoning on,
    model default). (cli seats reason via their own runner; we surface 'off' since we
    don't request/capture an api reasoning param for them.)"""
    try:
        on = providers.provider(speaker).reasoning
    except ValueError:
        on = False
    if not on:
        return "off"
    return override or "default"


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
                        absent: list[tuple[str, str]], *, rubric_file: str | None = None,
                        instruction: str | None = None) -> str:
    """The judge sees the task + every prior answer's TEXT (never reasoning) + absences.
    `rubric_file` (references/) → a HOW-TO-JUDGE section; `instruction` → the OUTPUT
    section. Fusion passes judge_rubric.md + FUSION_OUTPUT → byte-identical to the
    pre-framework prompt; mapping passes mapping_rubric.md + MAPPING_OUTPUT; side-by-side
    passes only the divergence-note instruction (no rubric)."""
    parts = ["===== ORIGINAL TASK =====", task, "", "===== PANEL ANSWERS ====="]
    for speaker, text in answers:
        parts += [f"--- Panelist: {speaker} ---", text, ""]
    if absent:
        parts += ["===== ABSENT PANELISTS (failed/dropped — NOT agreement) ====="]
        parts += [f"- {s}: {err}" for s, err in absent]
        parts += [""]
    if rubric_file:
        rf = settings.REFS_DIR / rubric_file
        rubric = rf.read_text(encoding="utf-8") if rf.is_file() else (
            "(rubric missing — synthesize: consensus, contradictions, partial coverage, "
            "unique insights, blind spots; for code, merge into one working artifact.)"
        )
        parts += ["===== HOW TO JUDGE =====", rubric, ""]
    if instruction:
        parts += ["===== OUTPUT =====", instruction]
    return "\n".join(parts)


def _stamp_artifacts(meta: dict, room_id: str, text: str, artifacts_dir: str | None) -> None:
    """Best-effort: auto-write any ```markdown blocks in a FORWARD turn (converse / yes-and
    reply or judge synthesis) and stamp the saved paths on the turn meta as `artifact_paths`
    — so the write is VISIBLE in the transcript (Phase 32.3); before, the paths were
    discarded. Raw panel answers do NOT auto-save (parity with the pre-32 _maybe_artifacts
    sites). Never raises: an artifact failure stamps nothing and must never fail the turn or
    its append. meta.* never enters build_context, so the forward-context invariant holds.
    NOTE: save_artifact's filename collision handling (artifacts.py) is count-based —
    single-writer-safe under the per-room lock; revisit if artifact writes ever parallelize."""
    if not artifacts_dir:
        return
    try:
        paths = artifacts.auto_write(room_id, text, artifacts_dir)
        if paths:
            meta["artifact_paths"] = [str(p) for p in paths]
    except Exception:  # noqa: BLE001 — artifacts are a side-effect, never load-bearing
        pass


def _call_judge(judge: str, payload: dict, effort: str, reasoning_effort: str | None = None,
                artifacts_dir: str | None = None):
    try:
        return providers.call_model(judge, payload, tools=True, effort=effort,
                                    max_tokens=settings.RESEARCH_MAX_TOKENS,
                                    reasoning_effort=reasoning_effort, artifacts_dir=artifacts_dir)
    except providers.RunnerUnavailable:
        return providers.call_model(judge, payload, tools=False,
                                    max_tokens=settings.RESEARCH_MAX_TOKENS,
                                    reasoning_effort=reasoning_effort, artifacts_dir=artifacts_dir)


# ---- the executor -----------------------------------------------------------
def _resolve_participants(rnd: Round, selection: dict, room: dict, target: str | None) -> list[str]:
    if rnd.participants == "subset":
        return list(selection["seats"])
    if rnd.participants == "one":
        if rnd.seat is not None:                          # yes-and's ordered pair: pick by index
            return [selection["seats"][rnd.seat]]
        return [target]
    return list(selection.get("panel") or room["participants"])      # "all"


def _round_payload(rnd: Round, speaker: str, prompt: str, doc_block: str,
                   path, room: dict, human_label: str, context: str | None) -> dict:
    """Build one seat's payload for a round. `context` is the EFFECTIVE context (the
    round's, or the panel_context toggle override) — transcript → build_context (+ the
    round instruction appended), blind → prompt + docs + instruction only."""
    if context == "transcript":
        ctx = build_context(transcript.load(path), speaker, "converse",
                            participants=room["participants"], human_label=human_label)
        if rnd.instruction:                               # e.g. yes-and / a transcript panel
            ctx["messages"][-1]["content"] += f"\n\n---\n{rnd.instruction}"
        return ctx
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
    # per-room artifacts dir (room override → global fallback), resolved ONCE: it both
    # feeds the awareness line into every seat's system prompt (32.2) and is the write
    # target for the meta stamp (32.3), so the two can never disagree.
    art_dir = artifacts.resolve_artifacts_dir(room_id)

    # attached documents (Phase 22) for blind rounds — read before the human turn
    docs = _attached_docs(transcript.load(path))
    doc_block = ("\n\n".join(docs) + "\n\n===== END ATTACHED FILES =====\n\n") if docs else ""

    # a single-seat target (converse): resolve for the human-turn meta + the "one" round
    target = selection.get("target")
    if mode.turn_mode == "converse" and not target:
        target = ((selection.get("seats") or [None])[0]            # yes-and: A is the addressee
                  or transcript.last_ai_speaker(path)
                  or (room["participants"] or providers.enabled() or providers.provider_keys())[0])

    human_meta = {"addressed_to": target} if mode.turn_mode == "converse" else {"round_id": round_id}
    # Round provenance: stamp the mode + its selection params (incl. the panel_context
    # toggle) on the round-head turn, so a transcript is self-describing about what move
    # ran — what was missing when we couldn't tell whether "panel sees conversation" was
    # on. meta only (never serialized forward by build_context), so the invariant holds.
    sel_snapshot = {"mode": mode.name}
    for k in ("panel", "seats", "target", "judge", "panel_context"):
        v = selection.get(k)
        if v:
            sel_snapshot[k] = v
    human_meta["selection"] = sel_snapshot
    transcript.append(transcript.make_turn(mode.turn_mode, "human", "human", prompt, human_meta), path)

    prior: list[tuple[str, str]] = []   # (speaker, text) from the latest ai round — judge sees TEXT only
    absent: list[tuple[str, str]] = []
    last = ""
    for rnd in mode.rounds:
        if rnd.role == "judge":
            judge = selection.get("judge") or room["judge"]
            jpayload = {"system": rnd.system or JUDGE_SYSTEM, "messages": [
                {"role": "user", "content": _build_judge_prompt(
                    prompt, prior, absent, rubric_file=rnd.rubric_file,
                    instruction=(rnd.instruction or None))}]}
            meta: dict = {"round_id": round_id}
            if rnd.judge_kind:
                meta["judge_kind"] = rnd.judge_kind        # UI label: synthesis | map | divergence
            if absent:                                     # who dropped + WHY (was lost before — only
                meta["absent"] = [{"speaker": s, "error": e} for s, e in absent]   # reached the judge prompt)
            judge_used = judge
            try:
                reply = _call_judge(judge, jpayload, effort, efforts.get(judge), artifacts_dir=art_dir)
            except Exception:  # noqa: BLE001 — judge down → fall back to a seat that answered
                fallbacks = [s for s, _ in prior if s != judge]
                if not fallbacks:
                    raise
                judge_used = fallbacks[0]
                reply = _call_judge(judge_used, jpayload, effort, efforts.get(judge_used), artifacts_dir=art_dir)
                meta["judge_fallback_from"] = judge
            meta["model"] = providers.provider(judge_used).model
            meta["reasoning_effort"] = _effort_label(judge_used, efforts.get(judge_used))
            meta.update(_reply_meta(reply))
            _stamp_artifacts(meta, room_id, reply.text, art_dir)   # write + stamp before append (32.3)
            transcript.append(transcript.make_turn(mode.turn_mode, "judge", judge_used, reply.text, meta), path)
            last = reply.text
            continue

        # ai / ai-raw round. Panel rounds (ai-raw) honour the blind/transcript toggle
        # (params.panel_context); a transcript-aware panel READS forward context but its
        # answers STAY ai-raw (excluded from forward context) — reads, never writes.
        speakers = _resolve_participants(rnd, selection, room, target)
        eff_ctx = rnd.context
        if rnd.role == "ai-raw" and selection.get("panel_context"):
            eff_ctx = selection["panel_context"]
        # cache the big re-sent transcript prefix (converse / yes-and / transcript-panel)
        cache_this = settings.PROMPT_CACHE and eff_ctx == "transcript"
        if rnd.degrade:
            with ThreadPoolExecutor(max_workers=max(1, len(speakers))) as ex:
                results = list(ex.map(
                    lambda s: _panelist(s, _round_payload(rnd, s, prompt, doc_block, path, room, human_label, eff_ctx),
                                        effort, efforts.get(s), tools=rnd.tools, max_tokens=rnd.max_tokens,
                                        cache=cache_this, artifacts_dir=art_dir),
                    speakers))
        else:   # non-degrading single seat (converse): a failure propagates, as before
            s0 = speakers[0]
            reply0 = providers.call_model(
                s0, _round_payload(rnd, s0, prompt, doc_block, path, room, human_label, eff_ctx),
                tools=rnd.tools, effort=effort, max_tokens=rnd.max_tokens, reasoning_effort=efforts.get(s0),
                cache=cache_this, artifacts_dir=art_dir)
            results = [(s0, reply0, None)]

        prior, absent = [], []
        for speaker, reply, err in results:
            if err is not None:
                absent.append((speaker, err))
                continue
            p = providers.provider(speaker)
            meta = {"model": p.model, "reasoning_effort": _effort_label(speaker, efforts.get(speaker)),
                    **_reply_meta(reply)}
            if mode.turn_mode != "converse":
                meta = {"round_id": round_id, **meta}
            if rnd.role == "ai-raw":
                meta["is_panelist_raw"] = True
                meta["tools"] = (p.auth_mode == "cli")      # only cli actually searched
            else:
                _stamp_artifacts(meta, room_id, reply.text, art_dir)   # forward replies auto-save (converse/yes-and)
            transcript.append(transcript.make_turn(mode.turn_mode, "ai", speaker, reply.text, meta), path)
            prior.append((speaker, reply.text))             # judge sees text only — never reasoning
            last = reply.text
        if rnd.degrade and not prior:
            raise RuntimeError("every panelist failed — nothing to judge")
    return last


# ---- wrappers (thin mode-specs over run_mode; signatures preserved) ---------
def research(room_id: str, prompt: str, panel: list[str] | None = None,
             judge: str | None = None, effort: str = "medium",
             panel_context: str | None = None) -> str:
    """Fusion: a parallel panel + a judge synthesis. Degrades gracefully (a failed
    panelist → absent, never silent agreement; abort only if zero return). `panel_context`
    (blind/transcript, default blind) is the per-mode panel-sees-conversation toggle."""
    room = rooms.load_room(room_id)
    panel = panel if panel is not None else room["participants"]
    judge = judge or room["judge"]
    if not panel:
        raise ValueError("no panelists selected for this room")
    if not judge:
        raise ValueError("no judge selected for this room")
    return run_mode(room_id, FUSION_MODE, prompt,
                    {"panel": panel, "judge": judge, "panel_context": panel_context}, effort=effort)


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
                 judge: str | None = None, effort: str = "medium",
                 panel_context: str | None = None) -> str:
    """Two seats answer the same task (ai-raw); the judge produces a short divergence note
    (does NOT merge) so the reader can choose which full answer to read."""
    room = rooms.load_room(room_id)
    judge = judge or room["judge"]
    if not seats or len(seats) != 2:
        raise ValueError("side-by-side needs exactly two models")
    if not judge:
        raise ValueError("no judge selected for this room")
    for s in seats:
        providers.provider(s)          # validate each; raises ValueError if unknown
    return run_mode(room_id, SIDE_BY_SIDE_MODE, prompt,
                    {"seats": list(seats), "judge": judge, "panel_context": panel_context}, effort=effort)


def mapping(room_id: str, prompt: str, panel: list[str] | None = None,
            judge: str | None = None, effort: str = "medium",
            panel_context: str | None = None) -> str:
    """Fusion's blind panel, but the judge EXPOSES the landscape (consensus / divergences /
    unique signal / takeaway) instead of merging — same rails, swapped judge guidance."""
    room = rooms.load_room(room_id)
    panel = panel if panel is not None else room["participants"]
    judge = judge or room["judge"]
    if not panel:
        raise ValueError("no panelists selected for this room")
    if not judge:
        raise ValueError("no judge selected for this room")
    return run_mode(room_id, MAPPING_MODE, prompt,
                    {"panel": panel, "judge": judge, "panel_context": panel_context}, effort=effort)


def yes_and(room_id: str, prompt: str, seats: list[str], effort: str = "medium",
            human_label: str = "human") -> str:
    """Two transcript rounds, an ordered pair: A answers seeing the room; B answers seeing
    the room INCLUDING A's turn (A's answer is a normal forward turn, so build_context shows
    it to B). Both forward (the user's next turn sees both)."""
    if not seats or len(seats) != 2:
        raise ValueError("yes-and needs exactly two models (an ordered pair: A then B)")
    if seats[0] == seats[1]:
        raise ValueError("yes-and needs two DIFFERENT models")
    for s in seats:
        providers.provider(s)          # validate each; raises ValueError if unknown
    return run_mode(room_id, YES_AND_MODE, prompt, {"seats": list(seats)},
                    effort=effort, human_label=human_label)
