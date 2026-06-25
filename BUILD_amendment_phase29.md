# BUILD amendment — prompt caching for the re-sent transcript (phase 29)

> **Status: BUILT.** Prompted by the context discussion: converse re-sends the WHOLE transcript every
> turn (stateless API, no model memory), so a long thread pays full prefill repeatedly. Prompt caching
> serves the stable prefix from cache (~10% cost + big latency win) — the lossless version of "it only
> needs the new rounds". As-built notes at the foot.

---

## 29.1 — Cache settings
`settings.PROMPT_CACHE` (on by default; `RESEARCH_ROOM_PROMPT_CACHE=0` to disable) +
`PROMPT_CACHE_TTL` (default **`1h`**). The 5-minute default expires between long deep-research turns, so
the prefix would never hit — 1h survives the gap. `""` → provider default (5m); `"5m"`/`"1h"` to tune.

## 29.2 — Cache the stable transcript prefix
On a transcript-context call (converse / yes-and / transcript-panel), `openai_style.chat` splits the
last user message at the `"Respond as […]"` boundary: the big transcript **head** gets a `cache_control`
breakpoint (with the TTL), the short tail stays volatile. Next turn the head grows by appending, so the
prior head is a byte-prefix → a cache hit. OpenRouter-only (the `cache_control` shape is Anthropic's; OR
ignores it for non-supporting models). **Transparent fallback:** a cached request that returns 400
retries once **without** caching — caching can never break a turn.

## 29.3 — Capture the cache hit
`usage.cached` = `prompt_tokens_details.cached_tokens` — the input tokens served from cache. Rides
`meta.usage` like cost/reasoning.

## 29.4 — Routing
`run_mode` passes `cache=True` only for transcript-context rounds (the big re-send); blind panels
(fusion/mapping/side-by-side default) don't cache. Threaded through `call_model` → `openai_style.chat`.

## 29.5 — Visibility
The pill metadata popover gains a **Cached** row (`48k in (~90% off)`) when a turn had a cache hit, so
the savings are visible — the offer from the reasoning-visibility phase.

## Gate
- **Engine** `engine_phase29`: the transcript prefix is split + `cache_control`+ttl marked (full text
  preserved); `cache=False` and non-OR rows stay plain strings; a cached 400 transparently retries plain
  and the turn still succeeds; `usage.cached` captured; converse routes `cache=True` while a blind panel
  routes `cache=False`.
- **Browser** `browser_phase29`: the popover shows a Cached row on a hit, absent otherwise.
- Full suite green (17 engine + 24 browser + the rollback race).

## Housekeeping
- README: prompt caching (what it caches, the 1h TTL, the transparent fallback, the Cached popover row).
- DEFERRED: compaction/summarization is the *complementary* lossy lever (Wave 5) for when even a cached
  thread approaches the window; caching is lossless and doesn't shrink context. 1h-TTL passthrough
  through OpenRouter wants live verification (the fallback covers it if rejected).

---

## As-built notes

- **Why caching, not delta-trimming.** The model is stateless and holds nothing between calls; sending
  only "the new rounds" would leave it blind to the docs + earlier turns. Caching keeps the FULL context
  (correct) and just makes the stable part nearly free to re-send — exactly what claude.ai does on top
  of the same store-and-resend it (and RR) already do.
- **Split-in-adapter keeps the blast radius tiny.** Rather than restructure `build_context` into content
  parts (which would ripple through cli/mock/estimate/anthropic), the split happens entirely inside
  `openai_style.chat` on the flat string, at the deterministic `"\n\nRespond as ["` marker that
  `build_context` always emits. So `build_context`, `modes._round_payload`, the mock, and the cli prompt
  are untouched — they still see plain strings. Only `call_model` gained a `cache` flag and `run_mode`
  sets it for transcript rounds.
- **The fallback makes 1h safe to default.** I can't verify from here whether OpenRouter forwards the
  `ttl` field (1h is an Anthropic extended-cache beta). So caching is optimistic (default on, 1h) but
  self-healing: if the cached shape is rejected with a 400, the adapter retries the identical request
  without `cache_control` and the turn proceeds. Worst case you lose the *optimization*, never the turn.
- **Faithfulness:** adding `cache` to `call_model` broke four test spies that mirrored its signature
  (`engine_phase20/23/25/26`) — they gained `**kw` to forward it. No production behaviour changed for
  non-transcript paths (blind panels, judge, mock, cli all route `cache=False` / are non-OR). All other
  `engine_phase*` pass unchanged.
- **Below-minimum prefixes just don't cache.** Anthropic ignores `cache_control` on a block under the
  model's minimum cacheable size (~1k tokens) — no error — so early short converse turns silently skip
  caching and long ones benefit. No size gate needed our side.
- **Gate:** `engine_phase29.py` + `browser_phase29.py`. Full suite green (17 engine + 24 browser + the
  rollback race proof).
