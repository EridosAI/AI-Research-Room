# BUILD_amendment_phase39 — OpenCode seat v1 + diplomatic channel foundation

**Phase:** 39  
**Status:** Build spec. Decisions settled. Net-new phase — full authorization via this file.  
**Winner:** OpenCode (serve + SSE + runtime MCP)  
**Mode:** Window mode for v1 (pane + adapter + lifecycle). Channel foundation ships with it.  
**Implementer note (Grok 4.5 in Kilo / future seats):** This spec is self-contained. All invariants, testing discipline, and guard patterns are restated or referenced explicitly. CLAUDE.md remains source of truth; a minimal AGENTS.md will be generated as part of bootstrap (see §8). Execute exactly; report judgment calls by name for ratification.

## What ships (done-when)
- OpenCode adapter live: one `opencode serve` per room (native-Linux cwd), session per code seat, SSE bridge to turns.
- Seat eligibility enforced: agents live in `code_seats` (or filtered by backend); never pulled into blind panelists.
- Diplomatic channel foundation: 5 primitives as blocking MCP tools (comment_to_main, query_main_state, ask_design_question, workspace_status, request_compaction). Outbox + approval (auto|control per room.json).
- Workspace enforcement: `workspace_path` in room.json + serve launched with that cwd (native ext4).
- Guard: `_guard_code_channel` injected at call_model for all seats.
- Trajectory already draws promoted notes from code origin — zero new paint work.
- Cost stamping generalized; cancel wired to /interrupt.
- Testing: one mutation set per new file + browser smoke for the pane. All existing gates green.
- Commit + push on gate green.

## Architecture decisions (settled — do not re-derive)
1. **Execution shape** — New `engine/adapters/opencode.py`. Session lifecycle (start/attach/park) + per-turn `chat()` that bridges OpenCode SSE events → on_delta callback (exact shape of room_run_stream in server.py:571–642). `call_model` gets one small additive branch for `backend=="agent"`. Window mode fits perfectly (one forward answer per turn).
2. **Seat model** — `code_seats` key in room.json (parallel to participants). Modes.py consumption updated to filter or exclude backend=="agent" seats from blind panels. R1 (agent-as-blind-panelist) closed in v1.
3. **Channel** — Blocking MCP tools. The tool call does not return until the room answers (outbox/approval). OpenCode already parks cleanly (bake-off validated). Outbox is one primitive: pending crossings sit there; auto mode approves immediately, control mode requires user click. Same path for future concierge.
4. **Workspace** — `workspace_path` added to _MUTABLE (rooms.py:150). On first attach: ensure dir exists on native FS, launch `opencode serve --cwd $workspace_path`. Engine stays on /mnt/c; only agent edits hit fast FS. 40–100× tax avoided.
5. **Long-turn silence** — Bridge OpenCode heartbeat/delta frames through the SSE layer. No uvicorn request timeout exists (server.py:889) — only proxy silence risk. R2 closed.
6. **Cancel** — Client disconnect (app.js:2116 AbortController → server.py:631 is_disconnected) wires to `POST /interrupt` on the OpenCode session.
7. **Cost** — Generalize `_reply_meta.usage` (modes.py:222) pattern for agent turns.
8. **AGENTS.md for code seat** — Generated at bootstrap (or via channel later). Minimal extraction from CLAUDE.md focused on invariants the seat must obey every turn. Points back to full CLAUDE.md. Grok 4.5 in Kilo: treat AGENTS.md as the seat-local contract.

## Exact changes (file:line where known from recon; implementer verifies at HEAD)

**New file: engine/adapters/opencode.py**
- Session manager: start_serve(room_id), attach_or_create_session, park_on_blocking_mcp, interrupt().
- chat(turn) → yields deltas, maps to turn.text + meta (structured events: message.part.*, tool state, session.diff).
- MCP tool registration for the 5 primitives (localhost MCP server inside Fusion or simple stdio bridge).
- Heartbeat passthrough.

**engine/providers.py**
- call_model: small `if backend == "agent":` branch that routes to adapter.chat().
- New `_guard_code_channel(system_lines)` — folds channel awareness + "you have MCP tools for diplomatic crossing" exactly like _guard_no_search / _guard_artifacts (providers.py:480/505). Injected only at call_model.

**engine/modes.py**
- RunBody / room consumption: add `code_seats` handling or backend filter so agent seats never become blind panelists (modes.py:466/516 area).
- Cost stamping generalized.

**engine/rooms.py**
- update_room allowlist: add `workspace_path`, `channel_mode` ("auto"|"control"), `code_seats`.
- _MUTABLE extension.

**engine/margin.py** (or new channel.py)
- Re-use windowed_forward for query_main_state.
- promote() path for comment_to_main with meta.from_code (already draws on trajectory).

**web/server.py**
- Route / room_run_stream already tolerates long streams — extend the on_delta bridge for agent events.
- Cancel path: on disconnect, call adapter.interrupt().

**web/static/app.js**
- Minimal pane for code seat (window mode v1). Reuse existing layout system. Input focus handling for the new pane.
- Outbox UI: pending crossings list + approve buttons (control mode). Auto mode = silent approve.

**New: AGENTS.md (repo root or generated into workspace)**
- Header: "This seat operates under the invariants in CLAUDE.md. Key rules restated below for every turn."
- List:
  - Bright line = forward context exactly (never include raw panelist turns unless meta.is_panelist_raw).
  - Origin colour: stroke = voice of last speaker.
  - Guard-layer injection is the only way to reach the model.
  - Any crossing into main transcript goes through outbox/approval.
  - Workspace edits only inside the assigned native-Linux workspace_path.
  - Testing discipline: falsifiable fixtures + discriminating mutations for anything you write.
  - "Report only, change nothing" on recon tasks.
  - Use the 5 MCP diplomatic tools for communication with main chat.
- Points to full CLAUDE.md for complete discipline + paint conventions.

## Testing discipline (mandatory — same as CLAUDE.md)
- Every assertion paired with evidence the fixture could have failed it.
- Prefer discriminating mutations (deliberate breakage that weak fixtures miss).
- New files get their own mutation set.
- Browser smoke for the pane + outbox UI.
- End-to-end channel round-trip (code seat asks via MCP → outbox → user approve or auto → main answers → code seat receives).
- Workspace enforcement test (edits land only in the native dir).
- Long-turn + cancel test.
- All 23 engine + 34 browser gates remain green.

## Risk closure in v1
- R1 (blind panelist): closed by code_seats + backend filter.
- R2 (silence timeout): closed by heartbeat bridging.
- Remaining 6 risks: logged in the spec comments or DEFERRED; none block ship.

## Commit rhythm
Gate green (mutations + browser smoke + channel round-trip) → commit with message referencing this spec → PUSH → next.

**The spec is the word.** Implement exactly as written. Any judgment call must be named and ratified before commit. Ready for build. 

Grok 4.5 in Kilo: this file + the integration recon report + CLAUDE.md give you everything. Start from the adapter.