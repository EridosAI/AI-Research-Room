# BUILD amendment — rooms, sidebar, and the margin (phases 8–10)

> **Status: BUILT.** Build record (companion to [BUILD.md](BUILD.md)). This is the
> amendment that extended the Phases 0–7 plan with multi-room support and the margin.
> Preserved verbatim — current architecture lives in [README.md](README.md); deferred
> items in [DEFERRED.md](DEFERRED.md).

---

Extends `BUILD.md`. Same rules: build one phase at a time, run its **Done when** check before
the next. **Strict dependency order — 8 → 9 → 10 — is not optional:** Phase 8 redefines what "a
transcript" is, and Phase 10 (the margin) is a child of whatever a room becomes in Phase 8.
Building the margin first means rebuilding it twice.

All three are **feature-level** (reuse existing transcripts, providers, `build_context`,
endpoints) — no new external dependency, no change to the install story beyond "data is now
folders of rooms," which is a cleaner thing to package later than loose transcripts.

---

## The model (read before Phase 8)

Two layers, cleanly split:

- **App-global (already built — unchanged):** keys in `~/.config/research-room/secrets.json`;
  the provider registry in `config.toml` (which providers exist, their endpoints/models/auth_mode).
  Configured once, in the sidebar. **Keys are never duplicated per room.**
- **Per-room:** which of those global providers are *active in this room*, plus this room's own
  state. A room is a **folder**:

```
<rooms_dir>/<room_id>/
  main.jsonl     # the conversation
  margin.jsonl   # the side-channel (created lazily on first margin use)
  room.json      # title, participants[], judge, margin_model, splitter_width, last_read_pos, ts
```

`room.json` fields:
- `participants`: list of provider **keys** (e.g. `["claude","grok"]`) referencing the global registry — never copies of config.
- `judge`: a provider key, or **null**. New rooms start null → UI shows a "select" placeholder and **gates research until a judge is chosen**.
- `margin_model`: a provider key, or null (margin prompts to pick on first use).
- `splitter_width`, `last_read_pos`: per-room UI state.

`<rooms_dir>` defaults to the vault path (env-overridable), replacing the flat transcript dir.

**New-room defaults (the forced-decision behaviour):** `participants = []`, `judge = null`,
`margin_model = null`. A new room forces you to select its models before use — no silent default roster.

