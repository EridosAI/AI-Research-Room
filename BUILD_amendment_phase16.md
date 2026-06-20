# BUILD amendment — served-model capture + per-turn model pill (phase 16)

> **Status: BUILT.** Build record (companion to [BUILD.md](BUILD.md) and the phase 11 / 13 / 14 / 15
> amendments). Spec preserved verbatim; as-built notes appended at the foot. Current architecture is
> in [README.md](README.md).

---

Extends phase 11 (visible reasoning) — **same seam, one more field.** The adapters already return a
`ModelReply` and every call site stamps `_reply_meta(reply)` onto the turn, so threading the
API-reported model out is a one-field addition, not a new pathway. Capture is uniform across
providers; display reuses the reasoning disclosure's row.

**Distinct from the existing `meta.model`.** `meta.model` already exists — the *configured* model
string, shown after the speaker in the turn header (`deepseek · deepseek-v4-pro`). This adds
`meta.served_model`: what the API *reported* serving the turn (`response.model`). The two are
usually equal; the value is that when they aren't, the mismatch is now **visible and recorded** —
the model's prose lies about its own identity, `response.model` doesn't.

**Invariant holds, untouched.** `build_context` serializes only `turn.text` and never reads `meta`,
so `served_model` is excluded from forward context **by construction** — same as `meta.reasoning`.
No `forward_turns` change.

## 16.1 — Capture (backend)
- `ModelReply` gains `served_model: str | None`.
- **`openai_style`** adapter: after parsing the response JSON, `served_model = data.get("model")`
  (DeepSeek / Kimi / OpenRouter all echo it). **`anthropic_style`**: same — `data.get("model")`
  (Claude responses carry a top-level `model`). Set it on the returned `ModelReply`.
- **Grok (`cli`)**: `grok -p` returns no model field → leave `served_model = None`.
- Extend **`_reply_meta(reply)`** to also emit `served_model` onto the turn meta when present. One
  change covers all surfaces — research panels, synthesis/judge, converse, margin.
- Persistence: the turn's `meta` is already serialized to JSONL whole, so `served_model` persists
  with no schema work. Confirm on read-back.

Done when: a turn from an API provider carries `meta.served_model` equal to the response's `model`;
the CLI path leaves it absent; older turns without it load fine; and a turn with `served_model` set
yields a `build_context` body containing the answer `text` and **zero** served-model string.

## 16.2 — Per-turn "model" pill (frontend)
- In `renderConverse`, after `.body`, append a `.turn-footer` flex row holding the **"thinking"
  toggle** and a new **"model" pill** side by side. Render the reasoning *body* **full-width below**
  the footer — not inside the flex row.
  - Light refactor of `reasoningBlock`: keep the `.reasoning-toggle` button, the `.reasoning-body`
    element, and the click→toggle wiring **exactly as named** (`browser_reasoning` keys off both
    classes) — just place the toggle in the footer and the body after it.
- `modelPill(t)`: render only if `t.meta?.served_model`. A small **non-interactive** `<span>` styled
  like `.reasoning-toggle`, text **"model"**, served string revealed on hover via the native `title`
  attribute. Order: thinking then model.
- Render the footer only if at least one pill exists. Apply the same footer + pill to the research
  **panel** and **synthesis/judge** renders; margin optional.
- Sanitisation: the label is the static word "model"; the served value lives in a `title` attribute /
  `textContent` only — **never** innerHTML.
- Optional polish: if `served_model` ≠ the header's configured `meta.model`, give the pill a subtle
  warning tint.

Done when: a turn with a served model shows a "model" pill beside "thinking"; hovering reveals the
served string; the pill is absent when `served_model` is; "thinking" still expands (now full-width
below the pill row); `browser_reasoning` passes unchanged.

## Gate
- **Engine:** extend the stubbed-httpx adapter test — stub a response with `model: "served-x"`,
  assert the turn's `meta.served_model == "served-x"` and that it's excluded from `build_context`.
- **Browser:** new `tests/browser_phase16.py` — the footer renders a "model" pill beside "thinking",
  the pill's `title` equals the served model, and the pill is absent when `served_model` is.
- Full suite green; DOM ids intact; `.reasoning-toggle` / `.reasoning-body` classes unchanged.

## Housekeeping
Append as-built notes here; update the README reasoning/provenance section; add `browser_phase16`.

---

## As-built notes (deviations / confirmations worth recording)

- **The helper was already `_reply_meta`.** Phase 11's optional rename had already happened, so
  served_model slotted in as a third `if getattr(reply, …)` block — research panel, judge, and
  converse all pick it up from that one edit, exactly as specced.
- **Adapters return a 4-tuple, not a `ModelReply`.** The spec says "set it on the returned
  `ModelReply`", but the adapters return `(text, reasoning, usage)` and `call_model` builds the
  `ModelReply`. So the faithful change was extending the tuple to
  `(text, reasoning, usage, served_model)` (`data.get("model") or None`) in both adapters, and
  `call_model` stamps it onto `ModelReply(..., served_model=served)`. The two `.chat()` unpackings in
  `call_model` and the three in `engine_phase11` were updated to the 4-tuple; `test_provider` ignores
  the return so it was untouched. (No other `.chat()` call sites — grepped.)
- **Mock echoes its configured model as served.** Like the way mock honours the reasoning toggle so
  the capture path is testable offline, `call_model`'s mock branch sets `served_model=p.model`. This
  is what lets `browser_phase16` (mock-only, zero-token) render a real pill. The cli branch leaves it
  `None` (Grok reports no model) and the Grok config-fallback was skipped per "quick v1".
- **Margin kept consistent.** `margin.py` inlines its meta (doesn't call `_reply_meta`), so a one-line
  `if reply.served_model:` was added there too — provenance is uniform across main and margin even
  though the margin UI pill itself was left out (spec: margin pill optional).
- **Frontend refactor.** `reasoningBlock(t)` was replaced by `turnFooterParts(t)` (builds the
  `.turn-footer` with the `.reasoning-toggle` and the `.model-pill`, returns the `.reasoning-body`
  separately) + `modelPill(t)` + `appendTurnFooter(container, t)` (appends footer then the full-width
  body). The three call sites — `renderConverse`, the research panel card, and the synthesis — now
  call `appendTurnFooter(…)`. The `.reasoning-toggle` / `.reasoning-body` class names and the
  click→toggle wiring are byte-for-byte preserved, so `browser_reasoning` passes unchanged.
- **Mismatch tint shipped (the "optional polish").** `modelPill` adds `.model-pill.mismatch`
  (warning-tinted) when `meta.model` and `meta.served_model` disagree. For the mock fixture they're
  equal (served = configured), so no tint shows in the offline tests — the tint path is asserted
  directly via `page.evaluate(modelPill({...}))` instead.
- **One browser assertion dropped as misguided.** An early draft checked "served value not in the
  visible body". For mock, `served == configured`, and the configured model is *intentionally* shown
  in the panel `.badge` / header — so the string is legitimately on screen. Context-isolation of
  `served_model` is an engine property anyway, and is asserted directly in `engine_phase11`
  (`SERVED_SECRET_X` excluded from `build_context`). Removed from the browser test.
- **Gate:** `engine_phase11` extended (served_model: adapter capture for both shapes, read-back
  persistence on the mock room, context-isolation); new `tests/browser_phase16.py` (pill beside
  thinking, `title` == served, absent/empty → no pill, mismatch tint, thinking still expands). Full
  suite **19/19** (14 browser + 5 engine), DOM ids intact, `.reasoning-*` classes unchanged.
