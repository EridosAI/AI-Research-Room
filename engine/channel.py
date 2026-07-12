"""channel.py — diplomatic channel foundation (Phase 39).

Blocking MCP primitives for a code seat talking to the main room:

  comment_to_main       — promote a note into main (meta.from_code)
  query_main_state      — windowed synthesis-only forward view
  ask_design_question   — outbox + block until room answers
  workspace_status      — non-blocking status
  request_compaction    — outbox request (auto|control)

Outbox is one primitive: pending crossings sit there; channel_mode=auto
approves immediately, control requires a user click. Channel writes to
main.jsonl take the room lock (caller supplies it) — unlike margin.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import margin, rooms, transcript

PRIMITIVES = (
    "comment_to_main",
    "query_main_state",
    "ask_design_question",
    "workspace_status",
    "request_compaction",
)

# in-process waiters for blocking tools (ask_design_question, control-mode writes)
_waiters: dict[str, threading.Event] = {}
_results: dict[str, Any] = {}
_guard = threading.Lock()


@dataclass
class OutboxItem:
    id: str
    kind: str
    payload: dict
    status: str = "pending"   # pending | approved | rejected | cancelled | answered
    answer: str | None = None
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "payload": self.payload,
            "status": self.status, "answer": self.answer, "ts": self.ts,
        }


def _load_outbox(room_id: str) -> list[dict]:
    return list(rooms.load_room(room_id).get("outbox") or [])


def _save_outbox(room_id: str, items: list[dict]) -> None:
    rooms.update_room(room_id, outbox=items)


def list_outbox(room_id: str) -> list[dict]:
    return _load_outbox(room_id)


def channel_mode(room_id: str) -> str:
    m = rooms.load_room(room_id).get("channel_mode") or "auto"
    return m if m in ("auto", "control") else "auto"


def _append_outbox(room_id: str, kind: str, payload: dict) -> dict:
    item = OutboxItem(id=str(uuid.uuid4()), kind=kind, payload=payload).to_dict()
    items = _load_outbox(room_id)
    items.append(item)
    _save_outbox(room_id, items)
    return item


def _update_item(room_id: str, item_id: str, **fields) -> dict | None:
    items = _load_outbox(room_id)
    found = None
    for it in items:
        if it.get("id") == item_id:
            it.update(fields)
            found = it
            break
    if found is not None:
        _save_outbox(room_id, items)
    return found


def _register_waiter(item_id: str) -> threading.Event:
    ev = threading.Event()
    with _guard:
        _waiters[item_id] = ev
    return ev


def _resolve_waiter(item_id: str, result: Any) -> None:
    with _guard:
        _results[item_id] = result
        ev = _waiters.pop(item_id, None)
    if ev is not None:
        ev.set()


def cancel_pending(room_id: str, reason: str = "cancelled") -> int:
    """Wake every blocked waiter for a room and mark pending items cancelled.

    Called on stream disconnect / interrupt so a parked MCP tool does not hang.
    """
    items = _load_outbox(room_id)
    n = 0
    for it in items:
        if it.get("status") == "pending":
            it["status"] = "cancelled"
            it["answer"] = reason
            _resolve_waiter(it["id"], {"status": "cancelled", "answer": reason})
            n += 1
    if n:
        _save_outbox(room_id, items)
    return n


def approve(room_id: str, item_id: str, *, answer: str | None = None,
            room_lock: Callable | None = None) -> dict:
    """Approve a pending outbox item (control mode). Optionally answer a question."""
    items = _load_outbox(room_id)
    item = next((i for i in items if i.get("id") == item_id), None)
    if item is None:
        raise ValueError(f"no outbox item: {item_id}")
    if item.get("status") != "pending":
        raise ValueError(f"item not pending: {item.get('status')}")

    kind = item["kind"]
    payload = item.get("payload") or {}

    def _do_write():
        if kind == "comment_to_main":
            return comment_to_main(room_id, payload.get("text") or "",
                                   speaker=payload.get("speaker") or "code",
                                   skip_outbox=True)
        if kind == "request_compaction":
            return {"ok": True, "note": payload.get("note") or "compaction requested"}
        if kind == "ask_design_question":
            return {"ok": True, "answer": answer if answer is not None else ""}
        return {"ok": True}

    if room_lock is not None and kind in ("comment_to_main",):
        with room_lock():
            result = _do_write()
    else:
        result = _do_write()

    status = "answered" if kind == "ask_design_question" else "approved"
    item["status"] = status
    item["answer"] = answer if kind == "ask_design_question" else None
    _save_outbox(room_id, items)
    _resolve_waiter(item_id, {"status": status, "result": result, "answer": answer})
    return item


def reject(room_id: str, item_id: str, reason: str = "rejected") -> dict:
    item = _update_item(room_id, item_id, status="rejected", answer=reason)
    if item is None:
        raise ValueError(f"no outbox item: {item_id}")
    _resolve_waiter(item_id, {"status": "rejected", "answer": reason})
    return item


# ---- primitives -------------------------------------------------------------
def query_main_state(room_id: str, window: str = "last_3") -> str:
    """Synthesis-only forward view, windowed — reuses margin.windowed_background."""
    turns = transcript.load(rooms.main_path(room_id))
    return margin.windowed_background(turns, window)


def comment_to_main(room_id: str, text: str, *, speaker: str = "code",
                    skip_outbox: bool = False, wait: bool = True,
                    timeout: float | None = None) -> dict:
    """Append a forward note turn with meta.from_code (promote pattern).

    In control mode (and not skip_outbox), queues for approval and optionally blocks.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("comment_to_main requires non-empty text")

    if not skip_outbox and channel_mode(room_id) == "control":
        item = _append_outbox(room_id, "comment_to_main",
                              {"text": text, "speaker": speaker})
        if not wait:
            return item
        ev = _register_waiter(item["id"])
        if not ev.wait(timeout=timeout):
            return {"status": "timeout", "id": item["id"]}
        with _guard:
            return _results.pop(item["id"], {"status": "unknown"})

    note = transcript.make_turn(
        "converse", "note", speaker, text,
        {"from_code": True, "model": speaker})
    transcript.append(note, rooms.main_path(room_id))
    return note


