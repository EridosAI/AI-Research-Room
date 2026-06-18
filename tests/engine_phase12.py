"""engine_phase12.py — Phase 12 Feature A gate (Obsidian Markdown export), mock-only.

The .md is a generated, one-way, read-only export of main.jsonl. Asserts:
  - a research room renders a .md with correct frontmatter (room/created/participants/tags);
  - it shows the FILTERED view — synthesis foregrounded, raw panel answers in a collapsed
    callout, margin NOT exported;
  - two same-named rooms don't collide (keyed on <slug>-<room_id>);
  - unset export_dir skips silently (no file, no error);
  - the export module is write-only (no .md read-back / parse path).

Run:  python tests/engine_phase12.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_TMP = tempfile.mkdtemp(prefix="rr-phase12-")
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(REPO / "tests" / "config.toml")
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
sys.path.insert(0, str(REPO))

from engine import export_md, margin, modes, rooms     # noqa: E402
from engine import transcript as T                       # noqa: E402

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0


def check(label, cond):
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}")
    if not cond:
        _fails += 1


def main() -> int:
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)
    exp = Path(_TMP) / "obsidian"

    # --- a room with a research round + converse + a margin question ---
    rid = rooms.create_room("Weft Architecture Review",
                            participants=["mock", "mock_cli"], judge="mock")
    rooms.update_room(rid, tags=["weft", "review"], margin_model="mock")
    modes.research(rid, "compare the two designs", effort="low")
    modes.converse(rid, "which did you prefer?", addressed_to="mock")
    margin.margin_turn(rid, "MARGIN_SCRATCH_XYZ side note", model="mock")

    print("1. export renders a .md with frontmatter + filtered view")
    path = export_md.export_room(rid, str(exp))
    check("file written under export_dir", path is not None and path.is_file())
    check("filename keyed on <slug>-<room_id>", path.name == f"weft-architecture-review-{rid}.md")
    md = path.read_text(encoding="utf-8")

    fm = md.split("---")[1] if md.startswith("---") else ""
    check("frontmatter present", md.startswith("---"))
    check("frontmatter room title", 'room: "Weft Architecture Review"' in fm)
    check("frontmatter created date", "\ncreated: " in fm)
    check("frontmatter participants", "participants: [mock, mock_cli]" in fm)
    check("frontmatter tags (research-room + user tags)",
          "tags: [research-room, weft, review]" in fm)

    print("2. filtered view — synthesis foregrounded, raw collapsed, margin excluded")
    check("synthesis foregrounded (heading)", "**mock — synthesis**" in md)
    check("raw panel answers in a collapsed callout", "> [!note]- Panel answers (raw," in md)
    # the converse turn is present
    check("converse turn rendered", "which did you prefer?" in md)
    # the margin is scratch — never exported
    check("margin Q&A NOT in the .md", "MARGIN_SCRATCH_XYZ" not in md)
    # raw panel text appears only inside the callout (quoted), never at top level
    raw = next(t["text"] for t in T.load(rooms.main_path(rid))
               if (t.get("meta") or {}).get("is_panelist_raw"))
    raw_head = raw.splitlines()[0]
    top_level_raw = any(raw_head in ln and not ln.startswith(">") for ln in md.splitlines())
    check("raw panel text not foregrounded (only inside callout)", not top_level_raw)

    print("3. same-named rooms don't collide")
    a = rooms.create_room("scratch", participants=["mock"], judge="mock")
    b = rooms.create_room("scratch", participants=["mock"], judge="mock")
    modes.converse(a, "hi a", addressed_to="mock")
    modes.converse(b, "hi b", addressed_to="mock")
    pa, pb = export_md.export_room(a, str(exp)), export_md.export_room(b, str(exp))
    check("two 'scratch' rooms → two distinct files", a != b and pa != pb and pa.is_file() and pb.is_file())

    print("4. unset export_dir skips silently")
    check("empty export_dir → no write, returns None", export_md.export_room(rid, "") is None)
    check("None export_dir → no write, returns None", export_md.export_room(rid, None) is None)

    print("4b. Windows path → WSL mount (server runs inside WSL)")
    check("C:\\ path translated to /mnt/c",
          export_md._to_wsl_path(r"C:\Users\Jason\Documents\Obsidian")
          == "/mnt/c/Users/Jason/Documents/Obsidian")
    check("POSIX path passes through unchanged",
          export_md._to_wsl_path("/home/jason/vault") == "/home/jason/vault")

    print("5. one-way: the export module never reads a .md back")
    src = (REPO / "engine" / "export_md.py").read_text(encoding="utf-8")
    check("export_md writes .md", "write_text" in src)
    check("export_md has no .md read/parse path", "read_text" not in src)

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 12 Feature A checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
