# BUILD amendment — OpenRouter consolidation + reasoning selectors + model-square bar (phase 20)

> **Status: BUILT.** Companion to [BUILD.md](BUILD.md) and the phase 11–19 amendments. As-built notes
> at the foot.

---

**Decision:** route every panelist through OpenRouter except Grok (Hermes proxy). Once every active
row is `openai`-backend, `anthropic_style` goes dormant and the Phase-17 search dispatch shrinks to
`openrouter:web_search` | none. The reasoning selector then rides one uniform shape. **Also fixes
instant-Claude:** via OR you send `reasoning.effort` and OR maps it to Opus 4.8's adaptive API (+
defaults `summarized`), sidestepping the `budget_tokens` trap.

**Invariant unchanged:** `meta` (reasoning/search/served_model/finish_reason) stays out of forward
context. No `reasoning_details` turn-to-turn passback (panels are single calls; forward context is
synthesis-only).

## 20.1 — Consolidate on OpenRouter (config, + shrink the adapter/search surface)
Routing is a personal config choice (repoint rows to OR `openai` rows; Grok stays on the proxy). No
production code change: with no `anthropic` rows active, `anthropic_style` and its search branch are
simply unused. `served_model` returns the OR slug — still truthful, pill still works.

## 20.2 — Reasoning plumbing (effort → `reasoning` param)
- Per-room, per-panelist `reasoning_effort` map in `room.json` (`{panelist: high|medium|low}`,
  empty = model default); threaded through `modes` (panelists + judge + converse) → `call_model` →
  `openai_style`. Absent override → `None` → OR uses the model default (Opus = high → Claude thinks).
- A generous `max_tokens` (Phase-18 `RESEARCH_MAX_TOKENS`) already prevents high-effort truncation.
- `effort_options` is exposed per provider (server view): `[high, medium, low]` for OpenRouter rows,
  `None` for proxy-Grok / direct rows (no effort control → no selector).

## 20.3 — Capture the OR reasoning shape (shipped WITH 20.1/20.2)
`openai_style` now reads reasoning from `reasoning_details` (render `reasoning.summary` +
`reasoning.text`, **skip** `reasoning.encrypted`) → flat `reasoning` → `reasoning_content` (direct).
OR rows send `reasoning: {enabled, effort}`; direct rows keep the `thinking`/`reasoning_effort`
switch. `reasoning_tokens` (counted in `completion_tokens`→ usage.output) and `served_model` still
parse; isolation gate holds.

## 20.4 — Model-square bar (persistent, above the composer; extensible popover)
`#token-bar` (now `.model-bar`) renders one `.model-square` per panelist (dot + abbreviated spend) +
a session-total chip. Hover/click → `#model-popover` anchored **above** the square, staying open
while hovering square-or-popover. Contents come from a **declarative `MODEL_CELLS` list** (label →
effort selector → tokens → share-%), so a new field is a one-line append. The effort selector is
data-driven from `effort_options` (absent for proxy-Grok). It **replaces** the old per-model token
line; the `show_token_estimate`/`show_model_pct` chip toggles folded in (% always in the popover).

## 20.5 — Draggable transcript ↔ composer split
A `#composer-resizer` divider at the composer's top edge; dragging the Y axis resizes the composer
height (`composerClamp`: min 110px, max 60% viewport), the input textarea flexing to fill. Persists
to `ui.json` `composer_height` like the sidebar/margin sizes; reused the same drag pattern.

## Gate
- Engine `engine_phase20.py`: OR request shape (`reasoning:{enabled,effort}`, no direct switch);
  capture from reasoning_details (summary+text, encrypted skipped) + flat-string fallback + direct
  `reasoning_content`; per-room effort threads into the panelist/judge/converse calls. Claude probe
  behind `RR_LIVE=1` (`live_phase20.py`).
- Browser `browser_phase20.py`: square per panelist; popover effort selector present (OR) / absent
  (mock); effort persists to room.json + survives reload; the divider resizes the composer and the
  height persists across reload (localStorage empty).

## Housekeeping
README (OR routing, per-model effort, model-square bar, capture-field change); DEFERRED.md
(anthropic/xAI branches dormant, proxy-Grok search gap, effort per-room, static effort list).

---

## As-built notes

- **20.1 needed no code; 20.2/20.3 did the work.** The "consolidation" is which rows the user runs
  (personal config); the engine change is the per-room effort plumbing + the OR reasoning request/
  capture shapes. `anthropic_style` left in place (dormant) for a future direct provider.
- **Adapter tuple stayed at 6.** `reasoning_effort` is an *input* arg on `chat()`/`call_model`, not a
  new return value — capture still returns `(text, reasoning, usage, served_model, search,
  finish_reason)`. The `ChatResult`-dataclass refactor (DEFERRED) is still pending but didn't grow.
- **`reasoning_details` rendering is defensive.** Each entry contributes `text or summary`; encrypted
  entries are dropped; if details are absent we fall back to the flat `reasoning` string, then
  `reasoning_content`. So every OR panelist's disclosure renders regardless of which shape a model
  returns — the failure mode the spec warned about (blank disclosures post-switch) is covered.
- **effort_options is metadata-driven (refined post-review).** First pass hardcoded
  `[high, medium, low]` for every OR row — the giveaway being GLM (which only supports `[high, xhigh]`)
  showing the same trio. Fixed: `openai_style._parse_effort_catalog` reads each model's
  `reasoning.supported_efforts` from a cached `GET /models` (reversed highest-first → ascending so the
  dial reads left = less; `null` efforts → full OR ladder; no reasoning object → omitted). A per-row
  `supported_efforts` config override wins (and is how the offline gate exercises it). proxy-Grok /
  direct rows get `None` → the square omits the selector.
- **The model-bar replaced two tested behaviours**, so `browser_phase12` (fill-chip → model-square)
  and `browser_phase14b` (chip toggles → "folded into the bar") were updated, and the
  `#chip-tokens`/`#chip-pct` controls + handlers + `_chipToggle` removed. The `ui.json`
  `show_token_estimate`/`show_model_pct` keys are left in `_UI_DEFAULT` (harmless, unused) to avoid
  churn on existing ui.json files.
- **Composer split:** `.composer` became a flex column; the `.input-row` flexes (`#input` height
  100%, resize off — the divider is now the resize affordance). Height ≈ `innerHeight − cursorY`,
  clamped.
- **Post-review aesthetic refinements (model bar/popover):** fixed-width tiles (74px, centred,
  `tabular-nums`) so the row is even regardless of value; effort segments `flex:1` (full-width),
  rendered ascending from metadata; a `border-top` divider between the effort control and the stat
  block; stat rows on one line (label↔value, `space-between`, tabular-nums) with **Context** added
  (Tokens / Share of room / Context); popover header = colour dot + the served name with the
  `provider/` prefix stripped (`claude-opus-4.8`) + a base_url-derived subtitle ("via OpenRouter" /
  "via Hermes proxy"); an inline-SVG bolt before "reasoning effort" (no icon-font dependency). No
  placeholder Cost row ships — extensibility lives in the `STAT_CELLS` list.
- **Gate:** `engine_phase20.py` (now incl. catalog parse + override) + `browser_phase20.py` (metadata
  efforts, header, one-line stats, no Cost row) + opt-in `live_phase20.py`. Full suite **26/26**
  (9 engine + 17 browser), DOM ids for existing components intact, `.reasoning-*` classes unchanged.
