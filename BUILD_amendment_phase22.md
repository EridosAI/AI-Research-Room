# BUILD amendment — inline file drop (.md / .txt into the composer) (phase 22)

> **Status: BUILT.** Companion to [BUILD.md](BUILD.md) and the prior amendments. As-built notes at
> the foot. (Numbered 22 — 21 is the shelved margin-intake bookmarklet spec; renumber to taste,
> they're just IDs.)

---

**Goal:** drag-and-drop (or pick) a `.md` / `.txt` file into the composer; it attaches as a chip and,
on send, enters the transcript as context the panel reads — the way you load files at the start of a
chat in claude.ai / Grok.

**Why this is small:** a dropped file becomes a **turn whose `text` is the file content**, so it rides
the existing `turn.text` path your typed messages already use. **No new context-injection plumbing** —
`build_context` is unchanged, the file reaches every panelist exactly like a message, and the
no-leakage invariant is untouched because the file *is* `turn.text`, not metadata. `.md` / `.txt`
keeps ingest trivial: `FileReader.readAsText` → text → done. No extraction, no retrieval (per the prior
discussion: full-text-in-context is the high-fidelity mode, and the only one that works uniformly
across a multi-provider panel).

**Scope:** text files only (`.md`, `.txt`). Code / other text is the same mechanism (it's all
`readAsText`) so the allowlist extends trivially later; PDF / docx (which need extraction) stay out.

## 22.1 — Composer drop + read (frontend)
- Make the composer/input a **drop target**: dragover → a drop affordance (highlight); drop → handle
  the file(s). Add a small **file-picker button** in the composer as the click alternative.
- Read each file with `FileReader.readAsText`. **Allowlist** by extension/type (`.md`, `.txt`); reject
  others with a friendly inline note ("text files only for now"). Guard size (reject `> N` MB).
- Dropped/picked files **stage as removable chips** in the composer (filename + ✕), not sent yet — so
  you can drop several, type your question, and send together (matches claude.ai / Grok, and "drop
  into the input window"). Multiple files → multiple chips.

Done when: dropping or picking a `.md` / `.txt` onto the composer adds a removable chip; the ✕ removes
it; a non-text file is rejected with a clear message; nothing is sent until you hit send.

## 22.2 — File-turn on send (data / backend)
- On **send**, each staged file becomes a **file-turn** emitted **before** the message turn (so context
  reads "here's the document, now my question"): `kind = "file"`, meta carries `filename` + size, and
  `turn.text = "[file: {filename}]\n\n{content}"` (the lightweight header tells the panel it's an
  attached document).
- Allow **send with files + empty message** (just the file-turns) — so you can drop files into a fresh
  room and load them without typing, then ask separately.
- The file-turn rides `turn.text` → it's in forward context for every panelist via the **existing**
  mechanism; `build_context` is not touched. Shared across the panel (common scope), independent
  reasoning over it (separate pools) — consistent with the room model.
- **Snapshot:** content is captured at send; editing the source file later doesn't update the turn —
  re-drop to refresh.

Done when: sending with a staged file creates a file-turn whose `text` carries the content (with the
header), ordered before the message turn; the next panel round's `build_context` includes that
content; an empty-message send with a file still posts the file-turn.

## 22.3 — Transcript rendering (frontend)
- Render a file-turn as a **collapsed file chip** on the user side (filename, size, expand-to-view),
  distinct from a message bubble — don't dump the full text into the transcript UI (it's still in
  context, just not visually sprawled).
- The expanded view shows the content via a **safe path** (`textContent`, or your existing `.md` render
  for `.md`) — **never** innerHTML raw file text.

Done when: a file-turn shows as a labelled chip, expands to show its content safely, and reads as
distinct from typed messages; the transcript stays uncluttered while the content stays in context.

## Gate
- **Engine:** a send with a staged file produces a file-turn whose `text` is `[file: …]\n\n{content}`,
  and that content appears in the next `build_context` output (forward context includes it);
  empty-message-with-file is allowed; oversize / non-text rejected.
- **Browser:** new `tests/browser_phase22.py` — drop/pick stages a chip, ✕ removes it, send emits a
  file-turn rendered as a chip that expands safely (no HTML injection from file content); non-text
  rejected.
- Full suite green; DOM ids intact; the send path is otherwise unchanged for text-only messages.

## Housekeeping
- README: drag-drop / pick `.md` / `.txt` into the composer, the snapshot (re-drop to refresh) model,
  and the cost note (a file-turn is re-sent to every panelist every round — keep loaded files lean).
- DEFERRED.md — the file-features ladder:
  - **Managed library (per room):** a toggleable file set injected as a context **prefix** (the
    togglable, non-turn version from the prior discussion) — keep files in a room and activate only the
    relevant ones; also the per-token cost lever.
  - **Projects (the bigger build):** a container above rooms — multiple rooms sharing a set of
    **project-scoped common files**, à la claude.ai / Grok. Folds cleanly into rooms-as-folders (a
    project folder holding room folders + a shared `files/` dir), with project files injected as the
    managed-prefix into every room in the project. The new part is the project↔room hierarchy, not the
    file mechanism.
  - Margin-intake bookmarklet (drafted as phase 21) also remains deferred.

---

## As-built notes

- **The "no new plumbing" claim held for converse, but research needed a one-line thread.** A file-turn
  flows forward for free in **converse** (`build_context` → `forward_turns` keeps it, since it's not
  `is_panelist_raw`; `format_turns` serializes its `text`). But **research builds a blind, STATELESS
  payload** — `{prompt}\n\n---\n{PANEL_INSTRUCTION}`, *not* `build_context` — so a loaded file would
  reach converse and the judge's forward context but never the research panel (the user's primary
  "thoroughness" mode). Fix: `modes.research` now gathers every file-turn (`_attached_docs`) and
  prepends it to the blind payload with an `===== END ATTACHED FILES =====` marker. `context.py` is
  genuinely untouched; the thread is local to `modes.research`. Files are re-sent to the panel every
  round (the cost note), consistent with `build_context` re-sending all forward turns each converse.
