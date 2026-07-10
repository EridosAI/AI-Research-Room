# CLAUDE.md — Research Room

Operational notes for working in this repo. The **architecture + full feature model** live in
[README.md](README.md); the phased **build history** is [BUILD.md](BUILD.md) + its
`BUILD_amendment_*.md` files; deliberate **"not yet"s** are in [DEFERRED.md](DEFERRED.md). Read
those for *how it works* — this file is just the working conventions and gotchas.

## Shape
Headless **engine** (`engine/`) + thin clients: a CLI (`cli/room.py`) and a localhost FastAPI web
UI (`web/`). A **room is a folder** under `vault/`; several LLMs share transcripts across
converse / research (fusion / mapping / side-by-side / yes-and) / margin modes. One `run_mode`
executes every interaction pattern (rounds + a gate). Keys never live in the repo or the vault.

## Running the tests — TWO interpreters (the #1 gotcha)
- **Engine / route tests** → `.venv/bin/python tests/engine_*.py` (also `route_phase36.py`,
  `rollback_race.py`). The venv carries fastapi / uvicorn / httpx.
- **Browser tests** → `python3 tests/browser_*.py` (the **system** python3, which has Playwright +
  Chromium). Running these under `.venv` fails with `ModuleNotFoundError: playwright`.
- Each test spins its own server on a private port against `tests/config.toml` (mock providers) —
  zero token cost. Current suite: **23 engine/route + 34 browser = 57, all green.**
- **A scroll assertion needs a transcript that actually overflows `#stream`.** With a short fixture
  `maxScroll == 0`, so `scrollTop` is always 0 and every scroll check passes vacuously — a real
  Phase-37 review catch. `browser_phase37.py` seeds two tall rooms and asserts the overflow first.
- A browser-test loop that hits a ~2-min wall is just the harness timeout; run the remainder
  separately with a longer timeout.

## Conventions
- **Commit at each gate.** Each gated phase / distinct concern is its **own commit** — do not pool
  several phases into one working tree (splitting a pooled, hunk-interleaved tree afterward is
  painful). Commit and push **only when asked**.
- **Commit format** (match `git log`): subject `Phase N: <title>` (or `tools:` / `docs:`), a body of
  per-area bullets + a `Gate:` line, ending with a `Co-Authored-By:` trailer.
- **Never commit** `config.toml` — the personal provider registry, kept **skip-worktree** (a live
  `S config.toml` under `git ls-files -v` is *correct*, not a mistake) — or `vault/` transcripts
  (only `vault/.gitkeep` is tracked). Secrets live outside the repo in
  `~/.config/research-room/secrets.json`.
- Invariants worth not breaking: `build_context` is the synthesis-only forward view and never
  serializes `meta.*`; the per-room lock serializes a room's `main.jsonl`; adapter `chat()` returns
  a 6-tuple; the JSONL append is one final line with full text+meta.
- The forward predicate `!(meta.is_panelist_raw)` now has **four** consumers: `context.forward_turns`
  (canonical), `export_md._group`, `groupTurns`, and `isForwardTurn` (the trajectory graph). Change
  the semantics in one and you must change all four.
- **Never call `drawTrajGraph()` from `render()`** — `render()` runs once per animation frame while a
  converse streams. Drive the graph off `adoptRoom` (the single committed-turn mutation point), the
  toggle, a debounced resize, `marginSend` (which returns no room view, so nothing else redraws), and
  composer-state changes (mode / addressee / disclosure controls — the future ghost re-derives; 38.3).
- Graph rendering's knobs are all named at the top of the section: `OP_LANE` / `OP_MID` / `OP_FULL` /
  `OP_GHOST` (the opacity registers — brightness *encodes* forward context, so nothing but a forward
  turn may be full-bright), `OP_HOVER_DIM`, and `CURVE_K` (Bézier handle length). No scattered
  literals. Graph nodes must never carry class `turn` or `round`, and hit geometry (row rects, node
  circles, future intersections) stays a separate element from every drawn path — `.traj-node` and
  `.traj-ghost` are `pointer-events: none`.
