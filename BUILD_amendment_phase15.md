# BUILD amendment — dark / light mode (phase 15)

> **Status: BUILT.** Build record (companion to [BUILD.md](BUILD.md) and the phase 13/14
> amendments). Promoted the light-mode item from [DEFERRED.md](DEFERRED.md) and the "Deferred"
> section of [BUILD_amendment_phase14.md](BUILD_amendment_phase14.md). Spec preserved verbatim;
> as-built notes appended at the foot. Current architecture is in [README.md](README.md).

---

Extends phase 13 (token layer + accent engine) and 14B (brightness-ramp-as-function). **Not a
variable swap.** The light *palette* is the easy 20%; the 80% is that the two derived ramps
(`applyAccent`, `applyBrightness`) write `--accent-*` and `--text-*` as **inline styles on
`documentElement` at runtime**, so a `[data-theme="light"]` CSS block alone will be *overridden*
by them — light mode would render with dark text and a dark-tuned accent. Flipping the mode must
therefore re-run both ramp functions with mode-aware values. That re-apply is 15.3 and is the
step that's tempting to skip and mustn't be.

No-build-step holds: CSS custom properties + vanilla JS only. **localStorage stays empty** — the
mode preference persists server-side in `ui.json` like `accent_hue`, and is applied on boot from
the server value. **DOM ids unchanged** — this adds paint + one control, no structural reshape;
run the full browser suite after.

Order: 15.1 → 15.4, gate each. 15.4 (first-paint flash) is optional polish and separable.

## 15.1 — Mode plumbing, switch, persistence
Goal: a `dark / light / system` preference exists, is the single entry point for repainting, and
survives reload.
- Add `theme_mode ∈ {"dark","light","system"}` to `ui.json`, **default `"dark"`** (preserves
  current behaviour). Persist + load through the same seam as `accent_hue` / brightness — server
  reads it, no new storage mechanism, localStorage untouched.
