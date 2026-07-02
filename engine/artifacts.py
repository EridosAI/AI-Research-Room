"""artifacts.py — save a model's markdown as a first-class .md file.

Scope guard: this is "save a model's fenced ```markdown block as a file", nothing
more — no execution, no sandbox, no other formats, no live-rendered pane. ONE clear
detection rule (a ```markdown fence), reusing the write-to-a-configured-folder
pattern of the Obsidian export (incl. its Windows→WSL path translation).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import rooms, settings
from .export_md import _to_wsl_path

_MD_FENCE = re.compile(r"```markdown[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)


def _global_artifacts_dir() -> str:
    """The global artifacts dir from ui.json (best-effort, "" if unset/unreadable).
    The engine reads only this one key here; the server owns the rest of ui.json."""
    try:
        data = json.loads(settings.UI_FILE.read_text(encoding="utf-8"))
        return (data.get("artifacts_dir") or "").strip() if isinstance(data, dict) else ""
    except (FileNotFoundError, ValueError, OSError):
        return ""


def resolve_artifacts_dir(room_id: str) -> str | None:
    """Per-room artifacts dir with global fallback (Phase 32.1): the room's own
    `artifacts_dir` (room.json) if set, else the global ui.json `artifacts_dir`, else
    None. ONE resolver so the auto-write, the prompt guard line, and the manual-save
    endpoint can never disagree on where a room's artifacts land. The dir is returned
    verbatim (may be a Windows path) — `save_artifact` does the Windows→WSL translation,
    so it is NOT duplicated here."""
    try:
        room_v = (rooms.load_room(room_id).get("artifacts_dir") or "").strip()
    except FileNotFoundError:
        room_v = ""
    if room_v:
        return room_v
    return _global_artifacts_dir() or None


def extract_blocks(text: str) -> list[str]:
    """Every fenced ```markdown block's inner content — the one detection rule."""
    return [b for m in _MD_FENCE.finditer(text or "") if (b := m.group(1).strip())]


def save_artifact(room_id: str, content: str, artifacts_dir: str | None) -> Path | None:
    """Write one artifact to <artifacts_dir>/<slug>-<room_id>-<n>.md (collision-safe,
    like the Obsidian export). Unset dir or empty content → None (skip)."""
    if not artifacts_dir or not str(artifacts_dir).strip() or not (content or "").strip():
        return None
    meta = rooms.load_room(room_id)
    slug = rooms._slug(meta.get("title") or room_id)
    out = Path(_to_wsl_path(str(artifacts_dir))).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    n = len(list(out.glob(f"{slug}-{room_id}-*.md"))) + 1
    path = out / f"{slug}-{room_id}-{n}.md"
    path.write_text(content, encoding="utf-8")
    return path


def auto_write(room_id: str, text: str, artifacts_dir: str | None) -> list[Path]:
    """Auto-write every markdown block detected in a turn's text. Returns the paths."""
    if not artifacts_dir:
        return []
    out: list[Path] = []
    for c in extract_blocks(text):
        p = save_artifact(room_id, c, artifacts_dir)
        if p:
            out.append(p)
    return out
