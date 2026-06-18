# BUILD amendment — settings home, theme controls, scrollbar (phase 14)

> **Status: BUILT.** Build record (companion to [BUILD.md](BUILD.md) and the other amendments).
> Preserved verbatim — current architecture is in [README.md](README.md); deferred items in
> [DEFERRED.md](DEFERRED.md).

---

Extends BUILD.md. UI/settings only; no install-story change. Preserve the DOM ids the browser suite keys off (move panels, don't rebuild). Full suite green after. Order: A → B → C, gate each.

## 14A — Settings home (the container)
Goal: "providers" becomes "settings" — a tabbed home with three tabs.
- Rename the providers entry/button to settings. It opens a panel with three tabs:
  - Providers — the existing provider-management panel, moved in unchanged.
  - Theme — 14B.
  - Data — the export_dir / Obsidian notes-directory setting, relocated here.
- Tabs are view-switching within the existing panel — no new persistence layer; each tab reads/writes the settings it already owns (ui.json for theme + export_dir, registry for providers).
Notes: pure reorganisation — move DOM nodes, don't recreate, so the suite's selectors still resolve.
Done when: "settings" opens; all three tabs render; Providers behaves exactly as before; Data holds the export dir; nothing lost in the move.

## 14B — Theme tab: text brightness, font size, display name
Goal: accent (as-is) + text-brightness (the fix for "too bright on dark") + font size + how the app addresses you. No light/dark/system switch this phase.
- Accent — existing swatch control, moved in unchanged.
- Text brightness — 3–4 steps (Soft / Default / Crisp). Built the derived way: one brightness setting recomputes the text-grey ramp (--text-primary/secondary/tertiary/quaternary) from a single input. Lower → lower-lightness oklch greys. Persist to ui.json; re-apply on boot.
- Font size — base-size control (Compact / Default / Large) via a root --font-scale multiplier the 12–35px ramp is expressed against. Persist + re-apply.
- Display name — a text field for what the app calls you; replaces the human speaker label in the UI and the [human] label in build_context. Default stays human if unset.
Notes: derive, don't hand-set the text ramp (the hook for future light mode). Display-name touches the prompt, not only the UI — models address you by name; still the human role under the hood.
Done when: brightness calms text + persists; font size scales + persists; the name replaces human in the UI and in what models are shown; accent still works; all reconstruct from ui.json on hard refresh with localStorage empty.

## 14C — Scrollbar restyle
Goal: the transcript scrollbar track blends into the background; only the thumb shows, lighter.
- Style the transcript scroll container — track → transcript background (disappears), thumb → a step lighter (low-alpha white) with a subtle hover lift. ::-webkit-scrollbar* (Chromium) plus scrollbar-color / scrollbar-width.
Notes: thumb wide enough to grab (~10–12px). Apply to the transcript + margin panes, not globally.
Done when: track invisible against the transcript background, thumb a lighter grabbable handle, themes with surface tokens.

## Deferred
Light mode — a second elevation ramp (light surfaces stepping darker) + its own text ramp + re-derived border alphas and --accent-text, behind a dark/light/system switch. The 14B brightness control establishes the text-ramp-as-function pattern the light text ramp reuses. (See DEFERRED.md.)

## Order
A (settings container) → B (theme controls) → C (scrollbar). Gate each; suite green, DOM ids intact.

---

## As-built notes (deviations / confirmations worth recording)

- **DOM ids preserved across the move.** The settings button kept id `#providers-btn` (label
  text only changed to "⚙ settings"); `#providers-overlay`/`#providers-close`/`#provider-list`/
  `#judge-select`/`#add-*`/`#export-*`/`#accent-swatches` all kept their ids, just relocated into
  `.tab-pane` panes. `browser_phase7` (Providers = default tab) passed unchanged; `browser_phase12`
  (export → Data tab) and `browser_phase13` (accent → Theme tab) got a one-line `click('.tab[...]')`
  to open the tab before interacting — the only test churn the reorg required.
- **Derived ramps, one input each:** `applyBrightness(level)` sets the four `--text-*` vars from a
  top-lightness (`soft 0.82 / default 0.90 / crisp 0.97`) × fixed proportions `[1, .856, .649, .495]`
  as neutral oklch greys; `applyFontScale(level)` sets `--font-scale` (`0.92 / 1.0 / 1.12`) and the
  whole 12–35px ramp is `calc(px * var(--font-scale))`. Default brightness is 0.90 (calmer than the
  old hardcoded ~0.97) — the requested fix lands by default; "crisp" restores max.
- **Display name reaches the model via one seam:** `context.format_turns(..., human_label)` and
  `room_system(..., human_label)` relabel the `human` role only in the serialized context;
  `modes.converse(..., human_label=...)` threads it; the server passes `ui.json.display_name`.
  Storage keeps `role/speaker = "human"` untouched — only the displayed/spoken name changes.
  (Research panelists are blind and the judge prompt has no `[human]` label, so only converse needed it.)
- **Scrollbar** scoped to `.stream` + `.margin-stream` (not global): transparent track, `--scrollbar-thumb`
  (rgba-white) thumb with a 2px transparent border + `background-clip: padding-box` (≈8px visual, 12px grab),
  hover lift. New tokens `--scrollbar-thumb`/`--scrollbar-thumb-hover` keep it on the token system.
- Gate: `tests/browser_phase14.py` (tabs + switching, brightness ramp + persist, font scale + persist,
  display name in UI *and* build_context, themed scrollbar, reload reconstruction with localStorage empty).
  Full suite 15/15, DOM ids intact.

---

## Expansion (amendment re-sent): stat-chip toggles (14C), markdown artifacts (14D), room preview (14E)

The phase-14 amendment was re-sent with three additions beyond the first pass (settings home,
theme controls, scrollbar). Built C(toggles) → D → E on the same gated discipline.

### 14C — stat-chip checkboxes + model %
Two checkboxes in the Theme tab (**token estimate**, **model %**), persisted to ui.json,
each toggling that piece of the per-participant token chip. **Model %** = a participant's share
of the room's spent tokens, computed client-side over the per-turn `meta.usage` already stored
(`modelPercents()`); Grok/cli is estimate-only so it's `~`-prefixed; missing usage just isn't
counted (never throws). Cost was deliberately omitted (see DEFERRED.md).

### 14D — Markdown artifacts
`engine/artifacts.py`: ONE detection rule — a fenced ` ```markdown ` block (`extract_blocks`);
`save_artifact` writes `<artifacts_dir>/<slug>-<room_id>-<n>.md` (collision-safe, reusing the
export's Windows→WSL path translation); `auto_write` saves every block. Server auto-writes on
each converse/research answer when `artifacts_dir` is set (`_maybe_artifacts`, best-effort, never
fails a turn); `POST /rooms/{id}/artifact` is the manual save (400 if no dir). UI: on a detected
block, **copy** (raw `.md` → clipboard) + **save** controls under the answer/synthesis; the
artifacts dir lives in the Data tab beside the export dir. Markdown-only by construction — no
execution, no other formats, no rendered pane.

### 14E — Room hover preview
`_room_view` gained `created` / `last_ts` / `preview` (the latest answer's first line, truncated —
cheap, no model call). The sidebar shows a debounced (250ms) popover on room hover with models +
both dates + the summary, rendered from `STATE.rooms` (already fetched) so it's instant; dismisses
on mouse-leave. Summary is inserted via `textContent` (no HTML injection).

### As-built notes (expansion)
- The token chip's *fill* is still the client-side `~chars/4` context estimate (toggle: token
  estimate); *model %* is spend-share from stored usage (toggle: model %); *session total* stays
  always-on. With both per-participant toggles off, a chip is just dot + name.
- Artifacts auto-write AND manual-save can both fire (numbered files) — accepted; the manual save
  is the escape hatch for when the dir was unset at generation time.
- Gates: `tests/engine_artifacts.py` (detection / collision-safe save / unset-skip / .md-only) and
  `tests/browser_phase14b.py` (chip toggles + persist + model %, artifact copy→clipboard +
  save→file, hover preview shows + dismisses). Full suite **17/17**, DOM ids intact.
- Deferred this phase: cost estimate, inferred (model-generated) room summary, trajectory graph,
  VS Code progress mirror — recorded in DEFERRED.md.
