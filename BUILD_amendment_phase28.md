# BUILD amendment — reasoning visibility: token capture, thinking-level stamp, pill popover, dial guard (phase 28)

> **Status: BUILT.** Prompted by a live diagnosis: Claude (via the API row) answered fast and shallow
> next to claude.ai. Root cause — `claude-or` had its **reasoning toggle OFF**, so no reasoning param
> (and no effort) was ever sent; the per-room "max" effort was a silent no-op, and nothing in the
> transcript recorded that. Four adds make reasoning legible and stop the dial from misleading.

---

## 28.1 — Capture reasoning tokens
`openai_style.chat` now reads `usage.completion_tokens_details.reasoning_tokens` → `usage.reasoning`
(rides the turn's `meta.usage`, like cost). It's the ACTUAL think — the real signal vs the *requested*
level. On the RR Loom 4 turns this reads **0/none**, which would have flagged the problem instantly.

## 28.2 — Stamp the requested thinking level
`run_mode` stamps `meta.reasoning_effort` on every output turn (panel / converse / judge):
- **`off`** — the provider's reasoning toggle is off, so no effort is sent (the dial is inert);
- the **override** value when the per-room effort is set;
- **`default`** — reasoning on, model default.

So a transcript records what thinking was asked for. `meta` only → never serialized into forward
context (asserted).

## 28.3 — Expose `provider.reasoning`
`/participants` now returns each row's `reasoning` flag, so the UI can tell when an effort dial is inert.

## 28.4 — Model-pill metadata popover
Hovering an output turn's model pill opens a popover (singleton `#turn-popover`, mirrors the
model-square popover): served model · **Thinking** (requested level) · **Reasoning** (actual tokens) ·
Tokens · Cost · Finish, plus a **"view thinking"** button when a trace exists (toggles the footer
disclosure). Keeps the footer clean while making the per-turn metadata reachable.

## 28.5 — Inert effort-dial guard
The model-square effort dial is greyed + disabled, with a note *"reasoning off — enable 'show
reasoning' in models"*, whenever the model's reasoning toggle is off. The exact trap that misled the
diagnosis: the dial was settable but inert.

## Gate
- **Engine** `engine_phase28`: `reasoning_tokens` captured into `usage.reasoning` (absent when the model
  didn't reason); `meta.reasoning_effort` stamped `off` / `default` / `<effort>` per turn (incl. judge);
  neither leaks into `build_context`.
- **Browser** `browser_phase28`: the pill popover shows Thinking / Reasoning / Tokens / served model and
  a working "view thinking"; a reasoning-off model shows a greyed, disabled dial + note, and re-enabling
  reasoning restores a live dial.
- Full suite green (16 engine + 23 browser + the rollback race).

## Housekeeping
- README: per-turn reasoning visibility (the pill popover: requested level + actual reasoning tokens +
  the trace), and the inert-dial guard.
- DEFERRED: surfacing cli-runner reasoning (Grok thinks via its own runner; we mark such turns `off`
  because no api reasoning param is sent/captured) — a later add if a cli path exposes its trace/tokens.

---

## As-built notes

- **The fix for the user was config, not code** (tick "show reasoning" on `claude-or`); this phase is
  the *visibility* so it can't happen silently again. `usage.reasoning` = 0 + `meta.reasoning_effort` =
  `off` together make the failure self-evident on the turn.
- **Faithfulness:** adding `usage.reasoning` broke two fixtures that asserted an exact `usage` dict
  (`engine_phase19`, `engine_phase20`) — both mock responses already included `reasoning_tokens`, so the
  assertions were updated to expect the now-captured field. Adding `meta.reasoning_effort` to output
  turns touched no existing assertion (they check specific keys). All other `engine_phase*` pass
  unchanged.
- **Popover, not relocation.** The footer keeps its `▸ thinking` disclosure (the trace control + the
  `.reasoning-*` classes `browser_reasoning` relies on); the pill popover ADDS the metadata view and a
  convenience "view thinking" button that toggles the same disclosure. So nothing load-bearing moved —
  `browser_phase16` (pill text + title) and `browser_reasoning` (disclosure) pass unchanged. The pill is
  now `cursor: pointer` and opens the popover on hover/click.
- **`off` for cli seats.** `_effort_label` returns `off` when `provider.reasoning` is false — including
  cli rows (Grok), which DO reason via their runner but expose no api reasoning param to us. Honest for
  the api path; surfacing cli reasoning is deferred.
- **Dial guard reads the new flag.** `effortSection` greys + disables when `providerOf(k).reasoning` is
  false; the effort options still render (from metadata) so you can see what *would* be available, just
  inert until reasoning is enabled.
- **Gate:** `engine_phase28.py` + `browser_phase28.py`. Full suite green (16 engine + 23 browser + the
  rollback race proof).