- **A dedicated no-model endpoint, not a research/converse rider.** `/research` and `/converse` both
  require a non-empty prompt and make model calls, so "send files with empty message" couldn't ride
  them. New `POST /rooms/{id}/files` (`modes.attach_file`) appends file-turns under the **main room
  lock** (it's a `main.jsonl` write) and returns `_full_room` — no model call. The client posts files
  **first**, then (optionally) the message, so file-turns are ordered before the message turn naturally.
- **Validation is doubled (client + engine).** The frontend allowlists `.md`/`.txt` + 1 MB and the
  engine re-checks (`TEXT_EXTS`, `MAX_FILE_BYTES`) — the endpoint maps `ValueError` → HTTP 400. Size is
  measured in UTF-8 bytes on the engine side; the staged-chip size is the JS string length (close
  enough for a label).
- **send() validates the round up front.** Research panel/judge selection is checked *before* the file
  flush, so a misconfigured research send (no panel/judge) doesn't half-commit the attachments. A
  files-only send (empty message) skips the model call entirely: it adopts the returned transcript,
  marks read, and returns.
- **Safe render, two paths.** A file-turn renders via `renderFileTurn`: a collapsed `.file-turn` chip
  (📎 filename + size + caret) that expands to the content. `.md` goes through the existing
  DOMPurify-sanitized `renderMd`; everything else uses a `<pre>` with `textContent`. The browser gate
  drops a `.md` containing `<img onerror=…>` and asserts `window.__pwned` never sets — the sanitized
  path neutralizes it. The header (`[file: name]\n\n`) is stripped from the displayed content.
- **Staged files are composer state, cleared on room switch.** `STATE.staged` holds `{filename,
  content}` until send; `switchRoom` clears it (staged files belong to the room you were in). The send
  button is still never globally disabled (multi-room concurrency).
- **Gate:** `engine_phase22.py` (turn shape, allowlist/size guards, forward-context inclusion via
  `build_context`, research blind-payload threading, no-marker-when-no-files) + `browser_phase22.py`
  (stage/remove/reject, files-only send → collapsed chip, safe expand). Full suite green (11 engine +
  18 browser), existing DOM ids intact.
