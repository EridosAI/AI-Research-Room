# BUILD amendment — round-in-progress signal + absent-panelist visibility (phase 30)

> **Status: BUILT.** Prompted by a live report: an 8-minute fusion round read as "fired but stalled"
> when the user returned to the room mid-flight, and a panelist (grok-proxy) had dropped with no way to
> see why. Two legibility fixes. As-built notes at the foot.

---

## 30.1 / 30.4 — Absent-panelist visibility
A failed panelist is dropped as *absent* (never silent agreement), but the reason only reached the
judge prompt and was then lost. Now `run_mode` stamps `meta.absent = [{speaker, error}]` on the judge
turn, and the round renders **"⚠ dropped (not counted): <seat>"** with the error on hover. So "why did
grok-proxy drop?" is answerable in the UI. Like all `meta`, it never enters forward context.

## 30.2 / 30.3 — Round-in-progress signal
The per-send status line is cleared on room switch (so one room's status doesn't bleed into another),
which meant a backgrounded or long round looked **idle** from inside the room. Now:
- the server tracks in-flight rounds (`_active_rounds`, marked around `/run`) and exposes `running` on
  every room view;
- returning to a room with a round in flight shows an in-room **"a round is running in this room…"**
  spinner, reconstructed from `room.running` (not the per-send status), and the room shows a **spinner
  in the sidebar** while you're elsewhere;
- the client **polls the active room every 3s while it's running**, so the panels + synthesis appear
  live, then the indicator clears when it finishes.

## Gate
- **Engine** `engine_phase30`: a failed panelist → `meta.absent` on the judge turn (seat + non-empty
  error); a clean round omits it; the reason is NOT in `build_context`; side-by-side records it too.
- **Browser** `browser_phase30`: fire a slow fusion round (sleeping `mockslow` + failing `mockfail`),
  leave the room → the running room shows a sidebar spinner; return → the in-room "running" indicator
  shows and then clears when the synthesis lands; the dropped `mockfail` renders as "dropped (not
  counted)" with its reason on hover.
- Full suite green (18 engine + 25 browser + the rollback race).

## Housekeeping
- README: the round-in-progress signal (in-room + sidebar) and absent-panelist visibility.
- DEFERRED: a global cross-room running poll (today the live in-room indicator follows the ACTIVE room;
  other rooms' sidebar spinners update on the next `/rooms` refresh, not continuously); a structured
  "why absent" surface (auth vs timeout vs context-length) layered on the stored error.

---

## As-built notes

- **`running` is in-memory, lock-independent.** `_active_rounds` is a per-room counter marked at `/run`
  entry (before the room lock, so a *queued* round also reads as running) and cleared in `finally`. It's
  separate from the room lock — `_running()` is a cheap read used by `_room_view`, so the sidebar + the
  active-room poll both see it without contending for the lock.
- **The signal is reconstructed from server state, not client status.** That's the whole point: the old
  status was tied to the send action and died on room switch. `adoptRoom` now calls
  `watchActiveRoom(view.running)`, so any path that loads a room (switch, activate, poll, send result)
  restores the indicator correctly. A 3s poll of the active room refreshes the transcript live and stops
  itself when `running` clears.
- **Foreground sends are unaffected.** A normal send shows its own detailed status ("fusion: N models
  working + judge synthesizes…"); `watchActiveRoom` only sets the generic "running" message when a round
  is observed via `adoptRoom` (i.e. on returning to the room), and only clears status for a round it was
  actually watching (`_watching` guard) — so it never clobbers a send's status or an unrelated room's.
- **Absent reasons were already computed, just discarded.** `run_mode` already built `absent =
  [(speaker, error)]` for the judge prompt; Phase 30 just also stamps it on the judge turn meta. Zero
  new failure handling — the degradation path is unchanged. The error strings are already key-redacted
  by the adapters, so they're safe to show.
- **This would have answered the live question.** With it shipped, the grok-proxy drop would have read
  "⚠ dropped (not counted): grok-proxy" with the actual error on hover — auth failure, timeout, or
  whatever it was — instead of silently missing from the panel.
- **Gate:** `engine_phase30.py` + `browser_phase30.py`. Full suite green (18 engine + 25 browser + the
  rollback race proof).
