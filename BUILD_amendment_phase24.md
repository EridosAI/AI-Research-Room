# BUILD amendment — context-window accuracy (phase 24)

> **Status: BUILT.** Extends 23.4 (per-model context gauge). As-built notes at the foot. Small phase.

---

The 23.4 ring gauged against the model's **headline** `context_length`. But OR routes a model across
providers who can serve **smaller** windows than the headline — common for open-weight seats (GLM, Kimi,
DeepSeek). Two refinements: calibrate the ring to the **effective** routed window, and a **small dot**
in the popover when that window is reduced from — or has changed since — the headline.

## 24.1 — Resolve the effective window
- The ring's denominator is now the **effective** routed window: `top_provider.context_length` from
  `/models` (inline, free), falling back to the **min `context_length` across `/models/:author/:slug/
  endpoints`** (the conservative floor) when the inline value is absent. Cached alongside `/models`.
- The popover's Context cell shows that window; off-OR seats (proxy-Grok) use the configured value with
  no comparison.

## 24.2 — The reduction / change dot
- A **small red dot** beside the popover's Context cell when **either** the effective window `<` the
  headline (*"routed window {eff} < headline {headline} — ring uses {eff}"*) **or** a fresh `/models`
  headline differs from the seeded value (*"headline changed: was {old}, now {new}"*, and the seed is
  re-seeded). No dot when effective == headline and nothing changed; none for proxy-Grok.

## Gate
- **Engine** `engine_phase24.py`: `model_catalog` exposes `effective_window` (top_provider);
  `endpoints_min_window` parses the floor; `window_info` resolves effective (top_provider → endpoints-
  min), flags `reduced` (eff < headline) and `changed` (fresh headline != seeded), clears `changed`
  after re-seed while `reduced` persists, and falls back to the configured window off-OR.
- **Browser** `browser_phase24.py`: the ring/Context calibrate to the effective window; the dot renders
  (with both numbers in the tooltip) for a reduced and a changed seat, and is absent for a full-window
  seat.
- Full suite green (12 engine + 20 browser); 23.4 ring behaviour otherwise unchanged.

---

## As-built notes

- **Headline vs effective are now distinct fields.** `model_catalog` returns `context_length` (headline
  — the model object's value, falling back to top_provider only when the headline is absent) AND
  `effective_window` (= `top_provider.context_length`, inline, `0` when absent). 23.5 still seeds
  `context_window` from `context_length` (the headline), so the "changed" comparison (fresh headline vs
  seeded) is apples-to-apples.
- **`window_info(p)` is the single resolver**, consumed by `_window_view` in `/participants`. OR seats:
  effective from the cached catalog's `effective_window`, else a per-seat `endpoints_min_window` call
  (only when the inline value is missing — not for all 300 models). Cached by `(base_url, model)` in
  `_win_cache`. Off-OR / no-key → `{effective: configured, headline: None, reduced/changed: False}`.
- **Could NOT verify `top_provider.context_length` against a live OR response** from here (no key/
  network in the build env), so both paths ship: inline `top_provider` preferred, `/endpoints`-min
  fallback. The CC verification note stands — confirm the inline field is present at wire time; if OR
  ever drops it, the endpoints fallback already covers it (tested).
- **Re-seed is a guarded client one-shot.** When `/participants` reports `window_changed`,
  `reseedChangedWindows()` PUTs `context_window = headline_window` once per key per session (a `Set`
  guard — no loop, a single config write per genuine change). After re-seed the headline matches the
  seed so the "changed" dot clears next refresh; the "reduced" dot (effective < headline) correctly
  persists. Kept client-side so `GET /participants` stays pure (no writes in a read handler).
- **The dot is data-driven off the cell list.** `STAT_CELLS`' Context entry gained an optional
  `note(k)` → element; `mpRow` appends it to the value. `windowDot(k)` returns the red dot + tooltip
  (or null), so the extensibility added in 20.4 absorbed this with no popover re-layout.
- **`window_info` is best-effort in the view.** `_window_view` wraps it in try/except → a metadata
  hiccup can never fail the participants list (degrades to the configured window, no flags).
- **Gate:** `engine_phase24.py` + `browser_phase24.py` (the latter injects the server-resolved flags
  into `STATE.participants` to exercise the UI calibration/dot offline, since resolving real OR windows
  needs a key + network). Full suite green; ring/popover otherwise unchanged.
