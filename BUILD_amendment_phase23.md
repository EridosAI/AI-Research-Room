# BUILD amendment — Cluster 1: surface wins (phase 23)

> **Status: BUILT.** Companion to [BUILD.md](BUILD.md), the roadmap, and prior amendments. As-built
> notes at the foot. (Numbered 23 — 22 is inline files.)

---

Five Cluster-1 surface wins plus the **proxy-Grok no-search guard** folded in — six small,
**independent** additions, mostly display / UX. **None touch the `turn.text`-only invariant** (cost and
context-size are meta/display; the guard is a per-seat system prompt, invisible to other panelists).

## 23.1 — Real cost surfacing (`usage.cost`)
- OpenRouter returns the authoritative per-request USD cost as `usage.cost`. **Capture** it alongside
  the existing usage parse → stamp to the turn's meta (rides `usage`, same shelf as the token counts).
- **Display** — a **`Cost` cell in the model-square popover** (accumulated per model for the room) + a
  **session total** cost beside the session token total.
- **Proxy-Grok / off-OR seats** have no cost field → show **free**.

## 23.2 — Copy button on output
- A **copy button** in each output turn's footer (beside model / thinking pills); copies the turn's
  text with a brief "copied ✓" state.

## 23.3 — Effort level in converse mode
- Surface the per-room / per-panelist effort dial in converse too: the popover's effort selector is
  present, and the converse dispatch sends `reasoning.effort`.

## 23.4 — Per-model context gauge
- A **per-model colour ring** on each model-square tile (speaker dot centred in a fill ring) — forward-
  context tokens ÷ **that model's own window**, ramping green → amber → red. Precise `used / window` in
  the popover's Context cell. Per-model (not one binding-constraint gauge) so it stays correct once
  Wave-5 per-model compact-and-swap lands — the rings are its trigger surface and read the same window.

## 23.5 — OR model dropdown (live from `/models`)
- Adding a model offers a **searchable dropdown from OR's `/models`** (reuse the cached fetch); picking
  one **creates the row with metadata-seeded defaults** (context window + reasoning). Proxy-Grok stays
  a manual row.

## 23.6 — No-search guard (stop proxy-Grok fabricating searches)
- When a seat has **no active web search**, append a line to *that seat's* system prompt: it has no web
  search this response; answer from its own knowledge, but when a question needs current info it can't
  verify, say so plainly rather than presenting unverified specifics as if it had searched.
- **Capability-driven** (tied to the `web_search` flag / whether search is actually attached this
  response), not name-hardcoded — fires for proxy-Grok and any search-off seat; does not fire when
  search is on.

## Gate
- **Engine** `engine_phase23.py`: `usage.cost` captured (OR sends `usage:{include}`) and **excluded
  from `build_context`**; the no-search guard is in a seat's assembled system prompt when search is off
  and absent when on; converse threads `reasoning.effort`; `model_catalog` parses `/models`;
  `or_model_catalog` is `[]` without a key; **list config fields round-trip through a UI write**.
- **Browser** `browser_phase23.py`: copy button copies turn text; popover Cost cell ($0.00 OR / free
  off-OR) + a working converse-mode effort selector; per-model context rings + colour ramp; the OR
  model dropdown populates and a pick seeds the new row's window + reasoning.
- Full suite green; DOM ids intact.

---

## As-built notes

- **Cost rides `usage`, not a new meta key.** `openai_style.chat` adds `usage["cost"]` from the
  response (and sends `body["usage"] = {"include": true}` on OR rows so cost is returned — OR gates the
  cost field behind that flag; the spec's "no extra params" wasn't quite right, but the flag is
  harmless and the only reliable way to get cost). `call_model` already passes `usage` straight to
  `ModelReply` → `_reply_meta` stamps it → `build_context` never serializes meta, so cost is isolated
  by the same construction as the token counts (asserted). The UI sums `usage.cost` per speaker; off-OR
  seats (no cost field) read **free** via a `base_url`-based `isORSeat` check.
- **23.3 was already wired end-to-end — the gap was only perceived.** `modes.converse` already passed
  `reasoning_effort`, and the model-square popover already rendered the effort selector in any mode
  (it's not mode-gated). engine_phase20 already tested the converse effort thread. So 23.3 reduced to a
  confirming browser assertion (selector present in converse + a click persists to room.json) plus a
  re-assert in engine_phase23. No dispatch change was needed.
- **The context ring is one shared numerator ÷ per-model windows.** `forwardTokenEstimate()` counts the
  synthesis-only forward view (`turn.text`, raw panel answers excluded — the same filter
  `build_context` uses) at ~chars/4; each tile's ring divides that by `providerOf(k).context_window`.
  Pre-compaction the rings differ only by window (as the spec predicted); the structure is already
  per-model so Wave-5 per-model compaction can swap one seat's numerator without touching the others.
  No window known → bare dot, no ring.
- **23.5 reuses the effort-catalog parse.** `openai_style.model_catalog` returns `{id, context_length,
  reasoning, supported_efforts}` (context_length falls back to `top_provider.context_length`; reasoning/
  efforts come from the same `_parse_effort_catalog` the selector uses, so a seeded row is consistent
  with its later popover). `providers.or_model_catalog` finds the first OR row with a key, caches by
  base_url, and returns `[]` otherwise. The add form's datalist populates from `/or-models`; picking a
  listed model seeds `context_window` + `reasoning` and defaults the base to OpenRouter. A typed,
  non-listed id still works unchanged (manual row).
- **The guard is applied once, at the `call_model` boundary.** `_guard_no_search(payload, searches)`
  returns a COPY with the guard folded into `system` when the seat won't search this response —
  critical because research fans ONE blind payload to N seats with different search capability, so the
  guard must not mutate the shared dict. `searches = (tools and web_search)` for api rows, or
  `(cli and tools)` for the agentic runner. Converse (tools=False) is always no-search, so converse
  seats get the guard — accurate, since converse genuinely doesn't search.
- **Latent bug fixed: the TOML serializer couldn't write arrays.** Caught by the browser gate — a
  `PUT /providers` (any field) rewrites `config.toml` via `_dump_toml`, and `_toml_scalar` stringified
  list values, so `supported_efforts=["high","xhigh"]` was dumped as `"['high', 'xhigh']"` and reloaded
  as `None` (silently dropping the effort override). Phase 20 added the only list field and it had never
  round-tripped through a UI write until Phase 23's test exercised it. Added `_toml_value` (emits a TOML
  array for lists) and a round-trip assertion in the engine gate.
- **Stale assertion updated.** `browser_phase20` asserted "no placeholder Cost row should ship"; Phase
  23 ships a real Cost cell, so that assertion was removed (the Cost cell is now covered by
  browser_phase23).
- **Gate:** `engine_phase23.py` + `browser_phase23.py`. Full suite green (11 engine + 19 browser),
  DOM ids intact, existing model-bar/popover behaviour otherwise unchanged.
