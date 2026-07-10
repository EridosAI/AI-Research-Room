# Research Room

A multi-model research room: a headless **engine** plus thin **clients** (a CLI and a
local web UI) that let several LLMs — Claude, Grok, Kimi, DeepSeek, or any
OpenAI-compatible endpoint you add — work shared transcripts. You keep many **rooms**
(each its own conversation), and in any room you can:

- **converse** — address one model; it answers seeing the room so far.
- **research** — a panel of models answers the prompt **blind and in parallel**, then a
  **judge** model synthesizes their answers into one (the "fusion" pattern).
- **margin** — a side-channel inside a room for quick side-questions that read the main
  chat as background but never pollute it (until you explicitly copy one answer across).

The engine owns the data and all orchestration; clients are pure views over it.
**API keys never live in the repo or the vault.**

---

## Model

Two layers, cleanly split:

- **App-global** — your provider keys (`~/.config/research-room/secrets.json`) and the
  provider registry (`config.toml`: which providers exist, their endpoints/models/auth).
  Keys are entered once, in the sidebar, and **never duplicated per room**.
- **Per-room** — which of those providers are *active in this room*, the room's judge and
  margin model, plus the room's own state. A **room is a folder**:

  ```
  <vault>/<room_id>/
    main.jsonl     # the conversation
    margin.jsonl   # the side-channel (created on first margin use)
    room.json      # title, participants[], judge, margin_model, splitter_width, last_read_pos
  ```

  `participants`/`judge`/`margin_model` are provider **keys** into the global registry —
  never copies of config, never secrets. **New rooms start empty**: you choose their
  models and judge before researching (research is gated until a judge is set).

## Why it's built this way

- **Interaction patterns as rounds + a gate.** A *mode* is an ordered list of *rounds*
  (`participants` all/subset/one/judge · `context` blind/transcript · `flow` · `instruction`
  prompt-modifier · `role` ai/ai-raw/judge) executed by one `run_mode` — no per-mode state
  machine. The live patterns all fold into the same executor — new patterns are new round-specs,
  not new code paths:
  - **Converse** — one model answers, seeing the room's synthesis-only forward context.
  - **Fusion** — blind parallel panel → a judge **synthesizes** one answer.
  - **Mapping** — blind panel → a judge **exposes** the landscape (consensus / divergences-mapped /
    unique signal / takeaway), no merge, no winner.
  - **Side-by-side** — two answers + a "where they differ" **divergence** note.
  - **Yes-and** — A answers, then B builds on A ("yes, and") seeing A via forward context.

  A single `#mode` selector reveals each mode's params contextually and dispatches a **mode-selection
  object** to one `/run` endpoint — selection is decoupled from execution (a future trajectory-graph
  is a second producer of the same object). Panel modes carry a **blind/transcript toggle** ("panel
  sees conversation" — panelists may read room history but stay independent of each other), and each
  judge turn shows a **mode-aware label** (Synthesis / Map / Divergence). The invariant holds by
  construction: a round's `instruction` is a prompt-modifier (never serialized forward), and `ai-raw`
  panel answers stay out of forward context regardless of the context toggle. Each round records
  its **provenance** (the mode + params, incl. the panel-context toggle) on the round-head turn and
  shows it on the prompt line (e.g. `side-by-side · panel saw chat`), so a transcript is
  self-describing about what move ran.
- **Undo last round.** The transcript is append-only, with one deliberate exception: a **"↶ undo
  round"** control removes the most recent round (its prompt + answers + judge turn) from a room. The
  removed turns are written to `rolledback.jsonl` first, so it's recoverable — a clean way to drop a
  misfired round instead of hand-editing the JSONL.
- **Blind panel + judge.** Panelists never see each other's work; only the judge's
  synthesis flows forward into later turns. Raw panel answers are kept for the record and
  the UI's "view full", but are filtered out of model context — the **synthesis-only
  filter**. The margin's background reuses that same filter, so a side-question sees the
  forward view you see, not a flood of raw panel text.
- **Two adapter shapes cover everything.** `openai` (Bearer, `POST {base}/chat/completions`)
  and `anthropic` (`x-api-key`, `POST {base}/v1/messages`). Any OpenAI-compatible service
  (OpenRouter, a local vLLM/Ollama server, …) drops in with no code change.
- **Subscription or API per provider.** `auth_mode` is `api` (HTTP + key) or `cli` (shell
  out to an agentic CLI runner, e.g. Grok on a SuperGrok subscription — **no key**).
- **Graceful degradation.** A failed panelist is dropped and marked *absent* (never treated
  as agreement); a round aborts only if everyone fails. If the **judge** is unavailable it
  falls back to a panelist that answered, so a bad judge can't sink a good round. A dropped
  panelist is shown in the round (**"dropped (not counted): <seat>"**, with the error on hover),
  so you can see *which* model failed and *why* instead of it silently missing.
- **Round-in-progress signal.** A round in flight shows a spinner — in the room you're in
  (reconstructed from server state, so a backgrounded or long round still reads as working when you
  come back, not idle) and as a spinner on the room in the sidebar. The active room polls while a round
  runs, so panels + the synthesis appear live, then the indicator clears when it finishes.
- **Visible reasoning (opt-in, best-effort).** Flip "show reasoning" on a provider and its
  answers carry the model's reasoning, shown as a collapsed "thinking" disclosure in the turn's
  footer. Captured from OpenRouter's `reasoning_details` (summary + text; encrypted entries
  skipped) or `reasoning`, falling back to direct providers' `reasoning_content`. It's stored on
  the turn's `meta`, which `build_context` never serializes — so reasoning is visible only to you
  and **never re-sent to another model**. Providers that don't expose it simply contribute none.
