# BUILD amendment — visible reasoning (phase 11)

> **Status: BUILT.** Build record (companion to [BUILD.md](BUILD.md) and
> [BUILD_amendment_rooms_margin.md](BUILD_amendment_rooms_margin.md)). Preserved verbatim —
> current architecture lives in [README.md](README.md); deferred items in [DEFERRED.md](DEFERRED.md).

---

Extends `BUILD.md`. One feature: capture each model's reasoning where it's offered, store it on
the answer turn, and show it in the main chat as a collapsed (auto-minimised) disclosure.
**Best-effort** — providers that don't expose reasoning simply contribute none, and that's fine.

## The model (read first)

**Reasoning is a field on the answer turn, not a separate turn.** Store it at `meta.reasoning`
(string) on the same `ai`/`judge` turn whose `text` holds the final answer, with optional
`meta.reasoning_kind` (`"summarized" | "full"`).

**No `forward_turns` change is needed — this is the elegant part.** `build_context` already
serializes only `turn.text` and never reads `meta`, so reasoning in `meta.reasoning` is excluded
from forward context **by construction** — it is never re-sent to any model on a later turn. This
is also *required*, not just nice: DeepSeek errors if `reasoning_content` is replayed in history
(only `content` may be), and Claude strips prior thinking blocks from context automatically.
Storing reasoning in a field the serializer doesn't read satisfies both for free. **Do not** add
`is_reasoning` to `forward_turns`; it's unnecessary.

## Per-provider capture (best-effort, opt-in)

Capture is **opt-in per provider** via a "show reasoning" toggle in the providers panel
(`reasoning: true|false` in the registry), **default off**, because enabling it changes
cost/latency on some providers. Flip on the ones you want to watch.

- **DeepSeek (`openai_style`)** — cleanest. With the toggle on, enable thinking:
  `extra_body={"thinking":{"type":"enabled"}}` + `reasoning_effort="high"`. Response carries
  `choices[0].message.reasoning_content` (chain-of-thought) beside `.content` (answer). Capture
  `reasoning_content` → `meta.reasoning`. **Cost:** this enables a thinking *mode* the model
  otherwise skips — real extra tokens. (`deepseek-v4-pro`/`-flash`, base `https://api.deepseek.com`.)

- **Claude / Opus 4.8 (`anthropic_style`)** — available, with two catches:
  - **Do NOT send `budget_tokens`** — returns a 400 on Opus 4.8 (adaptive-thinking model). Depth
    is via effort (`output_config={"effort": "..."}`), not a token budget.
  - **Thinking is `display:"omitted"` by default on 4.8** (empty thinking field, signature only).
    To get readable reasoning, set `thinking: {type: "adaptive", display: "summarized"}` —
    **verify exact nesting against current docs.** What you get is **summarized** reasoning, not
    the raw stream.
  - With the toggle on: set display=summarized, capture the `thinking`-type blocks' text →
    `meta.reasoning`, `reasoning_kind="summarized"`; keep `text` blocks → answer. **Cost:** 4.8
    thinks anyway at default effort, so you only pay for the returned summary — cheap to enable
    relative to DeepSeek.

- **Kimi (`openai_style`)** — **verify.** Capture `reasoning_content` if the Moonshot endpoint
  exposes it for `kimi-k2.6`; if the field's absent, contribute nothing.

- **Grok (cli / subscription)** — `grok -p` returns the final answer, not a reasoning field. The
  subscription-CLI path doesn't surface a trace the way an API field would. Expect none; capture
  nothing. (Cost of the subscription tradeoff, not a bug.)

The `reasoning_content` capture in `openai_style` is **provider-agnostic**: read
`message.reasoning_content` if present, store it, done — one path covers DeepSeek, Kimi, and any
future OpenAI-shaped reasoner.

## UI

- Under any answer, panel card, or synthesis whose turn has a non-empty `meta.reasoning`, render a
  **collapsed "thinking" disclosure** — folded by default (auto-minimised), one click to expand.
  Same interaction as the margin's "view full." Sanitise via DOMPurify like all model output.
- For Claude, label it subtly as summarised (e.g. `thinking (summary)`) so a summary isn't
  misread as the raw trace.
- It renders straight from the transcript you're viewing, so it's visible **only to you** in the
  main chat — nothing about it flows to other models (per the field-not-turn design above).
- Providers panel gains the per-provider "show reasoning" toggle (writes `reasoning` to the
  registry), default off.

## Done when
- A provider with its toggle on produces answer turns carrying `meta.reasoning`; with it off, the
  field is absent and behaviour is unchanged.
- **Isolation gate (mirror of synthesis-only):** a turn with `meta.reasoning` set → the next
  `build_context` body contains the answer `text` and **zero** reasoning text. Assert directly.
- DeepSeek reasoning appears and renders collapsed; Claude shows a summarised disclosure when
  enabled; Grok/Kimi show nothing gracefully when the field's absent — no errors either way.
- Reasoning never appears in any payload sent back to a model (verify a DeepSeek multi-turn
  exchange does not resend `reasoning_content`).

## Notes
Feature-level — no new dependency, no install-story change, no change to the room/margin model.
`meta.reasoning` is just a new optional field on existing turns. Fits cleanly before packaging.

---

## As-built notes (deviations / confirmations worth recording)

- **`call_model` now returns a `ModelReply`** (`text`, `reasoning`, `reasoning_kind`) instead of a
  bare string — the contract change that threads reasoning out of the adapters without a side
  channel. All call sites (`modes.research`/`converse`/`_call_judge`, `margin.margin_turn`) read
  `.text` and stamp `_reasoning_meta(reply)` onto the turn.
- **openai_style enables thinking via top-level body keys** (`thinking`, `reasoning_effort`) since
  we use raw httpx, not the OpenAI SDK's `extra_body`. Reasoning capture only runs when the toggle
  is on, so Kimi/others that reject the field are unaffected when left off (default).
- **Claude nesting used:** `thinking: {type: "adaptive", display: "summarized"}`, no
  `budget_tokens` — verify against current docs before the first real Opus 4.8 call.
- **Grok/cli + mock-without-toggle contribute no reasoning** by construction; the mock honours the
  toggle so the capture path is testable offline (`mockthink` fixture).
- The isolation gate and adapter capture/enable logic are covered by `tests/engine_phase11.py`
  (incl. stubbed-httpx adapter tests); UI render/expand + toggle persistence by
  `tests/browser_reasoning.py`.
- **Real-API verification — DONE (2026-06-17, with keys).**
  - **Claude summarized nesting:** a live call to `claude-opus-4-8` with our exact body
    (`thinking: {type: adaptive, display: summarized}`, no `budget_tokens`,
    `anthropic-version: 2023-06-01`) returned `['thinking', 'text']` blocks with a non-empty
    thinking summary — confirming the shape is accepted AND that `display:summarized` takes
    (didn't silently fall back to `omitted`). Our capture (text from `text` blocks, reasoning
    from `thinking` blocks) matches the live response.
  - **DeepSeek multi-turn:** confirmed a multi-turn exchange does not error from replaying
    reasoning — consistent with the isolation gate (reasoning lives in `meta`, never in the
    `text` that `build_context` re-sends), now confirmed at the live-API layer too.
