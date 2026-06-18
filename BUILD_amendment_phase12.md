# BUILD amendment — Obsidian export, token indicator, Enter-to-send (phase 12)

> **Status: BUILT.** Build record (companion to [BUILD.md](BUILD.md) and the other amendments).
> Preserved verbatim — current architecture is in [README.md](README.md); deferred items in
> [DEFERRED.md](DEFERRED.md).

---

Extends BUILD.md. Three independent features. Build in this order — the export carries the design risk, the others are quick. All feature-level; none touches the install story.

## Feature A — Markdown export to Obsidian (the one with edges)
Goal: every room renders a readable .md into a user-defined folder, so transcripts live in the vault without copying. JSONL stays canonical; the .md is a generated, one-way, read-only export — the app never parses it back.
Create:

A new setting export_dir (separate from rooms_dir; GET/PUT /ui or settings). Unset → skip export silently, never fail a turn.
engine/export_md.py — render_room_md(room_id) -> str: read main.jsonl, render Markdown, write <export_dir>/<slug>-<id>.md. Pure function, full rewrite (not append).
Trigger on completion of a converse or research turn (debounced — write once the turn lands, not mid-stream).

Notes — the decisions that matter:

Render the filtered view, not the raw log. Reuse forward_turns (or a render variant): syntheses foregrounded; raw is_panelist_raw answers omitted or in a collapsed > [!note]- callout; reasoning optionally in a collapsed block. A flat dump of every raw turn is a noisy mess — the .md should read like the conversation you'd read, mirroring the margin-background decision.
Frontmatter (this is the Obsidian-backlink payoff):

    ---
    room: weft architecture review
    created: 2026-06-17
    participants: [claude, grok, deepseek]
    tags: [research-room]
    ---
Tags: you set them per room for now (a tags field on room.json, surfaced in the room settings); auto-suggesting tags from the transcript via a cheap model is a deferred nice-to-have.

Filename hygiene: sanitise the room name to a safe filename (strip / : \ ? etc.), key the file on <slug>-<room_id> so two rooms named "scratch" don't collide.
Margin is NOT exported — it's scratch; only main.jsonl → <room>.md.
One-way, full-rewrite, never read back — keeps the JSONL truth and the .md from drifting, and keeps every correctness property off Markdown parsing.

Done when: a room with a research round renders a .md in export_dir with correct frontmatter; it shows the filtered view (synthesis foregrounded, raw answers collapsed/omitted, no margin); two same-named rooms don't collide; unset export_dir skips export without erroring; the app never reads the .md back (grep confirms no parse path).

## Feature B — Per-model token / context indicator
Goal: a per-participant chip per room showing context fill and a session total — exact where the API gives it, estimated where it can't, clearly labelled which.
Create:

A pre-send estimate: count build_context's assembled payload locally (chars/4 or a tiktoken-style count), same method for all providers — it's a fill gauge, not a billing figure. Display with a ~ prefix.
Fold in exact usage.input_tokens/output_tokens from each API response into meta, so a room accrues a real running total for the API providers. Grok-CLI has no usage block → stays estimate-only, always ~.
context_window per provider in the registry (you set it; e.g. Kimi 256K, DeepSeek 1M). Chip shows ~X / Y.

Notes:

Honesty: the ~ prefix on every estimate/pre-send number; never render an estimate as exact. Grok's number is always ~.
A missing usage block (Grok, or any failure) must fall back to the estimate, never throw.
Cross-model the pre-send number is approximate (different tokenizers) and exact only retrospectively from usage — that's expected; the chip is for tracking fill, and the windows are large enough now that it mostly reassures.

Done when: each participant shows ~X / Y fill; the session total accrues from real usage for API providers and estimate for Grok; a missing usage block falls back cleanly; estimates are visibly ~-prefixed.

## Feature C — Enter to send, Shift+Enter for newline
Goal: Enter sends, Shift+Enter inserts a newline.
Create: a keydown handler — Enter (no shift) → send + preventDefault; Shift+Enter → newline. Apply to the main composer and the margin's mini-composer, nothing else focusable.
Notes: guard if (e.isComposing) return so an IME candidate-commit isn't swallowed as a send.
Done when: Enter sends and Shift+Enter newlines in both composers; no other focusable element is affected; IME composition commits without sending.

## Order
A (export — design care) → B (token chip — moderate) → C (Enter key — trivial). All independent; gate each.

---

## As-built notes (deviations / confirmations worth recording)

- **A — export trigger lives in the server, not the engine.** `export_dir` is app-level UI
  state in `ui.json`; `web/server._maybe_export(room_id)` fires after a successful
  research/converse/promote, wrapped so it can NEVER fail the turn. `engine/export_md.py` is a
  pure renderer + writer (no `.md` read path — asserted in the test). Margin excluded by only
  reading `main.jsonl`. Filename `{slug}-{room_id}.md` (room_id already unique → collision-proof).
  **WSL path translation:** the server runs inside WSL, so a Windows export path
  (`C:\Users\…`) is translated to its `/mnt/c/…` mount at write time (`_to_wsl_path`), letting
  the user type the natural Windows path and still land the `.md` where Obsidian sees it.
- **B — adapter contract changed** to return `(text, reasoning, usage)`; `call_model` folds
  `usage` into `ModelReply` (exact from the API `usage` block, else a `~chars/4` estimate with
  `exact:false`) and `modes` stamps it onto `meta.usage`. The chip's *fill* number is a
  client-side `~chars/4` estimate of the forward view (same for all providers); the *session
  total* sums `meta.usage` across turns (real for API, estimate for cli, `~` if any estimate).
  Also fixed `_toml_scalar` to emit ints unquoted (so `context_window` round-trips as a number).
- **C — replaced the old ⌘/Ctrl+Enter binding** with Enter-to-send + Shift+Enter newline on both
  composers, `isComposing`-guarded. (Automated IME-commit testing isn't practical in Playwright;
  the guard is in code and covered by review, not a headless assertion.)
- Tests: `tests/engine_phase12.py` (export: filtered render, frontmatter, collision, unset-skip,
  no read-back) and `tests/browser_phase12.py` (Enter/Shift+Enter, token chip ~X/Y + session
  total, export-folder + room-tags UI round-trips).

## Deferred from this phase
- **Auto-suggested tags** from the transcript via a cheap model (tags are user-set for now).
  See [DEFERRED.md](DEFERRED.md).
