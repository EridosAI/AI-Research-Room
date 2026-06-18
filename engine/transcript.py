"""transcript.py — append-only JSONL store. Never rewrite, only append.

One JSON object per turn:
  {"id","ts","mode","role","speaker","text","meta":{...}}

A transcript is just a file (a room's main.jsonl or margin.jsonl). This module
knows nothing about rooms, "current", or titles — those live in rooms.py. Every
op takes an explicit path.

Raw panel answers and judge syntheses are BOTH recorded here (the file is the
complete record of what every model said); the synthesis-only filter for forward
context lives in context.py, not here.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def append(turn: dict, path: str | Path) -> dict:
    """Append one turn to a transcript file (path is required — no global current)."""
    p = Path(path)
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


def last_ai_speaker(path: str | Path) -> str | None:
    for t in reversed(load(path)):
        if t["role"] in ("ai", "judge"):
            return t["speaker"]
    return None
