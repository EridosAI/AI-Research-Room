"""export_md.py — one-way Markdown export of a room into an Obsidian vault.

A room's main.jsonl is canonical; the .md is a GENERATED, read-only export — the
app NEVER parses it back (no correctness property rides on Markdown). Each export
is a full rewrite of <export_dir>/<slug>-<room_id>.md.

Renders the FILTERED view (the same forward view you read, mirroring the margin
background): syntheses foregrounded, raw panelist answers tucked in a collapsed
callout, reasoning in a collapsed callout. The margin is scratch — never exported.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import context, rooms
from . import transcript as T


def _to_wsl_path(p: str) -> str:
    """The server runs inside WSL, but a user naturally types their Obsidian vault
    as a Windows path (C:\\Users\\…). Translate a drive-letter path to its /mnt
    mount so the .md lands where Windows can see it. POSIX paths pass through."""
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", p.strip())
    if m:
        drive, rest = m.group(1).lower(), m.group(2).replace("\\", "/")
        return f"/mnt/{drive}/{rest}"
    return p


def _quote(text: str) -> str:
    """Prefix every line with '> ' for a Markdown blockquote/callout body."""
    return "\n".join("> " + ln for ln in (text or "").splitlines() or [""])


def _frontmatter(meta: dict) -> str:
    title = (meta.get("title") or meta["id"]).replace('"', "'")
    created = (meta.get("ts") or "")[:10]              # YYYY-MM-DD
    parts = meta.get("participants") or []
    tags = ["research-room", *(meta.get("tags") or [])]
    lines = ["---", f'room: "{title}"']
    if created:
        lines.append(f"created: {created}")
    lines.append("participants: [" + ", ".join(parts) + "]")
    lines.append("tags: [" + ", ".join(tags) + "]")
    lines.append("---")
    return "\n".join(lines)


def _reasoning_callout(turn: dict) -> str | None:
    r = (turn.get("meta") or {}).get("reasoning")
    if not r:
        return None
    label = "thinking (summary)" if (turn["meta"].get("reasoning_kind") == "summarized") else "thinking"
    return f"> [!quote]- {label}\n{_quote(r)}"


def _group(turns: list[dict]) -> list[dict]:
    """Group research rounds (by round_id) into one block; converse turns stand alone.
    Mirrors the UI's grouping so the .md reads like the conversation on screen."""
    blocks: list[dict] = []
    round_block = None
    for t in turns:
        rid = (t.get("meta") or {}).get("round_id")
        if t.get("mode") == "research" and rid:
            if not round_block or round_block["rid"] != rid:
                round_block = {"kind": "round", "rid": rid, "prompt": None, "panels": [], "judge": None}
                blocks.append(round_block)
            if t["role"] == "human":
                round_block["prompt"] = t
            elif t["role"] == "judge":
                round_block["judge"] = t
            elif (t.get("meta") or {}).get("is_panelist_raw"):
                round_block["panels"].append(t)
            continue
        round_block = None
        blocks.append({"kind": "turn", "turn": t})
    return blocks


def render_room_md(room_id: str) -> str:
    """Pure render → Markdown string (no file write). Filtered, foregrounded view."""
    meta = rooms.load_room(room_id)
    turns = T.load(rooms.main_path(room_id))
    out: list[str] = [_frontmatter(meta), "", f"# {meta.get('title') or room_id}", ""]

    for b in _group(turns):
        if b["kind"] == "turn":
            t = b["turn"]
            who = "human" if t["role"] == "human" else t["speaker"]
            tag = " *(from margin)*" if (t.get("meta") or {}).get("from_margin") else ""
            out.append(f"**{who}**{tag}")
            out.append("")
            out.append(t["text"].strip())
            rc = _reasoning_callout(t)
            if rc:
                out += ["", rc]
            out.append("")
            continue

        # research round: prompt → synthesis foregrounded → raw panels collapsed
        if b["prompt"]:
            out += [f"**human** *(research)*", "", b["prompt"]["text"].strip(), ""]
        if b["judge"]:
            j = b["judge"]
            out.append(f"**{j['speaker']} — synthesis**")
            out.append("")
            out.append(j["text"].strip())
            rc = _reasoning_callout(j)
            if rc:
                out += ["", rc]
            out.append("")
        if b["panels"]:
            out.append(f"> [!note]- Panel answers (raw, {len(b['panels'])})")
            for p in b["panels"]:
                out.append(f"> **{p['speaker']}**")
                out.append(_quote(p["text"].strip()))
                out.append(">")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def export_room(room_id: str, export_dir: str | None) -> Path | None:
    """Full-rewrite the room's .md into export_dir. Best-effort: unset dir → skip
    (returns None); any write error is the caller's to swallow (never fail a turn)."""
    if not export_dir or not str(export_dir).strip():
        return None
    meta = rooms.load_room(room_id)
    slug = rooms._slug(meta.get("title") or room_id)
    out_dir = Path(_to_wsl_path(str(export_dir))).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{slug}-{room_id}.md"      # <slug>-<id>: readable + collision-proof
    path.write_text(render_room_md(room_id), encoding="utf-8")
    return path
