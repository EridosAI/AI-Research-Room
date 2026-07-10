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
  (or, for the margin, a windowed slice). No summarisation of long histories yet. This is the
  **lossy, complementary** lever to Phase 29's prompt caching: caching makes re-sending the full
  context cheap/fast (lossless) but doesn't shrink it, so when a thread approaches a model's *window*
  (watch the context ring), summarise older turns into a running digest that flows forward in place of
  the raw turns. Per-model compaction (Wave 5) swaps one seat's slice when its ring fills.
- **Verify OpenRouter's 1h cache-TTL passthrough** (Phase 29). Caching defaults to a 1h TTL
  (`cache_control.ttl`), which is an Anthropic extended-cache beta; whether OR forwards it (vs falling
  back to 5m) wants a live check against a real response. The transparent 400-retry already covers
  outright rejection — this is just to confirm long-gap turns actually hit the cache.
- **Global cross-room running poll** (Phase 30). The live in-room "round running" indicator + transcript
  poll follow the ACTIVE room; other rooms' sidebar spinners refresh on the next `/rooms` fetch, not
  continuously. A lightweight global poll (or server push) would keep every room's running state live
  while you sit in a different one. Also: a structured "why absent" surface (auth-expired vs timeout vs
  context-length) layered on the stored error string — right now it's the raw, key-redacted message on
  hover.
- **Mode 3 — hand-up / interject.** Only `converse` and `research` exist. A third mode
  where a model can raise a hand mid-round, or the user injects a steer into an in-flight
  round, was scoped out as its own design.
- **Auth / multi-user.** Single-user, localhost-only by construction (binds `127.0.0.1`,
  config endpoints reject non-loopback). No accounts, sessions, or per-user data. Any
  multi-user story is a separate project, not a flag flip.
- **Surface cli-runner reasoning** (Phase 28). The per-turn metadata popover shows the requested
  thinking level + actual reasoning tokens for api rows. A cli seat (Grok via its runner) DOES reason,
  but exposes no api reasoning param/usage to us, so those turns are marked `off` and show no reasoning
  tokens. If a cli runner ever surfaces its trace/token count, capture it through the same `meta.usage`
  / `meta.reasoning` channel and the popover lights up unchanged.
- **Auto-suggested room tags** (Phase 12). The Obsidian export writes per-room `tags` into the
  `.md` frontmatter, but you set them by hand in room settings. Auto-suggesting tags from the
  transcript via a cheap model is a nice-to-have left out for now.
- **Cross-restart composer drafts** (Phase 31). Per-room drafts are session-only, in-memory
  (`STATE.drafts` / `STATE.marginDrafts`) — they survive room switches but NOT a page reload or
  server restart, on purpose: `ui.json` is a global scalar store and message text doesn't belong
  in a config file. Persisting them wants **per-room** keying (a `draft` field written into the
  room-folder meta on switch/blur), not a `ui.json` key — deferred until "lost my draft on reload"
  is a felt need.
- **Atomic text+file send** (Phase 31). A send carrying both staged files and a message flushes the
  files as committed file-turns *before* the `/run` call, so the two aren't one transaction: if
  `/run` fails, the file-turns remain and only the typed text is preserved (optimistic render covers
  the text only). Making it atomic — commit the file-turns + message + round together, or roll the
  file-turns back on a failed `/run` — is deferred; the current behaviour is flagged in a `send()`
  comment.
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

## Deferred from Phase 32 (per-room artifacts)

- **Persona system-slot hygiene — ONE decision covering BOTH guards.** Two guard-style lines now fold
  into a seat's system prompt inside `call_model`: the no-search guard (Phase 23) and the artifacts-
  awareness line (Phase 32.2). When personas become real, persona-bearing speakers get a persona
  "bible" in that same system slot — so how the guards compose with it (apply before / strip / append
  after the bible) is a SINGLE call owned by the persona amendment, made once for BOTH guards rather
  than per-guard. Guard-layer injection already reaches every seat (incl. future persona ones), so
  nothing is special-cased now. This supersedes the earlier "personas are excluded for free via
  `room_system` replacement" reasoning — `room_system` was never the injection point (it skips the
  judge + blind panelists); `call_model` is, which is exactly why the artifacts line lives there.
