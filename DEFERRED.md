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
- **Light mode** (Phase 14). A working light theme is a second elevation ramp (light surfaces
  stepping *darker* with depth) + its own text ramp + re-derived border alphas and
  `--accent-text`, behind a dark / light / system (`prefers-color-scheme`) switch — not a toggle
  on the current near-black system. The 14B text-brightness control already establishes the
  text-ramp-as-function-of-one-input pattern the light text ramp will reuse (`applyBrightness`);
  "system" only makes sense once a light ramp exists.

## Cleanup carried into packaging

- **Retire the seeded `/transcript` shim — DONE.** It existed only to keep the pre-rooms
  browser tests' rooms usable. Those tests were migrated onto the real `/rooms` path and
  the shim (legacy `/research`, `/converse`, `/transcript*` endpoints) was removed in the
  docs+cleanup pass. Noted here so the history is legible; nothing left to do.

## Deferred from Phase 14 (settings re-jig / preview / artifacts)

- **Cost estimate** in the token chip. Deliberately omitted now to avoid a stale-pricing
  maintenance tail across 5 models. Revisit with hand-maintained per-model rates,
  subscription-aware (Grok = free at the margin), clearly labelled an estimate. (Model %
  and token estimate shipped in 14C; cost is the piece left out.)
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
