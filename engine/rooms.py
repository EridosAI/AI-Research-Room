"""rooms.py — a room is a folder. Folder CRUD + per-room state (room.json).

    <rooms_dir>/<room_id>/
      main.jsonl     # the conversation
      margin.jsonl   # side-channel (Phase 10; created lazily on first margin use)
      room.json      # title, participants[], judge, margin_model,
                     # splitter_width, last_read_pos, ts

`participants`, `judge`, and `margin_model` are provider KEYS into the global
registry (config.toml) — never copies of provider config, and never secrets.
Keys live in one place (~/.config/research-room/secrets.json) and are never
duplicated per room.

New rooms start with NO participants and NO judge (a forced decision in the UI);
research over a room is gated until a judge is chosen. Legacy flat transcripts
are migrated into room folders and inherit the currently-enabled providers +
the current research_judge, so existing history stays runnable.

There is no engine-level "current" room: every op takes an explicit room id.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import providers, settings

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _slug(title: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in title.strip())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "room"


def _safe_id(room_id: str) -> str:
    """Reject anything that isn't a plain folder name (no traversal / separators)."""
    if not room_id or "/" in room_id or "\\" in room_id or ".." in room_id \
            or not _ID_RE.match(room_id):
        raise ValueError(f"invalid room id: {room_id!r}")
    return room_id


# ---- paths ------------------------------------------------------------------
def _room_dir(room_id: str) -> Path:
    return settings.ROOMS_DIR / _safe_id(room_id)


def main_path(room_id: str) -> Path:
    return _room_dir(room_id) / "main.jsonl"


def margin_path(room_id: str) -> Path:
    return _room_dir(room_id) / "margin.jsonl"


def rolledback_path(room_id: str) -> Path:
    return _room_dir(room_id) / "rolledback.jsonl"


def _meta_path(room_id: str) -> Path:
    return _room_dir(room_id) / "room.json"


# ---- room.json --------------------------------------------------------------
def _default_meta(room_id: str, title: str) -> dict:
    return {
        "id": room_id,
        "title": title,
        "participants": [],   # provider keys; empty = forced decision in the UI
        "judge": None,        # provider key or null; research gated until set
        "margin_model": None,
        "splitter_width": None,
        "last_read_pos": 0,
        "tags": [],           # user-set; written into the exported .md frontmatter
        "reasoning_effort": {},   # {panelist_key: "high"|"medium"|"low"} overrides; empty = model default
        "ts": _now(),
    }


def _write_meta(room_id: str, meta: dict) -> None:
    _meta_path(room_id).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def _title_from_stem(stem: str) -> str:
    """Display title from a legacy filename `<YYYYMMDD>-<HHMMSS>-<slug>`."""
    parts = stem.split("-", 2)
    if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
        return parts[2].replace("-", " ")
    return stem.replace("-", " ")


# ---- CRUD -------------------------------------------------------------------
def create_room(title: str, *, participants: list[str] | None = None,
                judge: str | None = None) -> str:
    """Create a room folder + room.json; return its id. By default the room has
    no participants and no judge (forced-decision); pass them to seed (used by
    migration and the CLI smoke client)."""
    title = title.strip() or "room"
    room_id = f"{_stamp()}-{_slug(title)}"
    if _room_dir(room_id).exists():                 # same-second collision
        room_id = f"{room_id}-{uuid.uuid4().hex[:4]}"
    d = _room_dir(room_id)
    d.mkdir(parents=True, exist_ok=True)
    main_path(room_id).touch()
    meta = _default_meta(room_id, title)
    if participants is not None:
        meta["participants"] = list(participants)
    if judge is not None:
        meta["judge"] = judge
    _write_meta(room_id, meta)
    return room_id


def load_room(room_id: str) -> dict:
    """Return room.json (with any missing fields backfilled). Tolerates a room
    folder whose room.json is missing by regenerating defaults."""
    room_id = _safe_id(room_id)
    mp = _meta_path(room_id)
    if not mp.is_file():
        if main_path(room_id).is_file():
            meta = _default_meta(room_id, _title_from_stem(room_id))
            _write_meta(room_id, meta)
            return meta
        raise FileNotFoundError(f"no such room: {room_id}")
    stored = json.loads(mp.read_text(encoding="utf-8"))
    meta = _default_meta(room_id, stored.get("title") or _title_from_stem(room_id))
    meta.update(stored)
    meta["id"] = room_id   # id is the folder name, authoritatively
    return meta