- **Atomic / parallel-safe artifact naming.** `save_artifact` names `<slug>-<room_id>-<n>.md` with
  `n = (count of existing matches) + 1` — single-writer-safe under the per-room lock, but two
  concurrent writers could collide on `n`. Fine today (one round per room at a time, and only FORWARD
  turns auto-save — raw panels deliberately do NOT). Revisit with a real atomic allocation (O_EXCL
  create-and-retry, or a per-room counter in `room.json`) if artifact writes ever parallelize.

## Deferred from Phase 33 (artifact viewer pane)

- **Live-file viewer mode.** The viewer renders the turn's own `turn.text` (the ` ```markdown ` block
  as authored) — a snapshot, not the file on disk. When a turn carries `meta.artifact_paths`, a "live"
  toggle could instead read the saved `.md` from disk (via a new read endpoint) so you SEE Claude
  Code's edits to that file. Deferred: needs a file-read endpoint (+ path-safety scoping to the
  artifacts dir) and a refresh/poll story; the snapshot covers the common "read the spec I just
  generated" case.
- **Simultaneous margin + viewer — SHIPPED (Phase 34).** The two right panes now coexist as
  `[transcript | viewer | margin]` whenever the transcript keeps ≥ `MIN_MAIN` (520px); otherwise
  opening one swaps the other (the old behavior, now width-gated). Splitter drags clamp to preserve
  `MIN_MAIN`; window-shrink / sidebar-widen with both open yields the margin (see
  `tests/browser_phase34.py`). Still deferred: **recency-based
  close-on-shrink** — the yield rule is a FIXED "margin first, always" (no tracking of which pane you
  touched last). If that ever annoys (you're actively using the margin and it's the one that vanishes),
  close the least-recently-focused pane instead; needs a per-pane last-interaction timestamp.
- **Margin Esc-dismissal consistency.** The viewer closes on Esc (after overlays); the margin still
  does NOT (× / toggle only). Left asymmetric on purpose — the margin is a persistent workspace, the
  viewer a transient reading pane — but if it reads as inconsistent in use, give the margin the same
  Esc treatment (it would slot in after the viewer in the precedence chain).

## Deferred from Phase 35 (composer fast path)

- **Cross-restart persistence for mode / addressee.** Phase 35 made the composer's mode + addressee
  **session-scoped per-room** (`STATE.roomModes` / `STATE.roomAddressees`, keyed by room id — the
  drafts precedent, no disk keys). They survive room switches but reset to converse + auto on reload,
  by design. Persisting them across restart would ride a **`room.json` key pair** (`session_mode`,
  `session_addressee`) added to the `_default_meta`/`_MUTABLE`/`RoomUpdate` trio (like `viewer_width`)
  — deferred until "my room forgot it was a fusion room" is a felt need.
