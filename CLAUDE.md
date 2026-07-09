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
  zero token cost. Current suite: **22 engine/route + 32 browser = 54, all green.**
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

## Deploy / run
- `python -m web.server` → http://127.0.0.1:8765 (`--open` also launches a browser).
- `tools/` packages an **always-up** systemd service (+ a Windows-logon kickstart). If it's
  installed, the server is already running on **:8765** — `systemctl status fusion`; don't
  double-launch on that port; `sudo systemctl restart fusion` to pick up code changes.

## Current state (2026-07)
- **Latest:** Phase 36 — **converse streaming** (SSE, `POST /rooms/{id}/run/stream`; panel/judge
  modes stay synchronous). Preceded by Phase 35 (composer fast path) + the `tools/` service kit;
  a Phase 14 follow-up widened the font-size range.
- **Grok is OpenRouter-only.** The old localhost **Hermes-proxy** seat (`grok-proxy` →
  `127.0.0.1:8645`) was removed — it required a separate always-running proxy that shared OAuth
  state with the maintainer's Hermes gateway and interfered with it. **Do not reintroduce a
  `127.0.0.1:8645` proxy seat.** Re-add Grok, if wanted, as an OpenRouter `x-ai/grok-*` row via
  ⚙ Providers (gains web search too; see DEFERRED for the Phase-19.2 xAI-search caveat).