**Migration:** existing flat transcripts must be wrapped into room folders, idempotently
(`<rooms_dir>/<id>/main.jsonl` + a generated `room.json`). *Recommended call:* migrated rooms
inherit the currently-enabled providers as `participants` and the current `research_judge` as
`judge`, so existing history stays runnable — the empty/forced-decision default is for *newly
created* rooms only. (Flip this if you'd rather force re-selection on old rooms too.)

---

## Phase 8 — Room model (foundation)
**Goal:** a room is a folder; the engine operates per-room by id, with **no global "current"** in the engine layer.
**Create:**
- `engine/rooms.py` — folder CRUD: `create_room(title) -> id` (writes folder + `room.json` with the empty/null defaults), `list_rooms()`, `load_room(id)`, `update_room(id, **fields)`, path helpers `main_path(id)` / `margin_path(id)`.
- One-time, idempotent **migration** of existing flat transcripts into room folders (per the recommended call above).
- Refactor `engine/modes.py` so `research(room_id, prompt)` and `converse(room_id, prompt, addressed_to)` resolve to *that room's* `main.jsonl` and read its `participants`/`judge` from `room.json`. `build_context` reads the specified room's transcript. No reliance on a global current.
- Retire the engine-level `current`/`set_current` (it becomes a UI/CLI concern). `cli/room.py` may keep a convenience "active room" pointer locally, but must call engine ops with an explicit room id.
**Notes:** `participants` are keys into the global registry; `judge=null` means unset. Research over a room fans out to that room's `participants`; converse addresses one of them.
**Done when:** create two rooms; a research round in room A writes only to A's `main.jsonl` using A's roster, B untouched; migration wrapped existing transcripts into folders with zero data loss; `build_context` for a room reads that room's file; `cli/room.py` still drives a round against an explicit room.

## Phase 9 — Sidebar + multi-room (navigation + concurrency)
**Goal:** the collapsible left rail; switch rooms; per-room rosters; background rooms keep running.
**Create:**
- **Server — endpoints carry `room_id`:** `POST /rooms`, `GET /rooms`, `GET /rooms/{id}/transcript`, `POST /rooms/{id}/research`, `POST /rooms/{id}/converse`, `PUT /rooms/{id}` (title/participants/judge/margin_model/splitter/last_read). The app-global provider endpoints (`/providers*`, `/research-judge`) stay as-is.
- **App-level UI state, server-side** (honours the no-`localStorage` rule): a tiny `ui.json` + `GET`/`PUT /ui` for sidebar collapsed-state and width. (Per-room splitter width lives in `room.json`, not here.)
- **UI — left sidebar, Claude-style, minimisable:** lists rooms (+ new, switch, collapse), with **providers** and **settings** as items at the bottom — one nav surface for everything. (This replaces the "tabs" idea; same "switch active room," better container.)
- **Per-room model selection:** a control to pick which configured providers are active in the current room and to set its judge, writing back to `room.json`. A new room prompts model selection; the **judge selector shows a "select" placeholder and research is disabled until a judge is chosen.**
**Notes — concurrency (the one genuinely new failure mode):** every operation carries its room id; the engine writes to *that* room's folder regardless of which room is on screen. A round that finishes in a **non-active** room must **not** render into the active room — write it to its folder and show a subtle indicator (e.g. a dot on that room in the sidebar). The single-room code almost certainly leans on an implicit "current"; make room id an explicit parameter end to end.
**Done when:** sidebar lists/switches/minimises rooms; a new room forces model selection and research stays blocked until a judge is set; fire a slow (mock) research round in room A, switch to B and use it, confirm A's round completes into A's folder without appearing in B; sidebar collapse/width and per-room rosters survive a reload (reconstructed from `ui.json` + `room.json`, not browser storage).

## Phase 10 — The margin (child of a room)
**Goal:** the in-room side-channel — a window inside the window for quick explanations that never touch the main thread.
**Create:**
- `margin.jsonl` per room folder (created lazily). Endpoint `POST /rooms/{id}/margin {prompt}`.
- `engine`: `margin_turn(room_id, prompt)` assembles the margin's context from **two sources** — a *read-only, windowed* slice of the room's `main.jsonl` as labelled background, then `margin.jsonl` as the foreground Q&A — then calls the margin model (`tools=False`) and appends to `margin.jsonl`:
  ```
  system = "You are [margin_model], a side assistant. Below is BACKGROUND — the conversation the
            user is reading (read-only, you are not part of it). Then the user's side-questions to
            you. Answer the latest side-question; you may reference the background."
  body   = "=== BACKGROUND (main transcript) ===\n" + windowed_main + \
           "\n=== SIDE CONVERSATION ===\n" + margin_turns
  ```
  Window setting (from the UI): **`last turn` / `last 3 turns` / `full transcript`** — ship these three. (`current view` — the turns in the user's scroll viewport — is the most useful middle value but needs the UI to report what's visible; add it as a fast-follow.)
- **Copy-to-main (the only backflow):** `POST /rooms/{id}/margin/{turn_id}/promote` appends that one margin answer to `main.jsonl` as a clearly-attributed turn (role `note`, or a human turn prefixed `[from margin]`). Explicit and per-answer — **never automatic.**
- **UI:** a collapsible side panel within the room view, **resizable via a draggable splitter** (persist width to `room.json`); its own mini-composer; a **model dropdown** at top/bottom that picks the margin model per-question (writes `room.json.margin_model`); its own little transcript stream rendering `margin.jsonl` (sanitised via DOMPurify, same as main); the window-size selector; and a **"copy to main"** control on each margin answer.
**Notes:** information flows **one way by default** — main → margin (read-only background); margin → main only on explicit promote. This is what lets you ask freely without derailing the main chat. One margin per room for now.
**Done when:** ask the margin a question with main as background → answer references main content, is stored in `margin.jsonl`, and is **absent from `main.jsonl`**; the main thread's next `build_context` excludes the margin Q&A entirely; "copy to main" appends exactly one attributed turn to `main.jsonl`; the splitter width and margin model persist in `room.json`; margin output is sanitised; switching rooms shows that room's own margin.

---

## Deferred (carry forward)
`current view` margin window; multiple margins per room; context compression/summarisation
(full/windowed transcript only for now); Mode 3 (hand-up/interject); auth/multi-user.
(See [DEFERRED.md](DEFERRED.md) for the consolidated list.)

## Build order
8 (room model) → 9 (sidebar + multi-room) → 10 (margin). Each gated. The margin is built last
because it is a child of a room, and only Phase 8 defines what a room is.