- **Per-room round effort.** The `#effort` / `#sxs-effort` / `#ya-effort` dropdowns (relabelled "round
  effort") stay **global composer state** (default medium) — lower stakes, and they live inside the
  disclosure. A per-room round-effort would follow the same session-map pattern as mode/addressee.
  Distinct from the durably-per-room **per-model reasoning dial** (`reasoning_effort` in `room.json`,
  the models popover) — do not conflate the two.

## Deferred from the always-up service (tools/)

The `tools/` service kit (`fusion.service.template` + `install-service.sh` /
`uninstall-service.sh` + `windows-autostart.md`) keeps the **server** always up: a systemd
system service (auto-restart, starts at distro boot) plus a Windows logon task that boots the
WSL distro so systemd starts it. One dependency is deliberately **documented, not automated**:

- **Always-up Hermes proxy for the Grok seat.** The Grok panelist needs the Hermes OAuth
  proxy at `127.0.0.1:8645`, whose **OAuth token expires**. A "restart the proxy" unit would
  fake reliability it doesn't have — a running-but-unauthed proxy still can't answer, and the
  seat fails in a way a process-liveness check won't catch. So the server runs always and the
  Grok seat **degrades to absent** until the proxy is relaunched by hand (every other model
  keeps working). A real always-up proxy = its own unit **plus** a token-refresh/re-auth story
  (detect a 401/expired token, re-run the OAuth flow, restart) — deferred until it's a felt
  need. See [tools/windows-autostart.md](tools/windows-autostart.md) for the manual relaunch.
- **Recency/token-refresh generalised.** Same shape would cover any future subscription-CLI
  seat run as a sidecar. Not built; the proxy is the only such seat today.

## Deferred from Phase 36 (converse streaming)

Converse streams over SSE (`POST /rooms/{id}/run/stream`); panel/judge modes stay synchronous.
Three deliberate "not yet"s:

- **Append-the-partial on cancel.** Stop / disconnect **discards** the partial — no ai turn is
  appended, identical to a failed converse (answerless human turn). Keeping the partial (append what
  streamed so far, marked incomplete) needs a **finish flag** on the turn (`meta.finish_reason =
  "aborted"` or similar) + a UI affordance to resume/retry, and a policy for the half-formed text
  (is it forward context?). Deferred until "I stopped it but wanted to keep what it had" is felt. The
  seam is ready: `_StreamAborted` currently unwinds before the append; append-then-mark would branch
  there instead.
- **Reasoning-delta display.** Reasoning deltas (OR `delta.reasoning`, Anthropic `thinking_delta`) are
  **accumulated** into the turn's reasoning slot as today, but NOT streamed to the UI as text — only
  the answer streams live; the thinking appears in its collapsed disclosure once the turn lands.
  Live-streaming the thinking trace (a second growing region above the answer) is additive on the same
  `on_delta` channel — it would need a typed delta (`{kind: "text"|"reasoning", chunk}`) so the client
  routes each to the right region.
- **Streaming the judge synthesis.** The next-most-watched single stream: a fusion round's judge turn
  is one seat producing one forward answer, so it *could* stream like converse while the blind panel
  stays synchronous (panelists run in parallel — nothing to stream coherently). Deferred because it
  means threading `on_delta` into the judge round of `run_mode` + a second streaming route shape (the
  panel completes non-streamed, THEN the judge streams), not the clean single-call converse path.

## Trajectory graph (Phase 37)

- **Bracket overlap layout.** Two margin questions with overlapping windows draw two brackets on the
  same rail column; they overdraw. Harmless (same meaning, same stroke) but it hides how many calls
  read a given span. A nudge/stagger (or a per-bracket x-offset) waits until real margin use produces
  dense overlapping windows — the shape of the fix depends on how they actually cluster.
- **Viewport band / two-way scroll sync.** The rail is a map you can click, but it doesn't show *where
  you are*: no band marking the visible transcript rows, and scrolling the transcript doesn't move
  anything on the rail. Needs a scroll listener on `#stream` (there is none today) or an
  IntersectionObserver — the latter must be re-registered on every `render()`, which rebuilds `#stream`
  on every streaming frame. Deferred until the map is used enough to want the "you are here".
- **Hover labels beyond the native `<title>`.** Each node's tooltip is the browser's native `<title>`
  (speaker + the first 80 chars). A real label — a per-turn *summary* — is the old roadmap dependency
  ("summary infra"); it's the same utility that would feed a summary bar and seed compaction. Optional,
  and deliberately not a blocker.
- **The graph as a second producer of the mode-selection object.** `run_mode`'s docstring has always
  anticipated this: drag on the rail to shape the *next* round (who answers, who judges) instead of
  using the composer dropdown. The selection object is already decoupled from execution, so this is a
  new producer, not a new execution path. The natural first slice is drag-from-human-dot → lane,
  writing the existing session addressee. Phase 37.5's hit geometry (row rects + node circles) is
  kept as *separate elements* from the drawn paths precisely so curves never complicate this, and
  37.6B's centred human lane is incidentally the layout that interaction wants: drag outward from
  the middle, in either direction.
- **Fan-edge hover affordances.** Highlighting a round's whole fan on hover would make a dense
  transcript's rounds pop out individually. Nice, not now.
- **Distinct yes-and pair marking.** Yes-and writes two ordinary forward `converse` turns with no
  `round_id` and no marker on the turns themselves — the mode name survives only in the round-head's
  `meta.selection.mode`, which is **absent on pre-Phase-27 rooms**. v1 therefore draws the pair as what
  it is forward-wise: two bright vertices. Marking the pair (a brace, a shared tint) means tolerating
  "unknown" on old rooms.
- **Legacy margin brackets.** Margin questions written before Phase 37.1 carry only the `window` policy
  string, not `window_ids`. They get a best-effort `ts`-correlated connector and **no bracket**, because
  `ts` is second-granular and the margin deliberately runs under its own lock — a concurrent main append
  in the same second can be wrongly attributed. Backfilling `window_ids` for old margin turns is not
  possible (the snapshot is gone); re-deriving them would bake in exactly that error.

## Next up (not deferred, just not started)

- **Packaging / installable.** The whole point of settling the surface first: package this
  for a friend to install (entry point, pinned deps, the `Room.bat` / shortcut flow, and a
  first-run that creates the vault + config dir cleanly). Build against the now-clean,
  single-behaviour code.