def ask_design_question(room_id: str, question: str, *,
                        timeout: float | None = None) -> dict:
    """Always blocking: outbox entry + wait for approve(answer=...)."""
    question = (question or "").strip()
    if not question:
        raise ValueError("ask_design_question requires a question")
    item = _append_outbox(room_id, "ask_design_question", {"question": question})
    ev = _register_waiter(item["id"])
    # auto mode still needs a human answer for design questions — but for tests
    # and headless, auto can leave it pending until approve() is called.
    if not ev.wait(timeout=timeout):
        _update_item(room_id, item["id"], status="cancelled", answer="timeout")
        return {"status": "timeout", "id": item["id"]}
    with _guard:
        return _results.pop(item["id"], {"status": "unknown"})


def workspace_status(room_id: str) -> dict:
    """Non-blocking: workspace path, git short status, last-N code notes."""
    room = rooms.load_room(room_id)
    ws = room.get("workspace_path") or ""
    git = ""
    if ws and Path(ws).is_dir():
        try:
            import subprocess
            r = subprocess.run(
                ["git", "status", "--short"], cwd=ws,
                capture_output=True, text=True, timeout=5)
            git = (r.stdout or r.stderr or "").strip()[:2000]
        except Exception as e:  # noqa: BLE001
            git = f"(git status failed: {e})"
    turns = transcript.load(rooms.main_path(room_id))
    notes = [
        {"id": t.get("id"), "text": (t.get("text") or "")[:200], "speaker": t.get("speaker")}
        for t in turns
        if t.get("role") == "note" and (t.get("meta") or {}).get("from_code")
    ][-5:]
    return {
        "workspace_path": ws,
        "channel_mode": channel_mode(room_id),
        "git_status": git,
        "recent_code_notes": notes,
        "outbox_pending": sum(1 for i in _load_outbox(room_id) if i.get("status") == "pending"),
    }


def request_compaction(room_id: str, note: str = "", *, wait: bool = True,
                       timeout: float | None = None) -> dict:
    """Request context compaction — always goes through outbox (control) or auto-ack."""
    item = _append_outbox(room_id, "request_compaction", {"note": note or ""})
    if channel_mode(room_id) == "auto":
        item = _update_item(room_id, item["id"], status="approved") or item
        return {"status": "approved", "id": item["id"], "note": note}
    if not wait:
        return item
    ev = _register_waiter(item["id"])
    if not ev.wait(timeout=timeout):
        return {"status": "timeout", "id": item["id"]}
    with _guard:
        return _results.pop(item["id"], {"status": "unknown"})


# ---- MCP tool dispatch (stdio server entry uses this) -----------------------
def dispatch_tool(room_id: str, name: str, arguments: dict,
                  room_lock: Callable | None = None) -> Any:
    """Run one diplomatic primitive by name. Blocking tools block the caller."""
    args = arguments or {}
    if name == "query_main_state":
        return query_main_state(room_id, args.get("window") or "last_3")
    if name == "workspace_status":
        return workspace_status(room_id)
    if name == "comment_to_main":
        def _write():
            return comment_to_main(
                room_id, args.get("text") or "",
                speaker=args.get("speaker") or "code")
        if room_lock is not None and channel_mode(room_id) == "auto":
            with room_lock():
                return _write()
        return _write()
    if name == "ask_design_question":
        return ask_design_question(room_id, args.get("question") or "")
    if name == "request_compaction":
        return request_compaction(room_id, args.get("note") or "")
    raise ValueError(f"unknown channel tool: {name}")
