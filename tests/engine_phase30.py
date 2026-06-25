"""engine_phase30.py — absent-panelist reasons stamped on the round (offline).

When a panelist fails it's dropped as absent (never silent agreement). Before, the reason
only reached the judge prompt and was lost; now run_mode stamps meta.absent =
[{speaker, error}] on the judge turn, so "why did X drop?" is answerable. Like all meta,
it never enters forward context.

Run:  python tests/engine_phase30.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_TMP = tempfile.mkdtemp(prefix="rr-phase30-")
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


def main() -> int:
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)

    # --- 1. a failed panelist → judge turn records it + WHY ----------------------
    print("1. absent reasons — a dropped panelist is recorded on the judge turn (with the error)")
    rid = rooms.create_room("a", participants=["mock", "mockfail"], judge="mock")
    modes.research(rid, "task?", panel=["mock", "mockfail"], judge="mock")
    turns = transcript.load(rooms.main_path(rid))
    judge = next(t for t in turns if t["role"] == "judge")
    absent = (judge.get("meta") or {}).get("absent")
    check("judge turn carries meta.absent (a list)", isinstance(absent, list) and len(absent) == 1)
    check("absent entry names the dropped seat (mockfail)", absent[0]["speaker"] == "mockfail")
    check("absent entry carries a non-empty error reason", bool(absent[0].get("error")))
    survivors = {t["speaker"] for t in turns if (t.get("meta") or {}).get("is_panelist_raw")}
    check("the seat that ANSWERED (mock) is not listed absent",
          "mock" in survivors and absent[0]["speaker"] not in survivors)

    # --- 2. no failures → no absent key -----------------------------------------
    print("2. clean round — no failures → no meta.absent")
    rid2 = rooms.create_room("b", participants=["mock"], judge="mock")
    modes.research(rid2, "task?", panel=["mock"], judge="mock")
    judge2 = next(t for t in transcript.load(rooms.main_path(rid2)) if t["role"] == "judge")
    check("clean round omits meta.absent", "absent" not in (judge2.get("meta") or {}))

    # --- 3. isolation — the absence reason never enters forward context ----------
    print("3. isolation — meta.absent stays in meta")
    body = build_context(turns, "mock", "converse", participants=["mock", "mockfail"])["messages"][0]["content"]
    check("the absent error reason is NOT in build_context", absent[0]["error"] not in body)

    # --- 4. side-by-side also records absences ----------------------------------
    print("4. side-by-side — a dropped seat is recorded too")
    rid3 = rooms.create_room("c", participants=["mock", "mockfail"], judge="mock")
    modes.side_by_side(rid3, "compare", seats=["mock", "mockfail"], judge="mock")
    j3 = next(t for t in transcript.load(rooms.main_path(rid3)) if t["role"] == "judge")
    a3 = (j3.get("meta") or {}).get("absent") or []
    check("side-by-side judge records the dropped seat", any(x["speaker"] == "mockfail" for x in a3))

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 30 (absent-panelist reasons) checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
