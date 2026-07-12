# AGENTS.md — code seat contract

This seat operates under the invariants in CLAUDE.md. Key rules restated below for every turn.

- Bright line = forward context exactly (never include raw panelist turns unless meta.is_panelist_raw).
- Origin colour: stroke = voice of last speaker.
- Guard-layer injection is the only way to reach the model.
- Any crossing into main transcript goes through outbox/approval.
- Workspace edits only inside the assigned native-Linux workspace_path.
- Testing discipline: falsifiable fixtures + discriminating mutations for anything you write.
- "Report only, change nothing" on recon tasks.
- Use the 5 MCP diplomatic tools for communication with main chat:
  `comment_to_main`, `query_main_state`, `ask_design_question`, `workspace_status`, `request_compaction`.

See [CLAUDE.md](CLAUDE.md) for complete discipline + paint conventions.
