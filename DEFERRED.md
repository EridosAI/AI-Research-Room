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

## Cleanup carried into packaging

- **Retire the seeded `/transcript` shim — DONE.** It existed only to keep the pre-rooms
  browser tests' rooms usable. Those tests were migrated onto the real `/rooms` path and
  the shim (legacy `/research`, `/converse`, `/transcript*` endpoints) was removed in the
  docs+cleanup pass. Noted here so the history is legible; nothing left to do.

## Deferred from Phase 14 (settings re-jig / preview / artifacts)

- **Cost estimate** in the token chip. Deliberately omitted now to avoid a stale-pricing
  maintenance tail across 5 models. Revisit with hand-maintained per-model rates,
  subscription-aware (Grok = free at the margin), clearly labelled an estimate. (Model %
  and token estimate shipped in 14C; cost is the piece left out.) Phase 17 added a second
  billable axis — web search is billed per call, so a search-enabled round costs N× search on
  top of tokens; fold that in when cost lands.
- **Inferred room summary.** The hover preview ships the *cheap* version (14E: first line of
  the latest answer, no model call). The upgrade is a model-generated 1-line summary cached in
  `room.json`, regenerated every N new turns.
- **Trajectory graph.** Its own phase after a week of use — spec the swerve/round semantics
  (esp. how a research round renders: N speakers → judge) from real transcripts first.
- **VS Code progress mirror.** Not an embedded IDE — a read-only tail of Claude Code's
  activity/log. Revisit after the week; "mirror CC's progress", not "embed VS Code".

## Next up (not deferred, just not started)

- **Packaging / installable.** The whole point of settling the surface first: package this
  for a friend to install (entry point, pinned deps, the `Room.bat` / shortcut flow, and a
  first-run that creates the vault + config dir cleanly). Build against the now-clean,
  single-behaviour code.
