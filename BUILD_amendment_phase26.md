# BUILD amendment — mapping, yes-and, panel context toggle, judge labels (phase 26)

> **Status: BUILT.** Builds on the Phase-25 round/mode framework — all four are config-level adds on
> the proven rails, no executor surgery. As-built notes at the foot.

---

Four adds: **mapping** (fusion's judge swapped to *expose*), **yes-and** (two transcript rounds), the
**blind/transcript panel toggle**, and a **mode-aware judge label**. Invariant unchanged: instructions
are prompt-modifiers (out of context), outputs + the judge turn are `turn.text`, `ai-raw` stays out of
forward context.

## 26.1 — Mapping mode
`MAPPING_MODE` = fusion's blind panel + a judge round with `references/mapping_rubric.md` (four parts:
Consensus / Divergences-mapped / Unique signal / Takeaway), a `MAPPING_OUTPUT` instruction (expose,
don't merge, don't pick a winner), and `MAPPING_SYSTEM` (a judge that is also a panelist treats its own
answer as one voice among many). No new participant logic — reuses fusion's path. `judge_kind="map"`.
Source attribution deferred (shared with verification — needs a `meta`→judge citations channel).

## 26.2 — Yes-and mode
`YES_AND_MODE` = `[{one:A, transcript, ai}, {one:B, transcript, ai, YES_AND_INSTRUCTION}]`, an ordered
pair. A answers seeing the room; B answers seeing the room **including A's turn** — A's answer is a
normal forward `ai` turn, so `build_context` shows it to B (no intra-round threading). Both forward.
The `flow: sequential` stub stays **unfilled** — yes-and didn't need it.

## 26.3 — Blind / transcript panel toggle
The panel round's `context` is exposed as a per-mode toggle (`params.panel_context`, default `blind`)
on the panel modes (fusion, mapping, side-by-side). With `transcript`, each panelist's payload is
`build_context` (+ the panel instruction) — panelists see room **history** but **not each other**
(parallel; their current answers aren't in the transcript yet). **Invariant:** answers stay `ai-raw`
regardless of context — reads, never writes.

## 26.4 — Mode-aware judge label
`meta.judge_kind` (set from the mode: synthesis / map / divergence) renders as the judge turn's label,
so scrollback says what move each judge turn was. Retires the Phase-25 defer (side-by-side's note no
longer reads as a generic "synthesis").

## Gate
- **Engine** `engine_phase26`: mapping → four-part map judge turn (panel ai-raw, judge text-only,
  `judge_kind="map"`, neutral-self system); yes-and → A then B with B seeing A via forward context, no
  sequential code; transcript-panel keeps answers `ai-raw` (forward-context exclusion asserted with the
  toggle on) while a blind panel does not see the room; `judge_kind` per mode. All `engine_phase*` pass
  unchanged.
- **Browser** `browser_phase26`: selector lists Mapping + Yes-and; params reveal contextually; mapping's
  judge turn is labelled "map"; yes-and posts A then B via `/run`.
- Full suite green (14 engine + 21 browser).

## Housekeeping
- README: the three new modes' shapes + the judge labels; the sequential stub remains for a future
  intra-round-sequential mode.
- DEFERRED: source attribution (mapping) + verification pass share a `meta`→judge citations channel
  (build once, both use it); Debate = a panel mode with the gate flipped to loop; trajectory graph =
  second producer of the mode-selection object.

---

## As-built notes

- **Faithfulness held — `engine_phase*` pass unchanged.** The only behaviour-touching change to existing
  modes was generalizing `_build_judge_prompt` to take `rubric_file` + `instruction`; fusion now passes
  `judge_rubric.md` + `FUSION_OUTPUT` (the old hardcoded output paragraph, verbatim) which reconstructs
  the pre-Phase-26 prompt **byte-identically** (HOW TO JUDGE / rubric / blank / OUTPUT / para — same
  order, same text). Side-by-side (rubric_file=None, instruction=DIVERGENCE_NOTE) is unchanged too.
- **Mapping is pure config.** A new mode constant + a rubric file + a system/output string; it reuses
  fusion's panel round and the same judge branch. The four-part structure lives in the rubric (HOW TO
  JUDGE); `MAPPING_OUTPUT` is the short "expose, don't merge" OUTPUT line; the neutral-self note is the
  system. `judge_kind="map"`.
- **Yes-and needed two small generalizations, no sequential code.** (1) A `Round.seat` index so a `one`
  round picks `selection["seats"][seat]` (the ordered pair) instead of the converse `target`. (2)
  `_round_payload` now appends a transcript round's `instruction` to the `build_context` body (converse
  passes `instruction=""` → no append → unchanged; yes-and's B appends `YES_AND_INSTRUCTION`). B sees A
  purely through forward context — A's turn is a normal forward `ai` turn, re-read by `build_context` at
  B's round. `YES_AND_MODE` uses `turn_mode="converse"` so the two answers render as stacked individual
  turns (back to the user), both forward.
- **Panel toggle is an effective-context override, role untouched.** `run_mode` computes
  `eff_ctx = selection["panel_context"] or rnd.context` for `ai-raw` rounds only, and passes it to
  `_round_payload`; the role stays `ai-raw`, so a transcript-aware panel's answers are still excluded
  from forward context (asserted). Reads, never writes — otherwise parallel panelists would contaminate
  the next round through the transcript.
- **`research()` gained a `panel_context` kwarg** (default None → blind), so the server can pass the
  toggle through to fusion without touching `run_mode`'s call sites. Default-None keeps the wrapper
  faithful.
- **One stale assertion updated.** `browser_phase25` asserted the exact 3-mode option list; Phase 26
  adds two modes, so it now checks the three are a subset. (Engine faithfulness assertions were
  untouched and still pass.)
- **Gate:** `engine_phase26.py` + `browser_phase26.py`; faithfulness via the unchanged `engine_phase*`.
  Full suite green (14 engine + 21 browser).