_MUTABLE = {"title", "participants", "judge", "margin_model",
            "splitter_width", "last_read_pos", "tags", "reasoning_effort"}


def update_room(room_id: str, **fields) -> dict:
    meta = load_room(room_id)
    for k, v in fields.items():
        if k not in _MUTABLE:
            raise ValueError(f"unknown room field: {k}")
        meta[k] = v
    _write_meta(room_id, meta)
    return meta


def rollback_last_round(room_id: str) -> dict:
    """Remove the last round — every turn from the last human turn to the end — from
    main.jsonl. This is the ONE place we rewrite a transcript (otherwise append-only); it's
    a deliberate admin op, so the removed turns are appended to rolledback.jsonl first
    (undo/audit — nothing is lost). A round-head human turn carries the round_id, so for a
    grouped round (fusion/mapping/side-by-side) this removes the prompt + panels + judge
    together; for converse/yes-and it removes the prompt + its answer(s). Returns
    {removed, remaining}."""
    from . import transcript as T   # local import (no cycle: transcript imports nothing here)
    path = main_path(room_id)
    turns = T.load(path)
    if not turns:
        raise ValueError("nothing to roll back")
    # the last human turn is the head of the last exchange
    cut = next((i for i in range(len(turns) - 1, -1, -1)
                if turns[i].get("role") == "human"), 0)
    removed, kept = turns[cut:], turns[:cut]
    rb = rolledback_path(room_id)
    with rb.open("a", encoding="utf-8") as f:        # preserve removed turns (recoverable)
        for t in removed:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    with path.open("w", encoding="utf-8") as f:      # rewrite main without the last round
        for t in kept:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    meta = load_room(room_id)
    if (meta.get("last_read_pos") or 0) > len(kept):
        update_room(room_id, last_read_pos=len(kept))
    return {"removed": len(removed), "remaining": len(kept)}


def list_rooms() -> list[dict]:
    """All rooms, newest main.jsonl first. Runs migration first (idempotent)."""
    migrate_flat_transcripts()
    settings.ROOMS_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for d in settings.ROOMS_DIR.iterdir():
        if not d.is_dir() or not (d / "main.jsonl").is_file():
            continue
        try:
            meta = dict(load_room(d.name))
        except (ValueError, FileNotFoundError):
            continue
        meta["mtime"] = (d / "main.jsonl").stat().st_mtime
        out.append(meta)
    out.sort(key=lambda m: m["mtime"], reverse=True)
    return out


def room_exists(room_id: str) -> bool:
    try:
        return main_path(room_id).is_file()
    except ValueError:
        return False


# ---- migration --------------------------------------------------------------
def migrate_flat_transcripts() -> list[str]:
    """Idempotently wrap legacy flat <vault>/*.jsonl transcripts into room
    folders. Migrated rooms inherit the currently-enabled providers and the
    current research_judge so existing history stays runnable. Returns the ids
    of rooms created by this call (empty on a no-op / second run)."""
    base = settings.ROOMS_DIR
    if not base.is_dir():
        return []
    flat = sorted(base.glob("*.jsonl"))
    if not flat:
        return []
    try:
        seed_participants = providers.enabled()
        seed_judge = providers.research_judge()
    except Exception:  # noqa: BLE001 — registry unavailable: migrate with empty roster
        seed_participants, seed_judge = [], None

    migrated: list[str] = []
    for f in flat:
        stem = f.stem
        try:
            room_id = _safe_id(stem)
        except ValueError:
            room_id = f"{_stamp()}-{_slug(stem)}"
        if _room_dir(room_id).exists():     # collision with an existing room id
            room_id = f"{room_id}-{uuid.uuid4().hex[:4]}"
        d = _room_dir(room_id)
        d.mkdir(parents=True, exist_ok=True)
        f.rename(main_path(room_id))        # move the transcript, no data loss
        meta = _default_meta(room_id, _title_from_stem(stem))
        meta["participants"] = list(seed_participants)
        meta["judge"] = seed_judge
        _write_meta(room_id, meta)
        migrated.append(room_id)
    return migrated