- **Per-model reasoning effort (per room).** Each OpenRouter panelist's square (see the model bar)
  carries a `high / medium / low` effort selector; the choice is stored **per-room, per-panelist**
  (it travels with the room) and sent as OR's `reasoning: {effort}` next turn. New rooms start at
  the model's default (Opus 4.8 = high, so Claude thinks out of the box). Models with no effort
  control (the proxy-Grok seat) omit the selector.
- **Model-square bar.** Above the composer, one square per active panelist — a context-fill ring
  around the speaker dot + that model's token spend. Hover (or tap) opens a popover with the effort
  selector (present in both converse and research), full token count, share of the room's spend, **real
  USD cost**, and **context used / window**; a session-total chip (tokens · cost) sits at the end. The
  popover is built from a declarative cell list, so adding a field is a one-line append.
- **Real cost surfacing.** OpenRouter returns the authoritative per-request USD cost (`usage.cost`),
  captured to the turn's meta and shown as accumulated per-model cost in the popover plus a session
  total. Off-OpenRouter seats (proxy-Grok, CLI subscriptions) show **free**. Like tokens, cost rides
  `meta` and never re-enters forward context.
- **Per-model context gauge.** Each tile's ring shows that model's forward-context fill against **its
  own** window, ramping green → amber → red as it nears the limit — watched per model so a single seat
  can be refreshed when *its* window fills (the trigger surface for per-model compaction). The ring
  calibrates to the **effective routed window**, not just the headline: OpenRouter routes a model
  across providers that may serve a smaller window (common for multi-provider open-weight seats), so
  the gauge uses `top_provider.context_length` (or the per-endpoint floor) to warn before the *real*
  limit. A small dot in the popover flags a window that's **reduced** from the headline or **changed**
  since it was seeded, with both numbers in its tooltip.
- **Copy button.** Every model answer's footer has a copy button (copies the turn's text), beside the
  thinking / model / sources affordances.
- **Add models from a dropdown.** Adding a provider offers a searchable list of OpenRouter's models
  (live from `/models`); picking one seeds the row's context window and reasoning support. Any
  OpenAI-compatible endpoint can still be added by hand (base_url + typed model id).
- **No-search guard.** A seat with no active web search (proxy-Grok, or any search-off seat) is told so
  in its system prompt — answer from training knowledge, but flag current/real-time facts it can't
  verify instead of presenting them as freshly searched. Capability-driven (tied to the web-search
  flag), so it auto-covers any search-less seat and never fires when search is on.
