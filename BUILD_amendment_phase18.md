# BUILD amendment — research token ceiling + truncation surfacing (phase 18)

> **Status: BUILT.** Build record (companion to [BUILD.md](BUILD.md) and the phase 11–17
> amendments). Direct follow-on to Phase 17: turning on web search made agentic models chattier,
> and the fixed 8192 converse ceiling silently truncated their answers.

---

## The bug (observed)

A research round: GLM-5.2 (via OpenRouter, web search on) returned **77 sources** but only a
paragraph of *search-planning preamble* ("I'll conduct a systematic search… Let me search for a few
more specific areas…") — no synthesis. The answer was **truncated at the token ceiling** mid-plan,
and nothing in the UI said so: every call (research panelists included) used
`CONVERSE_MAX_TOKENS = 8192`, and we captured **no `finish_reason`**, so a clipped answer was
indistinguishable from a complete one. (Separately, Claude — the judge — fell back to a panelist
because its API credit ran out; that's the designed judge-fallback path working, not a bug.)

## 18.1 — A separate, larger research budget
- `settings.RESEARCH_MAX_TOKENS` (env `RESEARCH_ROOM_RESEARCH_MAX_TOKENS`, **default 32768**),
  distinct from `CONVERSE_MAX_TOKENS` (8192, unchanged for converse/margin).
- `providers.call_model` gained a `max_tokens` passthrough → the adapter request body.
  `modes.research` passes `RESEARCH_MAX_TOKENS` for **both** the panelists (`_panelist`) and the
  judge (`_call_judge`, including its tools-off fallback). Converse/margin pass nothing → keep 8192.
- **Generous, not infinite — on purpose.** `max_tokens` is an output ceiling, not a target (the
  model still stops at `finish_reason: stop`), but an "enormous" value isn't free: it can exceed a
  model's own max-output and **400** on some direct providers (worse than truncation — the panelist
  drops to "absent"); it removes the **circuit breaker** on a runaway agentic loop (×N panelists);
  and it crowds the judge's large input against the context window. 32768 clears any real synthesis
  while staying portable; raise per your model set via the env var.

## 18.2 — Capture `finish_reason` (so truncation is never silent)
- Both adapters return a 6th value, a **canonical** `finish_reason`: openai passes its vocab
  through (`stop` / `length` / `tool_calls` / `content_filter`); anthropic's `stop_reason` is mapped
  (`max_tokens`→`length`, `tool_use`→`tool_calls`, `end_turn`/`stop_sequence`→`stop`,
  `refusal`→`content_filter`). `ModelReply.finish_reason` carries it; `_reply_meta` stamps
  `meta.finish_reason` (panel/judge/converse); margin stamps it inline. Mock returns `"stop"`.
- Rides JSONL meta; excluded from `build_context` by construction (only `turn.text` is serialized).

## 18.3 — Truncation badge (UI)
- `truncBadge(meta)` → a non-interactive **⚠ truncated** (`length`) / **⚠ incomplete**
  (`tool_calls`) badge, added first in the turn footer; a clean `stop` (or absent / old turn) shows
  nothing and does **not** force a footer on its own. Warning-tinted; the cause is in the `title`.

## Gate
- Engine `engine_phase18.py`: finish_reason normalization (both backends), `max_tokens` passthrough
  to the request body, `modes.research` threading `RESEARCH_MAX_TOKENS` into panelists + judge
  (spy on `providers.call_model`), end-to-end `meta.finish_reason` read-back.
- Browser `browser_phase18.py`: badge renders for `length`/`tool_calls`, absent for `stop`/empty (no
  forced footer), and a clean mock round carries no badge.
- Full suite green; DOM ids intact; `.reasoning-*` classes unchanged.

---

## As-built notes

- **Adapter tuple is now 6** `(text, reasoning, usage, served_model, search, finish_reason)`. It's
  grown one element per provenance phase (11/16/17/18) and is getting unwieldy — flagged for a later
  refactor to a small `ChatResult` dataclass, deferred now to keep this change low-risk (the tuple
  is internal to adapters↔`call_model` plus three test unpackings, all updated).
- **Why a separate budget, not just bumping `CONVERSE_MAX_TOKENS`:** a converse reply hitting 32k is
  almost always a runaway, and the margin is a quick side-question — they want the tighter ceiling
  as a guard. Research is where length is the goal. Two knobs, two defaults.
- **`finish_reason` is stored even when `"stop"`** (honest provenance: "it finished cleanly", not
  "unknown/old turn"). The badge keys only off `length`/`tool_calls`, and the footer null-check
  ignores `stop`, so a clean turn gets no footer from this alone — asserted in the browser gate.
- **Immediate mitigation that needs no deploy:** `RESEARCH_ROOM_MAX_TOKENS` already let the user
  raise the (then-shared) ceiling at launch; 18.1 makes the research ceiling generous by default so
  no env tweak is needed for thorough rounds.
- **Mitigation, not a fix, for agentic over-search.** 77 searches on one panelist is a lot; the
  bigger ceiling lets the answer complete but doesn't cap search count (and ×N panelists multiplies
  the OpenRouter bill). Left for the deferred cost-estimate / a future per-round search cap.
- **Gate:** `engine_phase18.py` + `browser_phase18.py`. Full suite **23/23** (16 browser + 7
  engine), DOM ids intact, `.reasoning-*` unchanged.
