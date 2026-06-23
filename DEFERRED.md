# Deferred — deliberate "not yet"

Things consciously left out, with enough context to pick each up later. These are
**decisions, not oversights** — recorded while fresh so a future reader can tell the
difference. Current architecture is in [README.md](README.md); the build record is
[BUILD.md](BUILD.md) + [BUILD_amendment_rooms_margin.md](BUILD_amendment_rooms_margin.md).

## Features

- **`current view` margin window.** The margin's background can be `last turn` / `last 3
  turns` / `full transcript`. The most useful middle value — the turns currently in the
  user's scroll viewport — was deferred because it needs the UI to report what's visible.
  Fast-follow: have the client send the visible turn ids (or a range) and add a
  `window="current_view"` branch in `engine/margin.py`.
- **Multiple margins per room.** One margin per room for now (`margin.jsonl`). Multiple
  named side-channels would mean a margin id in the path + UI tabs. The engine already
  treats the margin as a separate file, so this is additive.
- **Undo stack / redo from `rolledback.jsonl`.** Phase 27 ships SINGLE-level "undo last round" with a
  recoverable log (removed turns appended to `rolledback.jsonl`), not a redo UI. A full undo/redo stack
  (re-apply from the log) and selective mid-transcript edit/delete stay out — rollback is last-round
  only, which matches the "my last round misfired" need without opening transcript surgery.
- **Context compression / summarisation.** Forward context is the full filtered transcript
  (or, for the margin, a windowed slice). No summarisation of long histories yet. When
  rooms get long this is the natural next lever — summarise older turns into a running
  digest that flows forward in place of the raw turns.
- **Mode 3 — hand-up / interject.** Only `converse` and `research` exist. A third mode
  where a model can raise a hand mid-round, or the user injects a steer into an in-flight
  round, was scoped out as its own design.
- **Auth / multi-user.** Single-user, localhost-only by construction (binds `127.0.0.1`,
  config endpoints reject non-loopback). No accounts, sessions, or per-user data. Any
  multi-user story is a separate project, not a flag flip.
- **Auto-suggested room tags** (Phase 12). The Obsidian export writes per-room `tags` into the
  `.md` frontmatter, but you set them by hand in room settings. Auto-suggesting tags from the
  transcript via a cheap model is a nice-to-have left out for now.
- **Light mode — SHIPPED (Phase 15).** Built as a `[data-theme="light"]` CSS surface block +
  mode-aware JS ramps (`applyAccent`/`applyBrightness` fork on `currentTheme`) repainted through a
  single `applyThemeMode()`, behind a dark / light / **system** (`prefers-color-scheme`, live OS
  follow) switch in the Theme tab. Light keeps content + floating surfaces white and lifts them by
  shadow (new `--shadow-*` scale, `none` in dark) instead of dark's lighter-shade elevation. Mode
  persists in `ui.json`; localStorage stays empty. See
  [BUILD_amendment_phase15.md](BUILD_amendment_phase15.md).

## File features ladder (Phase 22 shipped the first rung)

Phase 22 shipped **inline file drop** — drop/pick a `.md` / `.txt` into the composer → a file-turn the
panel reads (content *is* the turn text; converse gets it via `build_context`, research threads it into
the blind payload). See [BUILD_amendment_phase22.md](BUILD_amendment_phase22.md). The rest of the ladder:

- **More text formats.** The allowlist (`modes.TEXT_EXTS` + the JS `FILE_EXTS`) is `.md`/`.txt` only;
  any `readAsText`-able format (code, `.json`, `.csv`, …) is a trivial extension. PDF / docx need
  *extraction* (not just text decode) and stay out until there's a clean extractor path.
- **Managed library (per room).** A toggleable file set injected as a context **prefix** (a non-turn,
  re-orderable, switch-on/off version) — keep files in a room and activate only the relevant ones. Also
  the per-token cost lever (the current model re-sends every file-turn every round; a prefix you can
  toggle off is the way to bound that).
- **Projects (the bigger build).** A container above rooms — multiple rooms sharing a set of
  **project-scoped common files**, à la claude.ai / Grok. Folds into rooms-as-folders (a project folder
  holding room folders + a shared `files/` dir), with project files injected as the managed-prefix into
  every room in the project. The new part is the project↔room hierarchy, not the file mechanism.
- **Margin-intake bookmarklet** (drafted as phase 21) also remains deferred.

## Interaction patterns on the round/mode rails (Phase 25 shipped the framework)

Phase 25 made interaction patterns a category (rounds + a gate; one `run_mode`; selection decoupled
from execution via the mode-selection object). **Phase 26** added Mapping, Yes-and, the blind/transcript
panel toggle, and mode-aware judge labels — all config-level on the rails (see
[BUILD_amendment_phase26.md](BUILD_amendment_phase26.md)). Live modes: Converse, Fusion, Mapping,
Side-by-side, Yes-and. What's left:

- **Source attribution (mapping) + a verification pass.** Both blocked on the SAME new plumbing: a
  `meta`→judge **citations channel** that feeds the panel's web-search citations (which live in `meta`,
  out of forward context) to the judge, so it can attribute each mapped point / verify claims against
  sources. Build the channel once; mapping-attribution and verification both consume it.
- **Debate (later).** Any panel mode with the gate flipped to loop-until-N/conclusion (`gate` is
  `single` today; `loop` is the future value — the one piece `run_mode` doesn't yet implement).
- **Trajectory graph.** A second producer of the mode-selection object — drag the next round's shape on
  the graph instead of via the dropdown. Same `/run` rails, no engine change.
- **`flow: sequential`.** Still declared but unfilled — yes-and didn't need it (B sees A via forward
  context). Waits for a genuine intra-round-sequential mode (e.g. a relay panel); not on the roadmap.

## Considered and rejected (recorded so it isn't re-litigated)

- **Shared-retrieval / common-evidence pool for research rounds.** When web search landed
  (Phase 17), a tempting alternative was to run one search and feed all panelists the *same*
  result set ("controlled comparison"). **Rejected.** Fusion's value is *divergent independent
  exploration* — separate pools, common scope — and the synthesis step is richer when panelists
  drew on genuinely different sources. Common scope is already enforced by the shared panel prompt;
  independent per-panelist search supplies the separate pools with no extra machinery. (Cost: N
  panelists = N× search billing per round — accepted; see the cost-estimate item.)

## Deferred from Phase 18 (research ceiling / truncation)

- **Adapter return → `ChatResult` dataclass.** `*_style.chat()` now returns a 6-tuple
  `(text, reasoning, usage, served_model, search, finish_reason)` — one element added per provenance
  phase (11/16/17/18). Positional and easy to misorder; fold into a small frozen dataclass when next
  in the adapters. Internal only (adapters ↔ `call_model` + a few test unpackings).
- **Per-round web-search cap.** Nothing bounds how many searches an agentic panelist runs (one GLM
  panelist did 77). The larger research ceiling lets the answer finish, but ×N panelists × many
  searches multiplies the OpenRouter bill. A per-round/per-panelist search budget (where the API
  exposes one) is the lever; pairs with the cost-estimate item.

## Decision record — xAI-native search through the Hermes proxy (Phase 19.2 probe)

**Probed live (grok-4.3 via `hermes proxy start --provider xai`), result: does NOT work — fall back.**
The proxy forwards the request body verbatim to xAI's **chat-completions** endpoint, but xAI's current
search (the **Agent Tools API** `web_search` / `x_search`) is **Responses-API-only**: chat-completions
rejects it (`unknown variant 'web_search', expected 'function' or 'live_search'`). The `live_search`
tool variant and the legacy top-level `search_parameters` are both **runtime-deprecated**
("Live search is deprecated. Please switch to the Agent Tools API."). So there is no working
chat-completions search path through the proxy, and Fusion's `openai_style` adapter speaks
chat-completions (a `/responses` adapter would be a whole new dialect, not worth one seat).

**Chosen fallback:** proxy-Grok (grok-4.3) is the **converse/default** seat, search-less (correct for
converse). For Grok-**with**-search in research rounds, use a **second, OpenRouter-routed** Grok seat —
Phase 17's `openrouter:web_search` already covers it (paid, but the free proxy seat stays default).
No `search_dialect` / xAI search branch was built. Revisit only if xAI exposes the Agent Tools API on
chat-completions, or Fusion gains a Responses-API adapter.

## Deferred / dormant from Phase 20 (OpenRouter consolidation)

- **`anthropic_style` + the anthropic/xAI search branches are dormant, not removed.** With every
  active panelist on the `openai` backend (OR rows + proxy-Grok), the Anthropic adapter and the
  Phase-17 anthropic-native search branch aren't exercised; the live search dispatch is effectively
  `openrouter:web_search` (OR rows) or none (proxy-Grok). Kept for a future **direct** Anthropic/xAI
  provider — delete only if that's firmly off the table.
- **proxy-Grok search gap stands.** It's the one search-less seat (Phase 19.2 — xAI search doesn't
  traverse the proxy). For Grok-with-search in research, add an OpenRouter-routed Grok seat.
- **Reasoning effort is per-room by design** (travels with the room, set once, survives switches).
  The only piece deferred: an optional **per-provider preferred default for *new* rooms** (seeding a
  new room above the model's own default) — pending whether you find yourself bumping every new room
  the same way. Until then, new rooms start at the model default.
- **Effort options are metadata-driven** (closed in the 20.4 refinement): read per-model from
  OpenRouter's `/models` `reasoning.supported_efforts` (cached by base_url, reversed to ascending),
  with an optional per-row `supported_efforts` config override. Still deferred: honouring
  `mandatory` (force-on, hide the off case) and `default_effort` per model when seeding a new room
  — minor, pending real use. Today new rooms start at the model default via OR (no override sent).

## Cleanup carried into packaging

- **Retire the seeded `/transcript` shim — DONE.** It existed only to keep the pre-rooms
  browser tests' rooms usable. Those tests were migrated onto the real `/rooms` path and
  the shim (legacy `/research`, `/converse`, `/transcript*` endpoints) was removed in the
  docs+cleanup pass. Noted here so the history is legible; nothing left to do.

## Deferred from Phase 14 (settings re-jig / preview / artifacts)

- **Cost estimate — LARGELY SHIPPED (Phase 23).** Real per-request USD cost now comes from
  OpenRouter's authoritative `usage.cost` (no price table, reflects the actual route), shown
  per-model + as a session total; off-OR seats show *free*. What's still deferred: cost for
  **non-OpenRouter API rows** (no `usage.cost`) would need hand-maintained per-model rates —
  only worth it if a direct (non-OR) billable row comes back. Web search bills separately
  (Phase 17, N× per round); OR folds that into `usage.cost` already, so it's covered for OR seats.
- **Inferred room summary.** The hover preview ships the *cheap* version (14E: first line of
  the latest answer, no model call). The upgrade is a model-generated 1-line summary cached in
  `room.json`, regenerated every N new turns.
- **Trajectory graph.** Its own phase after a week of use — spec the swerve/round semantics
  (esp. how a research round renders: N speakers → judge) from real transcripts first.
- **VS Code progress mirror.** Not an embedded IDE — a read-only tail of Claude Code's
  activity/log. Revisit after the week; "mirror CC's progress", not "embed VS Code".

## Wave 5 — per-model compact-and-swap (the context rings are its trigger surface)

Phase 23 shipped per-model context-fill rings (forward tokens ÷ each model's own window). They were
built per-model on purpose: the end-state is to **compact-and-swap a single model when *its* window
fills** while the others keep going. When that lands, the rings are its trigger and share the same
window data — now the **effective routed window** (Phase 24: `top_provider.context_length` / endpoints-
min, not just the headline) + configured windows for off-OR seats. The new work is the
compaction itself: summarise/evict one seat's slice of forward context, swap in the digest, reset that
ring — without disturbing the other seats' context. Until then the numerator is shared across rings
(they differ only by window); post-compaction each ring reflects its own context. See
[BUILD_amendment_phase23.md](BUILD_amendment_phase23.md).

## Next up (not deferred, just not started)

- **Packaging / installable.** The whole point of settling the surface first: package this
  for a friend to install (entry point, pinned deps, the `Room.bat` / shortcut flow, and a
  first-run that creates the vault + config dir cleanly). Build against the now-clean,
  single-behaviour code.