- **Served-model provenance + per-turn metadata.** Beside "thinking" sits a **model** pill carrying
  `meta.served_model` — what the API *reported* serving the turn (`response.model`), distinct from
  the *configured* model in the header. They're usually equal; when they differ the mismatch is
  recorded and the pill tints (the model's prose can lie about its identity, `response.model`
  can't). Hovering the pill opens a **metadata popover**: the **thinking level requested** (`off` when
  a model's reasoning toggle is off — so the effort dial was inert; else the effort / `default`), the
  **reasoning tokens actually spent** (the real "how hard did it think", vs the requested level),
  tokens, cost, finish reason, and a **"view thinking"** button when a trace exists. Everything rides
  `meta`, so it's excluded from forward context; the Grok-CLI path reports no served model, so the pill
  just doesn't show. The effort dial itself is **greyed with a note when reasoning is off**, so it can't
  silently mislead.
- **Web search (opt-in, per provider).** Flip "web search" on a provider and its **research**
  panelists search the web server-side while answering — Claude's native `web_search` tool, or
  OpenRouter's `web_search` server tool for anything routed through OpenRouter (Grok already
  searches via its CLI runner). Search is **independent per panelist** (separate result pools,
  common scope — divergent exploration is the point), not a shared retrieval layer. Sources land in
  `meta.search` and surface as a collapsed **"sources (N)"** disclosure in the turn footer (links
  scheme-allowlisted to http/https); like reasoning, the trace never re-enters forward context.
  Off by default — search bills per call, so an N-panelist round costs N× search. Converse stays
  no-search.
- **Attached files (drag-drop or pick).** Drop a `.md` / `.txt` onto the composer (or use the 📎
  button); it stages as a removable chip and, on send, becomes a **file-turn** the panel reads —
  the way you load files at the start of a claude.ai / Grok chat. No new context plumbing: the
  file's content *is* the turn's `text`, so it rides the ordinary forward-context path (converse
  via `build_context`; research threads it into the blind panel payload). You can send files with an
  empty message to just load them, then ask separately. It's a **snapshot** — editing the source
  later doesn't update the turn; re-drop to refresh. A file-turn renders as a collapsed chip
  (expand to view; `.md` rendered, anything else as plain text — never raw HTML). **Cost note:** a
  loaded file is re-sent to every panelist every round, so keep attached files lean. Text only for
  now (`.md` / `.txt`); richer formats need extraction (deferred).
- **Obsidian export (opt-in).** Set an export folder and every room renders a read-only `.md`
  there after each turn — the filtered, foregrounded view (syntheses up top, raw panel
  answers in a collapsed callout, margin excluded) with YAML frontmatter (room, date,
  participants, your per-room tags) for backlinks. JSONL stays canonical; the `.md` is a
  one-way, full-rewrite export the app never reads back.
- **Prompt caching.** Converse re-sends the whole transcript every turn (the API is stateless — the
  model keeps nothing between calls), so a long thread would re-pay full prefill each time. Caching marks
  the stable transcript prefix with a `cache_control` breakpoint so OpenRouter/Anthropic serve it from
  cache (~10% of input cost + a big latency win) instead of re-prefilling — the lossless version of "it
  only needs the new turns". TTL defaults to **1h** (the 5-minute default expires between long
  deep-research turns); a cached request that's rejected transparently retries without caching, so it can
  never break a turn. The pill popover shows a **Cached** row when a hit lands. Off via
  `RESEARCH_ROOM_PROMPT_CACHE=0`.
- **Converse streaming.** A converse reply streams token-by-token into a live bubble (Anthropic
  and every OpenAI-compatible backend, incl. OpenRouter/DeepSeek/Moonshot/Grok-proxy); a **Stop**
  button cancels it — the client aborts the request and the server drops the partial (no answer is
  saved, matching a failed converse). The other modes (fusion / mapping / side-by-side / yes-and)
  stay synchronous by design: their value is the finished panel + judge synthesis, not a live feed.
  The JSONL append is unchanged — streaming is a display channel only, so the turn still lands once,
  with full text + reasoning/usage/cost meta. Non-streaming seats (a CLI runner) show a working
  indicator and land in one step.
