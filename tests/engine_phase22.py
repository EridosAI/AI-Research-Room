"""engine_phase22.py — inline file drop (.md/.txt → a file-turn the panel reads).

A dropped file becomes a turn whose `text` IS the content, so it rides the ordinary
turn.text forward-context path — no new injection plumbing:
  - attach_file builds a file-turn: text = "[file: {name}]\\n\\n{content}", meta
    {kind:"file", filename, size}; non-text / oversize rejected.
  - the file content flows forward: build_context (converse) includes it, and it is
    NOT marked is_panelist_raw (so the synthesis-only filter keeps it).
  - research is blind + stateless (no build_context), so the doc is threaded into the
    panel's blind payload explicitly — verified by spying on call_model.
  - empty-message-with-file is just attach_file with no following round.

Run:  python tests/engine_phase22.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_TMP = tempfile.mkdtemp(prefix="rr-phase22-")
_CFG = Path(_TMP) / "config.toml"
shutil.copy(REPO / "tests" / "config.toml", _CFG)
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(_CFG)
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
os.environ["RESEARCH_ROOM_SECRETS"] = str(Path(_TMP) / "secrets.json")
sys.path.insert(0, str(REPO))

from engine import modes, providers, rooms, transcript   # noqa: E402
from engine.context import build_context, forward_turns   # noqa: E402

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0


def check(label, cond):
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}")
    if not cond:
        _fails += 1


def main() -> int:
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)

    # --- 1. attach_file builds a file-turn with the documented shape -----------
    print("1. attach_file — file-turn shape (text = content, meta = kind/filename/size)")
    rid = rooms.create_room("file room", participants=["mock"], judge="mock")
    content = "# Title\n\nThe sky is teal in this document."
    turn = modes.attach_file(rid, "notes.md", content)
    check("role/speaker = human", turn["role"] == "human" and turn["speaker"] == "human")
    check("meta.kind == 'file'", (turn.get("meta") or {}).get("kind") == "file")
    check("meta.filename preserved", turn["meta"].get("filename") == "notes.md")
    check("meta.size = utf-8 byte length", turn["meta"].get("size") == len(content.encode("utf-8")))
    check("text carries the [file: …] header + content",
          turn["text"] == f"[file: notes.md]\n\n{content}")

    # --- 2. allowlist + size guard --------------------------------------------
    print("2. guards — non-text extension and oversize rejected")
    try:
        modes.attach_file(rid, "evil.exe", "x"); rejected_ext = False
    except ValueError:
        rejected_ext = True
    check("non-text extension rejected", rejected_ext)
    try:
        modes.attach_file(rid, "big.txt", "x" * (modes.MAX_FILE_BYTES + 1)); rejected_big = False
    except ValueError:
        rejected_big = True
    check("oversize file rejected", rejected_big)
    check(".txt accepted", modes.attach_file(rid, "plain.txt", "hello")["meta"]["kind"] == "file")

    # --- 3. forward context: build_context (converse) includes the file -------
    print("3. forward context — the file content reaches a converse model via build_context")
    turns = transcript.load(rooms.main_path(rid))
    fturns = [t for t in turns if (t.get("meta") or {}).get("kind") == "file"]
    check("file-turn is NOT is_panelist_raw (survives the synthesis-only filter)",
          all(not (t.get("meta") or {}).get("is_panelist_raw") for t in fturns))
    check("file-turn is in the forward view", all(t in forward_turns(turns) for t in fturns))
    ctx = build_context(turns, "mock", "converse", participants=["mock"])
    body = ctx["messages"][0]["content"]
    check("build_context body carries the file content", "sky is teal" in body)
    check("build_context body carries the [file: …] header", "[file: notes.md]" in body)

    # --- 4. research threads the doc into the BLIND payload --------------------
    print("4. research — the attached doc is prepended to each panelist's blind payload")
    seen = {}
    real = providers.call_model

    def _spy(provider_key, payload, tools=False, **kw):
        # the panel call is tools=True; capture its user message content
        if tools:
            seen.setdefault("blind", payload["messages"][0]["content"])
        return real(provider_key, payload, tools=tools, **kw)

    providers.call_model = _spy
    try:
        modes.research(rid, "What colour is the sky here?", effort="low")
    finally:
        providers.call_model = real
    blind = seen.get("blind", "")
    check("blind payload includes the document content", "sky is teal" in blind)
    check("blind payload includes the END-ATTACHED-FILES marker", "END ATTACHED FILES" in blind)
    check("blind payload still ends with the panel instruction",
          "independent experts" in blind)

    # --- 5. a room with NO files → no doc block, no marker --------------------
    print("5. no files → blind payload unchanged (no attached-files marker)")
    rid2 = rooms.create_room("plain room", participants=["mock"], judge="mock")
    seen.clear()
    providers.call_model = _spy
    try:
        modes.research(rid2, "hello?", effort="low")
    finally:
        providers.call_model = real
    check("no marker when no files attached", "END ATTACHED FILES" not in seen.get("blind", ""))

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 22 (inline file drop) checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
