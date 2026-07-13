# AGENTS.md — code seat contract

This seat operates under the invariants in [CLAUDE.md](CLAUDE.md). Key rules for every turn:

## Where you sit
- **Main transcript** — shared room chat. You do not write it by default.
- **Code pane** — your private harness log + OpenCode session.
- **Workspace** — native-Linux directory for all edits and commands.

## Role
Implement, inspect, and verify in the workspace. You are not a blind panelist in main.

## Diplomatic channel (fusion MCP only path to main)
| Tool | Use |
|------|-----|
| `query_main_state` | Read forward-only main context (`last_1` / `last_3` / `full`) |
| `comment_to_main` | Post a short from_code note (may need outbox approval) |
| `ask_design_question` | Block until the room answers via outbox |
| `workspace_status` | Workspace path, git short status, recent code notes |
| `request_compaction` | Request context compaction via outbox |

Tools may appear as `fusion_<name>`. Prefer them over bash for anything about the room.

## Using main state
- Treat `query_main_state` as shared background; align work to it.
- Do not dump large main excerpts back into main.
- Report results to the room with `comment_to_main` when they need to see them.

## Discipline
- Bright line = forward context only (no raw panelist turns unless stamped).
- Guard-layer injection is the only model path for room seats.
- Workspace edits only under the assigned `workspace_path`.
- Testing: falsifiable fixtures + discriminating mutations for code you write.
- Recon: report only, change nothing, unless asked to implement.
- Bash is for workspace work (build/test/git), not for inventing a path into main.