- **Trajectory graph.** A toggleable rail (`graph`, top-right) draws the shape of the conversation:
  one vertical lane per speaker (human leftmost, then the roster; colours are the speaker dots), and a
  single bright line that visits each turn's lane in order. The bright line traces **forward context
  exactly** — it is a client-side mirror of `forward_turns()`, so raw panel answers hang off it as
  **dim nodes** and never touch it. That makes a fusion round legible at a glance: the line dips out to
  the human, fans into the blind panel, and re-converges on the judge. A **margin rail** on the right
  hangs a connector at the row each side-question was asked beside, bracketing the turns it actually
  read. Clicking any row scrolls the transcript to that turn. Display-only: it renders from turns the
  client already has, and the transcript pane no longer yanks you to the bottom while you read
  scrollback (it follows the bottom only if you were already there).
- **Token / context indicator.** A per-participant chip shows `~X / Y` (estimated context
  fill vs the provider's window) plus a running session total — exact from API `usage` where
  given, estimated (always `~`) for the Grok-CLI path.
- **Linear-aesthetic theme, dark + light.** Depth from stacked lighter surfaces (not outlines) in
  dark, and from shadow over white surfaces in **light** — a `dark / light / system` switch
  (`system` follows the OS live). A single derived accent (one hue → six oklch roles, user-selectable
  and persisted to `ui.json`) recolours every state; the accent's hover/press direction and text
  lightness fork by mode so any hue stays legible on either base. Local **Inter** (vendored woff2, no
  CDN — works offline). All colour routes through CSS custom properties (surfaces in a
  `[data-theme="light"]` block, the text + accent ramps set in JS so they track the active mode);
  speaker-dot identity colours are the one deliberate exception.
- **Settings home + theming.** ⚙ settings is a tabbed panel (Providers / Theme / Data). Theme
  offers **mode** (dark / light / system), accent, **text brightness** (one input derives the whole
  grey ramp, mode-aware), **font size** (a `--font-scale` multiplier), a **display name** the app
  (and the models, via context) address you by, and **token-chip toggles** (token estimate / model
  %). All persist to `ui.json` and survive reload.
- **Markdown artifacts (per-room).** When a model emits a fenced ` ```markdown ` block, the answer
  shows **copy** (raw `.md` → clipboard) and **save** (→ an artifacts folder, collision-safe name);
  auto-written on detection when a folder resolves. The folder is **per-room** — set an "artifacts
  dir" in room settings and that room's specs land there (blank inherits the global Settings → Data
  folder), so a room pinned to a project folder writes where Claude Code reads. Every seat in the
  room (panel, judge, converse — via a system-prompt line) is told the path, an auto-saved block
  stamps the saved path on the turn, and the chip shows the **filename + a "copy path"** button for
  the hand-off. Markdown only — no execution, one rule.
- **Artifact viewer pane.** Click **open** on an artifact chip (or the filename) and the ` ```markdown `
  block renders as a **document** in a right-side pane with its own scroll — headings, tables, nested
  fences — so the transcript stays live while the spec stays in view. Width persists per room, Esc
  closes it (after any open overlay), and switching rooms closes it. Source of truth is the turn's own
  text — no disk read. (Human turns now sit in the same left column flow as model turns; the accent
  tint + label carry "this is me".)
- **Panes coexist on wide screens.** The layout is `[transcript | viewer | margin]` (viewer adjacent
  to the transcript, margin outermost). Viewer and margin open **together** whenever the transcript
  keeps a minimum readable width; on a narrower window opening one closes the other. Splitter drags
  can't crush the transcript, and shrinking the window (or widening the sidebar) with both open yields
  the margin first. No mode to toggle — it just tracks the space you have.
- **Room hover preview.** Hovering a room in the sidebar shows its models, start/last dates, and a
  truncated summary — instantly, from `room.json`/the JSONL, no model call.
- **Multi-room concurrency.** Each room has its own lock, so a slow research round in one
  room never blocks work in another; a round that finishes in a background room lands in
  its own folder and shows an unread dot rather than rendering into the room on screen. The
  margin has a *separate* lock again — a side-question runs even while that room's research
  round is in flight.

## Security model (the part that matters)

- **Keys live outside the repo and the vault** — `~/.config/research-room/secrets.json`,
  `chmod 600`. The git-tracked vault holds transcripts only; an auto-commit can never push
  a key.
- **Keys are write-only over the API.** `GET /providers` returns last-4 + status, never the
  key; keys are redacted from logs and error bodies.
- **Localhost only.** The server binds `127.0.0.1`; provider/config endpoints additionally
  refuse non-loopback callers.
- **Model output is sanitized** (markdown → DOMPurify → DOM) on every bubble, panel card,
  and margin answer, and **fails closed** to plain text if the sanitizer can't load. No
  browser storage — UI state (sidebar, per-room rosters) is reconstructed from the server.

---

## Install

Requires Python 3.11+.

```bash
pip install -e .          # fastapi, uvicorn, httpx, pydantic
```

Providers with `auth_mode = "cli"` also need their CLI installed and authed (e.g. Grok).

## Configure providers

The registry is `config.toml` (base URLs, models, `auth_mode`, `enabled`, colour) — **not
secrets**. It's machine-managed by the web UI but human-readable. The built-in template:

| key | auth | adapter | base_url | model |
|-----|------|---------|----------|-------|
| `claude` | api | anthropic | `https://api.anthropic.com` | `claude-opus-4-8` |
| `grok` | cli | — (`run_grok*.sh`) | SuperGrok subscription | `grok-4` |
| `kimi` | api | openai | `https://api.moonshot.ai/v1` | `kimi-k2.6` |
| `deepseek` | api | openai | `https://api.deepseek.com` | `deepseek-v4-pro` |

A simple setup routes **every reasoning panelist through OpenRouter** (`openai` backend,
`openrouter.ai` base — one billing relationship, one uniform `reasoning: {effort}` shape, and
OpenRouter handles Claude's adaptive-thinking mapping) and keeps **Grok on the Hermes proxy**. With
all active rows on the `openai` backend, the `anthropic` adapter just isn't exercised.

Add more in the UI (⚙ providers) — any OpenAI-compatible endpoint. `base_url` is stored
verbatim; the adapter appends `/chat/completions` (openai) or `/v1/messages` (anthropic) —
it never injects `/v1`, so a base already ending in `/v1` isn't doubled. `research_judge`
names the default synthesizer (each room may override it). Each provider also has a **show
reasoning** toggle (default off) — on, the engine captures that model's reasoning where the
backend offers it (DeepSeek's `reasoning_content`, Claude's summarized thinking) — and a **web
search** toggle (default off) — on, research panelists search the web server-side (Claude's
`web_search` tool, or OpenRouter's for OR-routed models). Both bill per use, hence off by default.

**Set keys through the web UI** (write-only masked field) or drop them into
`~/.config/research-room/secrets.json`. Env vars are honored as a fallback:
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`, `MOONSHOT_API_KEY`, `DEEPSEEK_API_KEY`.
For Grok-on-subscription, keep `XAI_API_KEY` **unset** so it uses the CLI's own auth.

### Optional: Grok via the Hermes OAuth proxy (genuine grok-4.3, free at the margin)

Instead of the CLI Grok runner, you can run [Hermes Agent](https://github.com/NousResearch/hermes-agent)'s
local OpenAI-compatible proxy as a **sidecar** and treat Grok as an ordinary `openai` provider —
which means the served-model pill, reasoning capture, usage and finish_reason all work, and the
seat is a real **grok-4.3** reasoner rather than the CLI's coding-tuned default.

```bash
hermes proxy start --provider xai --host 127.0.0.1 --port 8645   # background sidecar; OAuth attached
```
Then add a provider (⚙ settings → Providers): `backend = openai`, `base_url = http://127.0.0.1:8645/v1`,
`model = grok-4.3`, **any** dummy key (the proxy authenticates via your SuperGrok OAuth, stored and
auto-refreshed in `~/.hermes/auth.json` — Fusion holds no Grok secret). Flip **show reasoning** on to
surface Grok's `reasoning_content`. Fusion doesn't manage the proxy's lifecycle — if it's down, that
Grok seat just degrades to an absent panelist. This is a **personal** convenience and never ships in
the template; a friend instead drops in a key-based Grok row (an xAI key, or OpenRouter) — same
`openai` backend, zero code difference. The CLI runner (`run_grok*.sh`) still works and is superseded,
not removed. (Note: xAI-native web search does **not** traverse the proxy — see [DEFERRED.md](DEFERRED.md);
for Grok-with-search in research rounds use an OpenRouter-routed Grok seat.)

---

## Use

### Web UI (recommended)

```bash
python -m web.server        # → http://127.0.0.1:8765
```

A single static page (vanilla HTML/JS, `marked` + `DOMPurify` from CDN, no build step):

- a **left sidebar** of rooms (create, switch, collapse/resize; an unread dot marks a room
  that updated while you were elsewhere) with **⚙ providers** at the foot;
- a **room view** — colour-coded transcript stream, research rounds rendered as one
  composite block (collapsed panel cards with "view full" above the foregrounded
  synthesis), and a **fast-path composer**: by default just a mode chip + addressee +
  textarea — type and hit Enter. The presiding machinery (mode select, judge, panel,
  round effort) lives behind the chip; click it to expand (it auto-opens for non-converse
  modes, and names the active mode when collapsed). Mode + addressee are remembered
  **per room** for the session;
- a **models** control per room to choose its participants and judge;
- the **margin** — a resizable side-panel with its own model, a window selector
  (`last turn` / `last 3 turns` / `full transcript`), and a "copy to main" on each answer;
- **composer niceties** — the caret lands in the composer on load, room switch and new-room
  (just type); each room keeps its own **draft**, so typed-but-unsent text no longer bleeds
  between rooms (session-only — not saved across a restart); your message appears the instant
  you send it (optimistic), and is left in the composer if the send fails;
- a **⌘K / Ctrl-K room switcher** — a keyboard-first palette: type to fuzzy-filter by room
  title / tag / participant, ↑↓ to move, Enter to jump (the caret lands back in the composer),
  Esc or a backdrop click to dismiss — the same Esc/backdrop grammar now closes every overlay.

### CLI

```bash
./room new "embedding models"      # create a room (folder) in the vault, make it active
./room rooms                       # list rooms (* = active)
./room use <room_id>               # switch active room
./room ask "best open embedding model?"   # research: the room's panel + judge
./room say @deepseek "build on that"       # converse, addressed
./room say "and the tradeoffs?"            # converse, default = last AI speaker
./room show                        # print the active room's transcript
./room who                         # providers + models + key status
```

(`python -m cli.room <cmd>` works too. The CLI seeds new rooms with the enabled providers
so a `new` → `ask` smoke test runs immediately; the web UI forces explicit selection.)

### One-click launch (Windows + WSL)

`python -m web.server --open` starts the server and opens the UI in your browser once it's
accepting connections (opt-in, so headless/test runs stay browser-free). For a
double-clickable / pinnable launcher:

```bash
# from the repo root, create a Desktop shortcut (portable — derives its own paths)
powershell.exe -ExecutionPolicy Bypass -File "$(wslpath -w tools/create_shortcut.ps1)"
# then right-click "Research Room" on the Desktop → Pin to taskbar
```

`Room.bat` is the launcher it points at (the console window it opens *is* the server —
close it to stop). Drop a `room.ico` in the repo root for a custom taskbar icon.

### Run as a service (always-up)

For a pinned tab that stays warm — survives a crash, WSL idle, and a Windows reboot — install
Fusion as a systemd **system** service (WSL with `systemd=true`). It auto-restarts on failure
and starts when the distro boots; `Room.bat` still works for one-off dev runs when the service
is stopped (they share port 8765, so don't run both at once).

```bash
tools/install-service.sh        # render the unit → enable → start → health-check :8765
tools/uninstall-service.sh      # stop + remove it
```

The installer derives the repo, user, and drive-mount from its own location (override with
`--user` / `--repo` / `--port`), renders [tools/fusion.service.template](tools/fusion.service.template)
to `/etc/systemd/system/fusion.service` (needs `sudo`), and re-running it updates the unit and
restarts. To also survive a **Windows reboot**, add the logon task in
[tools/windows-autostart.md](tools/windows-autostart.md) (it boots the distro so systemd starts
the service). The Grok proxy seat is intentionally **not** auto-managed — see that doc.

---

## Layout

```
engine/
  transcript.py     append-only JSONL I/O (a transcript is just a file)
  rooms.py          rooms as folders: CRUD + room.json + legacy migration
  context.py        the synthesis-only forward filter (shared by build_context + margin)
  providers.py      registry (config.toml) + call_model dispatch (api | cli | mock)
  adapters/         openai_style.py, anthropic_style.py
  runners/          cli runners (run_grok*.sh) + mock runners for tests
  modes.py          research(room_id, …) and converse(room_id, …)
  margin.py         the in-room side-channel + copy-to-main
  export_md.py      one-way Markdown export of a room (filtered view + frontmatter)
  artifacts.py      detect + save a model's ```markdown block as a .md
  secrets.py        keys outside the vault, chmod 600
  settings.py       paths (vault, config, secrets, ui)
cli/room.py         CLI client (new/rooms/use/ask/say/show/who)
web/
  server.py         FastAPI (127.0.0.1): /rooms*, /participants, /providers*, /ui, margin
  static/           the single-page UI (sidebar + room view + margin)
    styles.css      Linear-aesthetic token layer; fonts/ holds vendored Inter (local, no CDN)
config.toml         provider registry (NOT secrets)
references/         judge rubric
vault/              rooms live here — point RESEARCH_ROOM_VAULT at your Obsidian vault
tests/              mock-provider engine tests + headless-browser UI tests (Playwright)
BUILD.md            the phased build record (history, not current architecture)
DEFERRED.md         deliberate "not yet" features
_archive/           pre-build scaffolding kept for reference — deliberately dead, not wired in
```

## Testing

Orchestration is validated with **mock providers** (`run_mock*.sh` + a `tests/config.toml`
fixture) at zero token cost — fan-out, judge-sees-N, degradation, the synthesis-only
filter, room isolation, and the margin's isolation. The web UI's security- and
concurrency-critical behaviour runs in a real headless Chromium:

```bash
pip install playwright && playwright install chromium     # dev only

python tests/engine_phase8.py          # rooms as folders: isolation, migration, CLI round
python tests/engine_phase10.py         # margin isolation + windowed background + promote
python tests/engine_phase11.py         # reasoning + served_model: isolation + opt-in capture + adapter capture
python tests/browser_phase6.py         # composite render, view-full, sanitization, fail-closed
python tests/browser_phase7.py         # key round-trip, cli toggle, /test+/models, secrets loop
python tests/browser_phase8.py         # per-round model picker + judge fallback
python tests/browser_phase9.py         # per-round judge override
python tests/browser_rooms_race.py     # multi-room concurrency: slow round in A, work in B
python tests/browser_rooms_sidebar.py  # sidebar, forced-decision, no-localStorage reload
python tests/browser_margin.py         # margin concurrency + UI + copy-to-main + persistence
python tests/browser_reasoning.py      # collapsed 'thinking' disclosure + provider toggle
python tests/engine_phase12.py         # Obsidian export: filtered render, frontmatter, no read-back
python tests/browser_phase12.py        # Enter-to-send + token chip + export/tags UI round-trip
python tests/browser_phase13.py        # theme tokens + accent engine/persistence + local Inter
python tests/browser_phase14.py        # settings tabs + brightness/font/display-name + scrollbar
python tests/engine_artifacts.py       # markdown-artifact detection + collision-safe save
python tests/browser_phase14b.py       # chip toggles + model % + artifact copy/save + hover preview
python tests/browser_phase15.py        # dark/light/system mode: surface + ramp fork, persist, dark unchanged
python tests/browser_phase16.py        # served-model 'model' pill beside thinking + absence/mismatch guard
python tests/engine_phase17.py         # web search: adapter attach/capture + meta.search isolation + e2e
python tests/browser_phase17.py        # 'sources (N)' disclosure + http(s) link allowlist
RR_LIVE=1 python tests/live_phase17.py # OPT-IN, billed: confirm live Anthropic/OpenRouter search shapes
python tests/engine_phase18.py         # research token ceiling + finish_reason capture/normalization
python tests/browser_phase18.py        # ⚠ truncated/incomplete badge keyed off finish_reason
python tests/engine_phase19.py         # Grok-via-proxy provider parses through the existing adapter
python tests/engine_phase20.py         # OpenRouter reasoning request/capture + per-room effort threading
python tests/browser_phase20.py        # model-square bar + reasoning selector + draggable composer split
python tests/engine_phase22.py         # inline file drop: file-turn shape + forward-context + research threading
python tests/browser_phase22.py        # composer file stage/remove/reject + file-turn chip + safe expand
python tests/engine_phase23.py         # cost capture/isolation + no-search guard + OR catalog + config round-trip
python tests/browser_phase23.py        # copy button + cost cell + converse effort + context rings + OR dropdown
python tests/engine_phase24.py         # effective routed window (top_provider/endpoints-min) + reduced/changed flags
python tests/browser_phase24.py        # ring calibrates to effective window + reduced/changed popover dot
python tests/engine_phase25.py         # round/mode framework + side-by-side: ai-raw isolation, degrade, fallback
python tests/browser_phase25.py        # unified mode selector + contextual params + side-by-side via /run
python tests/engine_phase26.py         # mapping + yes-and + panel context toggle (ai-raw kept) + judge_kind
python tests/browser_phase26.py        # mapping/yes-and in the selector, contextual params, mode-aware labels
python tests/engine_phase27.py         # round provenance stamped (not leaked) + rollback whole-round + backup
python tests/browser_phase27.py        # round provenance label + undo-last-round button
python tests/rollback_race.py          # rollback can't truncate a round mid-append (room lock serializes)
python tests/engine_phase28.py         # reasoning-token capture + requested-thinking-level stamp (off/default/effort)
python tests/browser_phase28.py        # model-pill metadata popover + inert effort-dial guard
python tests/engine_phase29.py         # prompt caching: prefix split + cache_control/ttl + 400 fallback + capture
python tests/browser_phase29.py        # cached-token row in the turn popover
python tests/engine_phase30.py         # absent-panelist reasons stamped on the judge turn (not leaked)
python tests/browser_phase30.py        # round-in-progress signal (in-room + sidebar) + absent rendering
python tests/browser_phase31.py        # composer focus + per-room drafts + optimistic send + ⌘K/Ctrl-K switcher
python tests/engine_phase32.py         # per-room artifacts: dir resolution + guard across seats + meta stamp/isolation
python tests/browser_phase32.py        # artifacts-dir overlay round-trip + saved chip (filename + copy-path)
python tests/browser_phase33.py        # artifact viewer pane (open/render/resize/Esc) + human-bubble realignment
python tests/browser_phase34.py        # pane coexistence: wide→both, narrow→swap, splitter clamp, resize/sidebar
python tests/browser_phase35.py        # fast-path composer: disclosure + per-room mode/addressee stickiness
python tests/engine_phase36.py         # converse streaming: adapter SSE deltas + engine on_delta threading + abort
python tests/route_phase36.py          # streaming SSE route: delta*→done, error event, reject non-converse
python tests/browser_phase36.py        # live converse bubble grows + Stop (no ai turn) + room-switch detach
python tests/engine_phase37.py         # margin window anchoring: window_ids == the snapshot, not a re-read
python tests/browser_phase37.py        # trajectory rail: lanes, forward line vs dim panel, jump, margin brackets
```

## Environment

`RESEARCH_ROOM_VAULT` (rooms dir), `RESEARCH_ROOM_HOME` / `RESEARCH_ROOM_SECRETS` (secrets
location), `RESEARCH_ROOM_CONFIG` (registry path), `RESEARCH_ROOM_UI` (sidebar-state file),
`RESEARCH_ROOM_HOST` / `RESEARCH_ROOM_PORT`, `RESEARCH_ROOM_MAX_TOKENS` (converse/margin output
cap, default 8192), `RESEARCH_ROOM_RESEARCH_MAX_TOKENS` (research panelist + judge output cap,
default 32768 — far larger because syntheses and agentic web-search answers run long).

When an answer is cut off (hit the token ceiling, or stopped on an unfinished tool round), the
turn's footer shows a **⚠ truncated / ⚠ incomplete** badge — the engine records `finish_reason`
on every API turn, so a clipped answer is flagged, never silently shown as if complete.

## License

MIT © Jason Dury — see [LICENSE](LICENSE).
