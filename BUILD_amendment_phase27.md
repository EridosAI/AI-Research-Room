# BUILD amendment — round provenance + roll-back-last-round (phase 27)

> **Status: BUILT.** Prompted by a live bug: a side-by-side ran with the panel blind even though the
> "panel sees conversation" toggle was checked (a stale pre-Phase-26 server silently dropped
> `panel_context`), and there was (a) no way to tell from the transcript what move actually ran, and
> (b) no way to undo the poisoned round short of hand-editing `main.jsonl`. Two small adds fix both.

---

## 27.1 — Round provenance on the transcript
`run_mode` stamps the **mode-selection snapshot** on the round-head turn's meta:
`meta.selection = {mode, panel_context?, seats?, panel?, judge?, target?}` (only the params that
apply). So a transcript is self-describing about what move ran — including whether the panel saw the
conversation. It's `meta` only, so `build_context` never serializes it forward (invariant intact).
The UI renders it on the round's prompt line: e.g. **`side-by-side · panel saw chat`**.

## 27.2 — Roll back the last round
- `rooms.rollback_last_round(room_id)` removes the last round — every turn from the **last human turn
  to the end** — from `main.jsonl`. A round-head human turn carries the `round_id`, so a grouped round
  (fusion / mapping / side-by-side) is removed whole (prompt + panels + judge); converse / yes-and
  remove the prompt + its answer(s). This is the **one** deliberate transcript rewrite (otherwise
  append-only), so the removed turns are appended to **`rolledback.jsonl`** first — nothing is lost.
  `last_read_pos` is clamped to the new length.
- `POST /rooms/{id}/rollback` (main room lock; serializes with rounds). Returns the updated transcript.
- UI: a **"↶ undo round"** button in the room header, disabled when the room is empty, behind a
  `confirm()` that names how many turns it will remove and that they're recoverable.

## Gate
- **Engine** `engine_phase27`: provenance stamped (mode + panel_context + seats/judge) and NOT leaked
  into `build_context`; rollback removes a grouped round whole, preserves removed turns in
  `rolledback.jsonl`, keeps the prior history, clamps `last_read_pos`, and errors on an empty room.
- **Browser** `browser_phase27`: a side-by-side with the toggle on shows `side-by-side · panel saw chat`
  on the round; the undo button removes the round (4 turns), re-disables, and the removed turns land in
  `rolledback.jsonl`.
- Full suite green (15 engine + 22 browser); all prior `engine_phase*` pass unchanged.

## Housekeeping
- README: round provenance label + the undo-last-round control (append-only with one explicit,
  backed-up rewrite).
- DEFERRED: a full **undo stack / re-apply from `rolledback.jsonl`** (this ships single-level undo with
  a recoverable log, not a redo UI); selective mid-transcript edit/delete stays out (rollback is
  last-round only, which matches the "poisoned my last round" need).

---

## As-built notes

- **Provenance lives on the round head, not a new turn.** The human turn that starts every send is the
  natural anchor; adding `meta.selection` there cost nothing and added no turn. Existing tests that
  inspect the human turn check specific keys (`round_id` / `addressed_to`), not full-dict equality, so
  the extra key was faithfulness-safe — the whole `engine_phase*` suite passed unchanged.
- **`panel_context` is recorded even when "blind".** The snapshot includes `panel_context` whenever the
  selection carries it (panel modes always do — "blind" by default), so the transcript distinguishes
  "ran blind" from "ran transcript" rather than leaving it ambiguous. (Converse/yes-and don't set it →
  omitted.) This is exactly the bit that was missing when we had to *infer* the blind run from Claude's
  wording.
- **Rollback granularity = "last human turn → end".** One rule covers every mode: grouped rounds put
  the `round_id` on the head human turn so the whole group goes; converse/yes-and/file-drops go back to
  their prompt. Known edge: a promoted-margin note sitting after the last human turn would be swept with
  that exchange — rare, and the confirm() shows the turn count first.
- **The rewrite is contained + reversible.** `transcript.py` stays append-only; `rooms.rollback_last_round`
  is the single rewriter, and it appends the removed turns to `rolledback.jsonl` before truncating, so a
  mis-click is recoverable (manually, for now). The endpoint takes the main room lock, so it can't race a
  round in the same room.
- **UI restraint.** One header button next to "models"/"margin", `confirm()`-gated with the count, and
  it adopts the returned transcript so the view updates immediately (no manual refresh — unlike the
  hand-edit we did before). Round labels reuse the existing `whoLine` extra slot, so no layout change.
- **Concurrency verified, not just asserted.** `tests/rollback_race.py` (HTTP, no browser) fires a
  slow fusion round (panel = sleeping `mockslow`) in a thread, then fires `/rollback` the instant the
  round's human turn is on disk — i.e. mid-append, lock held. It confirms rollback **blocks** on the
  lock until the round completes, then removes a **complete** 3-turn round (`[human, ai-raw, judge]`)
  leaving `main.jsonl` empty. Were the lock not covering the whole append, rollback would have removed
  only the human turn and the panel+judge would have landed orphaned — the check distinguishes the two.
  So: a round in flight makes undo *wait* (it can't truncate a half-written round). The UI doesn't
  disable undo during an in-flight round — it waits — which is safe by the lock; the only cosmetic nit
  is the confirm()'s turn-count is computed from the on-screen (pre-round) state.
- **Gate:** `engine_phase27.py` + `browser_phase27.py` + `rollback_race.py`. Full suite green
  (15 engine + 22 browser + the race proof).
