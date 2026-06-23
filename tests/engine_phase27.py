"""engine_phase27.py — round provenance + roll-back-last-round (offline, mock).

  - provenance: run_mode stamps the mode + its selection params (incl. panel_context) on
    the round-head turn's meta; it stays in meta (never serialized into build_context);
  - rollback: rooms.rollback_last_round removes the last round (last human turn → end),
    preserves the removed turns in rolledback.jsonl, and fixes last_read_pos. A grouped
    round (side-by-side) is removed whole (prompt + panels + judge); converse removes the
    prompt + its one answer.

Run:  python tests/engine_phase27.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_TMP = tempfile.mkdtemp(prefix="rr-phase27-")
_CFG = Path(_TMP) / "config.toml"
shutil.copy(REPO / "tests" / "config.toml", _CFG)
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(_CFG)
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
os.environ["RESEARCH_ROOM_SECRETS"] = str(Path(_TMP) / "secrets.json")
sys.path.insert(0, str(REPO))

from engine import modes, rooms, transcript               # noqa: E402
from engine.context import build_context                    # noqa: E402

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0


def check(label, cond):
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}")
    if not cond:
        _fails += 1


def _human_head(turns):
    return next(t for t in turns if t["role"] == "human")


def main() -> int:
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)

    # --- 1. provenance: mode + panel_context stamped on the round head ----------
    print("1. provenance — mode + selection params stamped on the round-head turn")
    rid = rooms.create_room("prov", participants=["mock", "mockthink"], judge="mock")
    modes.side_by_side(rid, "Compare X.", seats=["mock", "mockthink"], judge="mock",
                       panel_context="transcript")
    turns = transcript.load(rooms.main_path(rid))
    head = _human_head(turns)
    sel = (head.get("meta") or {}).get("selection") or {}
    check("round head carries selection.mode", sel.get("mode") == "side_by_side")
    check("selection records panel_context (transcript)", sel.get("panel_context") == "transcript")
    check("selection records the seats", sel.get("seats") == ["mock", "mockthink"])
    check("selection records the judge", sel.get("judge") == "mock")

    # provenance stays in meta — never serialized into forward context
    body = build_context(turns, "mock", "converse", participants=["mock", "mockthink"])["messages"][0]["content"]
    check("selection NOT leaked into build_context", "panel_context" not in body and "side_by_side" not in body)

    # converse stamps its mode too
    rid_c = rooms.create_room("provc", participants=["mock"], judge="mock")
    modes.converse(rid_c, "hi", addressed_to="mock")
    chead = _human_head(transcript.load(rooms.main_path(rid_c)))
    check("converse round head records mode=converse",
          (chead["meta"].get("selection") or {}).get("mode") == "converse")

    # --- 2. rollback: a grouped round is removed whole --------------------------
    print("2. rollback — a side-by-side round (prompt + panels + judge) removed whole")
    rid2 = rooms.create_room("rb", participants=["mock", "mockthink"], judge="mock")
    modes.converse(rid2, "first message", addressed_to="mock")          # 2 turns
    before = len(transcript.load(rooms.main_path(rid2)))
    modes.side_by_side(rid2, "the round to undo", seats=["mock", "mockthink"], judge="mock")
    mid = transcript.load(rooms.main_path(rid2))
    round_turns = len(mid) - before
    check("side-by-side added a multi-turn round (prompt + 2 panels + judge)", round_turns == 4)

    res = rooms.rollback_last_round(rid2)
    after = transcript.load(rooms.main_path(rid2))
    check("rollback removed exactly the last round", res["removed"] == round_turns)
    check("remaining == the pre-round transcript", len(after) == before and res["remaining"] == before)
    check("the round is gone (no 'the round to undo' turn)",
          all("the round to undo" not in (t.get("text") or "") for t in after))
    check("the prior converse survived", any("first message" in (t.get("text") or "") for t in after))

    # removed turns preserved (recoverable) in rolledback.jsonl
    rb = transcript.load(rooms.rolledback_path(rid2))
    check("removed turns preserved in rolledback.jsonl", len(rb) == round_turns
          and any("the round to undo" in (t.get("text") or "") for t in rb))

    # --- 3. rollback granularity: converse removes prompt + its one answer ------
    print("3. rollback — converse removes the prompt + its single answer")
    rid3 = rooms.create_room("rb2", participants=["mock"], judge="mock")
    modes.converse(rid3, "keep me", addressed_to="mock")
    modes.converse(rid3, "undo me", addressed_to="mock")
    res3 = rooms.rollback_last_round(rid3)
    t3 = transcript.load(rooms.main_path(rid3))
    check("converse rollback removed 2 turns (human + ai)", res3["removed"] == 2)
    check("only the earlier converse remains", len(t3) == 2 and any("keep me" in t["text"] for t in t3)
          and all("undo me" not in t["text"] for t in t3))

    # --- 4. last_read_pos clamped; empty room errors ----------------------------
    print("4. rollback — last_read_pos clamped to the new length; empty room errors")
    rid4 = rooms.create_room("rb3", participants=["mock"], judge="mock")
    modes.converse(rid4, "only message", addressed_to="mock")
    rooms.update_room(rid4, last_read_pos=2)
    rooms.rollback_last_round(rid4)
    check("last_read_pos clamped to remaining length", rooms.load_room(rid4)["last_read_pos"] == 0)
    try:
        rooms.rollback_last_round(rid4); empty_ok = False
    except ValueError:
        empty_ok = True
    check("rollback on an empty room raises", empty_ok)

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 27 (round provenance + rollback) checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
