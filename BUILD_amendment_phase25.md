# BUILD amendment — interaction-pattern framework + side-by-side (phase 25)

> **Status: BUILT.** Companion to [BUILD.md](BUILD.md), the roadmap (Cluster 2), and `modes.py`.
> As-built notes at the foot.

---

Turned "interaction pattern" into a **category** you can extend, not a set of hand-written functions.
`modes.py` now has a **round/mode layer** that `research`/`converse` fold into, plus **side-by-side** as
the first new mode (participant subset + a swapped judge instruction) — proving the rails generalize.

**A round** = `participants` (all / subset / one / judge) · `context` (`blind` / `transcript`) · `flow`
(parallel; sequential is an extension point) · `instruction` (the appended prompt-modifier) · `role`
(`ai` forward / `ai-raw` = `is_panelist_raw`, out of forward context / `judge` forward). **A mode** =
ordered rounds + a `gate` (`single`; loop is future). Every pattern is rounds + a gate.

**Invariant by construction:** the per-round `instruction` is a prompt-modifier (out of context, like
the no-search guard); model outputs + the judge synthesis are `turn.text` (forward as normal); `ai-raw`
outputs stay out of forward context. Modes shape *how* models are prompted, never *what* serializes
forward.

## 25.1 — The round/mode model + executor
`Round` / `Mode` dataclasses + a single **`run_mode(room_id, mode, prompt, selection)`** executor that
*extracts* (not rewrites) the existing primitives: parallel `ThreadPoolExecutor` + `_panelist`; the
judge round via `_build_judge_prompt` (now taking the round's instruction) + `_call_judge` (both
fallbacks kept); degradation (failed seat → absence, abort only if all fail); meta-isolation
(`_reply_meta` on every output, judge sees text only); `ai-raw` → `is_panelist_raw` → out of forward
context. `flow: sequential` is expressed but not implemented (clear extension point for 26).

## 25.2 — Migrate converse + fusion onto the layer
`research()` and `converse()` are now **thin wrappers** that build a mode-spec and call `run_mode`,
**signatures unchanged** — so `engine_phase*` call them unchanged. Fusion = `[{all, blind, parallel,
PANEL_INSTRUCTION, ai-raw}, {judge}]`; converse = `[{one, transcript, ai}]`. The faithfulness gate:
**all current engine tests pass unchanged**.

## 25.3 — Side-by-side (the first new mode)
`[{subset[2], blind, parallel, PANEL_INSTRUCTION, ai-raw}, {judge, DIVERGENCE_NOTE, SIDE_SYSTEM}]`. The
judge instruction is a divergence note (not the synthesis rubric): two visible raw answers + a short
"where they differ" note; no merge, no winner. Exercises the participant-subset path + a swapped judge
instruction + system through the same executor.

## 25.4 — Unified mode selector
One `#mode` selector (Converse · Fusion · Side-by-side) replaces the converse/research radio; params
reveal contextually (converse → addressee; fusion → judge + panel; side-by-side → two-seat picker +
judge). The selector produces a **mode-selection object** (`{mode, prompt, params}`) sent to **one
dispatch endpoint** `POST /rooms/{id}/run` → the mode wrappers → `run_mode`. Selection is decoupled from
execution: the dropdown is the v1 producer; a future trajectory-graph is a second producer of the same
object, so nothing engine-side changes when the graph lands.

## Gate
- **Engine:** `engine_phase*` pass **unchanged** (faithfulness); `engine_phase25` covers `run_mode`
  directly — side-by-side produces two `ai-raw` answers + a divergence-note judge turn; `ai-raw`
  excluded from `build_context`; judge sees text only; degradation + judge fallback hold; converse runs
  through the same executor.
- **Browser:** `browser_phase25` — the selector lists the modes + reveals params contextually;
  side-by-side renders two answers + a divergence note and dispatches through `/run`.
- Full suite green (13 engine + 21 browser).

## Housekeeping
- README: the round/mode framework, the three live modes, the selection-object ↔ execution decoupling.
- DEFERRED / roadmap: Mapping (26, judge instruction → expose), Yes-and (26, fills the sequential
  extension point), blind/transcript panel toggle (26), Debate (later, gate → loop), trajectory graph
  (second producer of the mode-selection object).

---

## As-built notes

- **Faithfulness held — `engine_phase*` pass UNCHANGED.** The migration reproduces the exact human-turn
  metas (`{round_id}` for grouped modes, `{addressed_to}` for converse), the exact ai/judge turn metas
  (fusion: `round_id` + `is_panelist_raw` + `model` + `tools` + reply-meta; converse: `model` +
  reply-meta), the byte-identical fusion judge prompt (the `instruction=None` path is the old rubric +
  output text verbatim), and both fallbacks. The legacy `/research` + `/converse` endpoints stay for
  back-compat; the UI moved to `/run`.
- **Degrade vs propagate is a round flag.** Fusion/side-by-side panels are `degrade=True` (failure →
  absence via `_panelist`, abort only if all fail). Converse is a single-seat `degrade=False` round that
  calls `call_model` directly so a failure propagates exactly as before (the server maps it to 502).
  That's the only behavioural fork between the two ai-round shapes; everything else is shared.
- **The judge round is parametrized by instruction + system.** `_build_judge_prompt(..., instruction)`:
  `None` → the synthesis rubric + standard fusion output (unchanged); a string → that text as the OUTPUT
  section. Side-by-side passes `DIVERGENCE_NOTE` + a distinct `SIDE_SYSTEM` (plain `JUDGE_SYSTEM` says
  "synthesize into one", which would fight "do not merge").
- **`turn_mode` drives UI grouping, not behaviour.** Fusion + side-by-side use `turn_mode="research"`
  (grouped round: prompt + panels + judge), converse uses `"converse"` (individual turns) — matching the
  existing `groupTurns`. Side-by-side's judge turn renders in the "synthesis" slot; the divergence-note
  text itself makes its role clear (a mode-aware label is deferred polish).
- **Selection ↔ execution decoupled, as specced.** `buildSelection(mode, text)` (client) produces
  `{mode, prompt, params}`; `RunBody` (server) consumes it and dispatches to the wrappers. The dropdown
  and the round-spec are deliberately separate objects, so the future graph drops in as a second
  producer with no engine change.
- **Sequential is declared, not shipped.** `Round.flow` carries `"sequential"` but `run_mode` only
  implements parallel — the explicit extension point for Yes-and (26). No untested sequential code ships.
- **Test churn from the selector.** Ten browser tests that drove the old `input[name="mode"]` radio were
  updated to `select_option("#mode", "fusion"|"converse")` (research → fusion); one default-mode
  assertion switched to reading the selector value. DOM ids for the param groups (`#research-opts`,
  `#converse-opts`, `#effort`, `#judge-pick`, `#panel-pick`) are unchanged; `#sxs-opts` + `#sxs-pick` +
  `#sxs-judge` are new.
- **Gate:** `engine_phase25.py` + `browser_phase25.py`; faithfulness via the unchanged `engine_phase*`.
  Full suite green (13 engine + 21 browser).
