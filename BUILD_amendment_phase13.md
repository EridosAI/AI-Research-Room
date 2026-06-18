# BUILD amendment — Linear aesthetic (phase 13)

> **Status: BUILT.** Build record (companion to [BUILD.md](BUILD.md) and the other amendments).
> Preserved verbatim — current architecture is in [README.md](README.md); deferred items in
> [DEFERRED.md](DEFERRED.md).

---

Extends BUILD.md. A theming refactor, not a variable swap — the palette is the easy 20%; the elevation re-mapping and the derived-accent engine are the 80% that makes it look like Linear rather than Linear's colours on the wrong bones. No-build-step constraint holds: pure CSS custom properties + vanilla JS, no compiler. Preserve the DOM ids the browser suite keys off (as in the Phase 9 reshape) and run the full suite after — a reskin shouldn't change structure, only how it's painted.
Order: 13.1 → 13.5, gate each. 13.3 (elevation) is the one that's tempting to skip and mustn't be.

## 13.1 — Token layer + accent engine (foundation)
Goal: the full token set exists, and the accent is one hue, five derived — so user-selectable accent is native, not bolted on.
- Drop the spec's :root block for the neutral tokens — five surface tiers + hover/active, four text greys, three border alphas, semantic, type vars, radii, the 4px spacing grid.
- applyAccent(hue) in JS: sets --accent, --accent-hover, --accent-active, --accent-subtle, --accent-border, --accent-text by composing oklch(L C H) at fixed per-role lightness/chroma, varying only the hue. base oklch(.55 .15 H), hover +.05 L, active −.05 L, text ~.72 L, subtle/border low-alpha. Browser does oklch→screen — no colour math/lib/build step. Default hue ≈ navy (~233°).
Done when: vars resolve; applyAccent(navy) reproduces ~the spec's navy; changing the hue recolours every interactive/selected state coherently with nothing else touched.

## 13.2 — Token migration (route everything; grep for strays)
Goal: every colour comes from a token. Replace every hardcoded colour in CSS and inline JS styles with var(--…). Grep CSS + JS for stray hex, rgb(, named colours afterward — the only legal exceptions are the token block itself and the speaker-dot map (13.4).
Done when: the grep is clean; nothing hardcoded paints; the whole UI renders through tokens.

## 13.3 — Surface elevation re-mapping (the structural one)
Goal: depth from stacked lighter surfaces, not outlines. Re-map: app background → --bg-primary; main transcript → --bg-secondary; sidebar + panels → --bg-tertiary; margin panel + dialogs/popovers → --bg-elevated; modals → --bg-modal. Demote borders to faint low-alpha whites. Audit every border-as-separator and decide elevation-step vs faint-border (mostly elevation).
Done when: the UI reads as surfaces getting lighter with depth, borders barely-there.

## 13.4 — Speaker-dot exception + affordance preservation (cross-cutting)
Goal: identity colours stay semantic; no interaction loses its signal.
- Speaker-dot colours stay OUT of the accent/token system — their own small map. Distinct from each other and the accent; near a future hue is a known caveat.
- Affordance check through the reskin: collapsed thinking / view-full, the research composite block, the activity dot, the token chip, the pending/spinner — each re-expresses in the new elevation language without losing its cue.
Done when: dots distinct/legible against the new surfaces and accent; every disclosure/indicator still reads as interactive/active.

## 13.5 — Typography (local Inter) + accent persistence
- Vendor Inter locally (woff2 + @font-face), not CDN. Tight scale (12/13/14/16/21/27/35; body 14), weights 400/510/590. Mono for chips/code.
- Accent persistence: chosen hue → ui.json via GET/PUT /ui (not localStorage); applyAccent runs from the server-loaded value on boot. A minimal hue control in settings.
Done when: Inter loads locally (offline); scale/weights match; the accent persists across a hard refresh from the server with localStorage empty.

## Cross-cutting honesty note
Faithful-to-aesthetic, not pixel-current — Linear iterates. Match the structure (elevation tiers, single derived accent, Inter, tight radii); tune the exact navy by eye. Don't chase exact current hex.

---

## As-built notes (deviations / confirmations worth recording)

- **No spec :root block was provided**, so the neutral token set was authored to the described
  structure: surfaces `#08090a → #0f1011 → #161718 → #1c1d1f → #232427` (primary→modal), text
  greys `#f7f8f8 / #c4c8ce / #8a8f98 / #62666d`, borders `rgba(255,255,255, .045/.08/.13)`,
  semantic success/warning/error, type + radius + 4px-spacing vars. Navy accent =
  `oklch(0.55 0.15 233)` (text role lifted to `0.72`). Tune the hue by eye if desired — the
  swatch control makes it one click.
- **Elevation (13.3) done, not skipped:** sidebar/panels/cards → tertiary, margin/disclosures →
  elevated, modals → modal, main column → secondary on the primary base; borders demoted to
  `--border-subtle`; row/selection states use `--surface-hover/active`; the human bubble uses
  `--accent-subtle` instead of a hardcoded green tint.
- **Migration grep is clean** — every colour routes through a token; the only literals left are
  the `:root` block and `DOT_MAP`/`DOT_DEFAULT` in app.js (the speaker-dot exception). Added
  `--scrim` / `--shadow-modal` tokens so even the modal backdrop/shadow blacks are tokenised.
- **Accent control = swatches** (8 preset hues), not a slider — "user-selectable accent real
  now"; a full picker/slider is the natural extension. Persisted to `ui.json.accent_hue`
  (default 233), applied on boot from the server value (localStorage stays empty).
- **Inter vendored** at `web/static/fonts/InterVariable.woff2` (variable woff2, ~344 KB) with a
  `@font-face` weight range 100–900; committed to the repo so the friend gets it offline.
- Gate: `tests/browser_phase13.py` (tokens resolve, accent engine recolours all six roles +
  persists across hard refresh with localStorage empty, Inter served locally, dot exception).
  Full suite 14/14, DOM ids intact (reskin changed paint only).