- Add a segmented `dark / light / system` control to the **Theme** tab (next to accent / brightness).
- `applyThemeMode(mode)` in app.js, the **single repaint entry point**:
  - Resolve: `system` → concrete via `matchMedia("(prefers-color-scheme: dark)").matches`.
    Store the resolved concrete value in a module-scope `currentMode`.
  - Set `document.documentElement.dataset.theme = currentMode` (drives the 15.2 CSS block).
  - **Re-run `applyAccent(currentHue)` and `applyBrightness(currentLevel)`** so the inline-set
    `--accent-text` / `--text-*` match the new mode (see 15.3). Keep `currentHue` / `currentLevel`
    in module scope so they can be re-applied.
  - If `mode === "system"`, attach a **single** `matchMedia(...).addEventListener("change", …)`
    listener that re-resolves + repaints live; remove it when mode is not `system` (hold one ref,
    don't stack listeners).
- Boot: seed `currentHue` / `currentLevel` / `currentMode` from `ui.json`, **then call
  `applyThemeMode(currentMode)` once**. Remove any now-redundant direct `applyAccent` /
  `applyBrightness` calls from boot so mode-aware values aren't applied and then clobbered.

Done when: toggling the control switches the theme live; reload restores the saved choice;
`system` follows the OS and updates **live** when the OS theme flips; localStorage is still empty
after all of it.

## 15.2 — Light token block (CSS-resident tokens)
Goal: the surfaces / borders / affordances / shadows that live in CSS flip under `[data-theme="light"]`.
- Keep the existing dark values in `:root` as the **default** (no flash for dark users + a sane
  fallback if JS fails). Add a `[data-theme="light"] { … }` override block in `styles.css` for the
  CSS-resident tokens only:
  - **5 surface tiers — light inverts dark's elevation *mechanism*.** Dark distinguishes elevation
    by surface *lightness* (deeper = lighter shade). Light distinguishes it by *shadow*: chrome
    (sidebar/panels) gets subtly greyer, but content and floating surfaces stay **white** —
    `--bg-elevated` and `--bg-modal` are `#FFFFFF`, lifted by shadow, **not** darkened.
  - **Shadow scale — new; dark didn't need it.** Add `--shadow-sm` / `--shadow-md` / `--shadow-lg`.
    In `:root` (dark) set them to **`none`** — dark uses shade, keeping dark byte-identical. In
    `[data-theme="light"]` set the research values. Apply `box-shadow: var(--shadow-*)` to the
    surfaces that go white in light. Keep the **modal** on its existing `--shadow-modal` and
    override that token's value in the light block.
  - `--surface-hover` / `--surface-active` → low-alpha **black** (repo's `--surface-*` names).
  - `--border-subtle` / `--border-default` / `--border-strong` → low-alpha **black**.
  - `--scrollbar-thumb` / `--scrollbar-thumb-hover` → low-alpha **black**.
  - **Semantic** (`--success` / `--warning` / `--error` / `--error-bg`) → darkened for white-surface
    contrast. Static `:root` hex, so they belong in the light block.
- Typography / radii / spacing are **already** shared in `:root` (phase 13).
- Token discipline holds: light values go **only** in this block (and the JS ramps in 15.3).

Done when: with `data-theme="light"`, chrome reads as white with subtly greyer panels, floating
surfaces read as white *lifted by shadow*, borders are barely-there dark hairlines, the scrollbar
thumb is a darker grabbable handle; the dark theme is pixel-identical to before.

## 15.3 — Mode-aware ramps (the JS half — the one that mustn't be skipped)
Goal: the runtime-set text + accent vars are correct for the active mode. They go in the ramp
functions, keyed off `currentMode`.
- `applyBrightness(level)`: key off `currentMode`. **Dark** keeps the existing
  `BRIGHTNESS_TOP × RAMP_STEPS` computation untouched. **Light** uses its own ramp rows — neutral
  oklch greys at light L values (primary near-black, descending to faint grey).
- `applyAccent(hue)`: stays **hue-derived**. Two things fork by `currentMode`:
  - **State direction.** Dark: hover lightens (+0.05 L), active darkens (−0.05). Light:
    hover −0.05, active −0.10 (both darker for contrast on white).
  - **`--accent-text` L.** Dark ≈ 0.72; light ≈ 0.47.
  `--accent`, `--accent-subtle`, `--accent-border` are unchanged across modes.

Done when: in light, primary text is near-black / high-contrast and the grey ramp recedes toward
white; accent fills darken on hover/press and accent text/links are legible on white; dark output
is byte-identical.

## 15.4 — First-paint flash (optional / gated)
Pick (a) server-stamp the saved mode onto the served `index.html` (zero flash for explicit
dark/light), or (b) accept the brief flash and document it.

## Shared across modes (do NOT fork these)
`--accent` / `--accent-subtle` / `--accent-border` (hue-derived); `--scrim` (modal backdrop stays a
dark scrim in both); the type / radii / spacing scales; the speaker `DOT_MAP` / `DOT_DEFAULT`.

## Gate
Full browser suite green; DOM ids intact. `tests/browser_phase15.py`: the switch is present in the
Theme tab; light sets `html[data-theme="light"]`, flips a surface token, drops `--accent-text` to
its light L, makes `--text-primary` dark, and `--shadow-md` is non-`none` in light / `none` in dark;
system resolves to a concrete `data-theme`; the choice persists across a hard refresh with
localStorage empty; dark leaves every token at its pre-phase-15 value.

---

## As-built notes (deviations / confirmations worth recording)

- **`currentMode` → `currentTheme`.** The spec's module-scope `currentMode` collided with an
  existing `currentMode()` function (the composer's converse/research selector). Renamed the theme
  variable to `currentTheme`; `currentHue` / `currentLevel` kept the spec names. (Caught by
  `node --check` before the browser run — a redeclaration `SyntaxError`.)
- **15.1 single repaint path, exactly as specced.** `applyThemeMode(mode)` resolves system →
  concrete (`matchMedia`), sets `documentElement.dataset.theme`, then re-runs
  `applyAccent(currentHue)` + `applyBrightness(currentLevel)`. One held `matchMedia` listener
  (`_mq` / `_mqListener`) is attached only in `system` mode and removed on any other selection —
  never stacked. Boot seeds the three module vars from `ui.json` and calls `applyThemeMode()` once;
  the old direct `applyAccent`/`applyBrightness` boot calls were removed so mode-aware output isn't
  applied then clobbered. `applyFontScale` stays a separate, mode-independent call.
- **15.2 light block.** Surfaces follow the research mechanism: chrome (`--bg-tertiary` `#F0F1F4`,
  `--bg-secondary` `#F9F9FB`) steps greyer; content + floating surfaces (`--bg-elevated` /
  `--bg-modal`) stay `#FFFFFF` and lift by shadow. New `--shadow-sm/md/lg` are `none` in `:root` and
  filled in the light block (so dark is byte-identical); `box-shadow: var(--shadow-*)` was added to
  `.panel` (`--shadow-md`), `.pcard` / `.artifact` / `.reasoning-body` (`--shadow-sm`) — the
  white-collapsing surfaces. `.overlay-card` and `.room-preview` already used `--shadow-modal`, whose
  value the light block overrides, so they were left untouched. The margin panel keeps its splitter
  for separation (no shadow needed).
- **15.3 mode-aware ramps.** `applyBrightness` branches: dark = `BRIGHTNESS_TOP × RAMP_STEPS`
  (unchanged); light = explicit per-role L rows `LIGHT_RAMP` (`default [0.13,0.36,0.56,0.71]`, soft +
  crisp variants), neutral `oklch(L 0.012 256)` greys (no cool tint — the optional faithful touch was
  skipped for parity with dark). `applyAccent` forks state-direction L deltas + `--accent-text` L
  (light 0.47 / dark 0.72) off `currentTheme`; hue stays user-selected; `--accent`/`-subtle`/`-border`
  shared. The accent-swatch and brightness controls now also write `currentHue`/`currentLevel` so a
  later mode flip re-applies the live selection.
- **15.4 — chose (b), accept the brief flash, documented.** No localStorage + `/ui` is fetched on
  boot, so an explicit-light user sees the `:root` dark default for one paint. Server-stamping the
  surface attribute alone would *not* help — the JS-driven text ramp still applies a paint later, so
  stamping surfaces without the (JS-only, single-source) light text vars would flash *near-white text
  on white* instead, arguably worse. Honoring "JS is the single source of the ramps," (a) was not
  worth duplicating the light text ramp into CSS; the flash is <100ms on localhost. Recorded here.
- **One legibility fix beyond the spec.** `#send-btn` fills with the saturated `--accent` (L 0.55)
  but took `color: var(--text-primary)`, which goes near-black in light → unreadable on the fill. Its
  text is now a stable light tone (`#f7f8f8`) in both modes (text on an accent fill is "on-accent",
  not body text). Side effect in dark: the button label is a hair brighter than the phase-14
  brightness-dimmed value (back to the pre-14 white) — imperceptible and arguably more correct for a
  primary CTA. No token changed; the gate's four tracked tokens are unaffected.
- **Gate:** `tests/browser_phase15.py` — control present in Theme tab; light flips
  `--bg-primary` off `#08090a`, `--shadow-md` off `none`, drops `--accent-text` to L 0.47, makes
  `--text-primary` L 0.13; persists across hard refresh with localStorage empty; system resolves to a
  concrete `data-theme`; returning to dark restores every captured token byte-for-byte. Full suite
  **18/18**, DOM ids intact (phase 13/14 accent + theme-tab tests unchanged).
