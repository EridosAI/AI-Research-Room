"""transcript.py — append-only JSONL store. Never rewrite, only append.

One JSON object per turn:
  {"id","ts","mode","role","speaker","text","meta":{...}}

The file lives in the git-tracked vault. Raw panel answers and judge syntheses
are BOTH recorded here (the file is the complete record of what every model said);
the synthesis-only filter for forward context lives in context.py, not here.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import settings


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(title: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in title.strip())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "room"


def make_turn(mode: str, role: str, speaker: str, text: str,
              meta: dict | None = None) -> dict:
    """Build a turn object with id + timestamp."""
    return {
        "id": str(uuid.uuid4()),
        "ts": _now(),
        "mode": mode,
        "role": role,
        "speaker": speaker,
        "text": text,
        "meta": meta or {},
    }


def append(turn: dict, path: str | Path | None = None) -> dict:
    """Append one turn to a transcript (the active one if path is omitted)."""
    p = Path(path) if path is not None else current()
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(turn, ensure_ascii=False) + "\n")
    return turn


def load(path: str | Path) -> list[dict]:
    """Read all turns from a transcript, in order."""
    p = Path(path)
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip()]


# ---- active-transcript management (used by the CLI / web later) -------------
def new(title: str) -> Path:
    settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = settings.VAULT_DIR / f"{stamp}-{_slug(title)}.jsonl"
    path.touch()
    set_current(path)
    return path


def current() -> Path:
    if not settings.CURRENT_PTR.is_file():
        raise FileNotFoundError("no active transcript — run `room new \"<title>\"` first")
    p = Path(settings.CURRENT_PTR.read_text(encoding="utf-8").strip())
    if not p.is_file():
        raise FileNotFoundError(f"active transcript missing: {p}")
    return p


def set_current(path: str | Path) -> None:
    settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)
    settings.CURRENT_PTR.write_text(str(path), encoding="utf-8")


def title(path: str | Path) -> str:
    """Best-effort display title from the filename (`<YYYYMMDD>-<HHMMSS>-<slug>.jsonl`)."""
    stem = Path(path).stem
    parts = stem.split("-", 2)
    if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
        return parts[2].replace("-", " ")
    return stem


def last_ai_speaker(path: str | Path) -> str | None:
    for t in reversed(load(path)):
        if t["role"] in ("ai", "judge"):
            return t["speaker"]
    return None