- **Paint-to-compose (38.4) has no second store.** The future dots are a VIEW over the composer's
  selection state: a compiling paint writes the SAME DOM controls the picker edits and goes through
  the `#mode` change dispatch (chip, disclosure, redraw). `STATE.paintDots` is non-null ONLY while
  the painted pattern does NOT compile — the overlay (composer untouched; since 38.5B it draws every
  stroke whose endpoints both exist, so validity is visually just "the shape completed" — the chip
  flip stays the only signal send behaviour changed). It clears on send, on room switch, and on any
  picker change. Never render a compiled pattern from the gesture, never make the overlay sticky,
  and never let the overlay branch write selection state.
- **Future row +1 is the ghost round-head (38.5A)** — every round begins with a human turn, so the
  head is always drawn (with the now-connection in the last forward speaker's colour) and is never
  paintable: the hit grid starts at +2, structurally. Grammar offsets count from the head — targets
  +2, judge +3, yes-and discriminator +4.
- The graph's rows are **logical, not per-turn**: `trajRows` collapses a round's raw panelist turns
  onto one shared row (a blind concurrent panel is one event). Spacing runs on the row count. SVG has
  no z-index, so document order *is* depth — the paint order (margin → lanes → fans → trajectory →
  panel dots → vertices → hits) is load-bearing, not cosmetic.
- Every trajectory/fan stroke takes its **ORIGIN** turn's colour (37.7): the line carries the voice
  of whoever just spoke; the dot is where the colour changes hands. Margin connectors/brackets are
  indicators, not trajectory — they stay grey and are exempt from the rule.

## Deploy / run
- `python -m web.server` → http://127.0.0.1:8765 (`--open` also launches a browser).
- `tools/` packages an **always-up** systemd service (+ a Windows-logon kickstart). If it's
  installed, the server is already running on **:8765** — `systemctl status fusion`; don't
  double-launch on that port; `sudo systemctl restart fusion` to pick up code changes.

## Current state (2026-07)
- **Latest:** Phase 38 — the graph's **interaction layer**: hover raises a round's whole fan (one
  attribute on the SVG root + draw-time CSS rules — no per-element style mutation), yes-and hand-offs
  halo (keyed on `meta.selection.mode`, never topology), the rail runs at a **fixed scale** (12
  visible rows, scrolls with the transcript's conditional pin rule) with a 5-row **future zone**
  ghosting what send would do right now, and the future is **paintable** — dots compile to the same
  mode-selection object the composer dispatches (38.4; grammar + judge-glyph cycle + human-dot
  discriminator). Zero engine changes.
- Phase 37 — the **trajectory graph** (a toggleable SVG rail, `graph` button). Its one
  engine edit: `margin_turn` stamps `meta.window_ids` on the margin *question* turn — the exact
  forward turns its window read, captured from the same snapshot as the background. That retired a
  cross-file `ts` correlation that was unsound (the margin runs under its own lock **by design**, and
  `ts` is second-granular with no tiebreaker). Margin turns written before 37.1 have only the policy
  string, so they get a best-effort connector and **no bracket**.
- Preceded by Phase 36 — **converse streaming** (SSE, `POST /rooms/{id}/run/stream`; panel/judge modes
  stay synchronous), Phase 35 (composer fast path), the `tools/` service kit, and a Phase 14 follow-up
  that widened the font-size range.
- `render()`'s bottom-pin is **conditional** since Phase 37: it follows the bottom only if you were
  already there, and otherwise preserves `scrollTop` exactly. `adoptRoom` force-pins on a room switch
  and `send()` force-pins on an explicit send (`_forcePin`).
- **Grok is OpenRouter-only.** The old localhost **Hermes-proxy** seat (`grok-proxy` →
  `127.0.0.1:8645`) was removed — it required a separate always-running proxy that shared OAuth
  state with the maintainer's Hermes gateway and interfered with it. **Do not reintroduce a
  `127.0.0.1:8645` proxy seat.** Re-add Grok, if wanted, as an OpenRouter `x-ai/grok-*` row via
  ⚙ Providers (gains web search too; see DEFERRED for the Phase-19.2 xAI-search caveat).
