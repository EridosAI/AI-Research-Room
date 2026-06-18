"""engine_phase8.py — Phase 8 Done-when gate (rooms as folders), mock-only.

Verifies, at zero token cost:
  1. migration wraps legacy flat transcripts into room folders with no data loss,
     idempotently, seeding enabled providers + research_judge;
  2. a research round in room A writes ONLY to A's main.jsonl using A's roster —
     room B is untouched;
  3. build_context for a room reads THAT room's transcript;
  4. converse appends to the addressed room only;
  5. the CLI drives a round against an explicit (active) room.

Run from the repo root:  python tests/engine_phase8.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Point the engine at a throwaway vault + the test fixture registry BEFORE import
# (settings reads env at import time). Secrets go to a temp dir too — never touched.
_TMP = tempfile.mkdtemp(prefix="rr-phase8-")
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(REPO / "tests" / "config.toml")
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
sys.path.insert(0, str(REPO))

from engine import modes, providers, rooms, settings   # noqa: E402
from engine import transcript as T                       # noqa: E402
from engine.context import build_context                 # noqa: E402

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0


def check(label: str, cond: bool) -> None:
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}")
    if not cond:
        _fails += 1


def main() -> int:
    settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)

    # --- 1. migration -------------------------------------------------------
    print("1. migration of legacy flat transcripts")
    legacy = settings.VAULT_DIR / "20200101-000000-legacy-thread.jsonl"
    turns = [
        T.make_turn("converse", "human", "human", "old question"),
        T.make_turn("converse", "ai", "mock", "old answer", {"model": "mock-1"}),
    ]
    legacy.write_text("".join(__import__("json").dumps(t) + "\n" for t in turns),
                      encoding="utf-8")
    migrated = rooms.migrate_flat_transcripts()
    check("flat file wrapped into exactly one room", migrated == ["20200101-000000-legacy-thread"])
    mid = migrated[0]
    check("folder main.jsonl exists", rooms.main_path(mid).is_file())
    check("flat file removed (moved, not copied)", not legacy.exists())
    moved = T.load(rooms.main_path(mid))
    check("no data loss (turns + text preserved)",
          [t["text"] for t in moved] == ["old question", "old answer"])
    meta = rooms.load_room(mid)
    check("migrated room seeded with enabled providers",
          meta["participants"] == providers.enabled())
    check("migrated room seeded with research_judge", meta["judge"] == providers.research_judge())
    check("migration is idempotent (2nd call is a no-op)", rooms.migrate_flat_transcripts() == [])

    # --- 2. two rooms; research isolation -----------------------------------
    print("2. research round isolation across rooms")
    a = rooms.create_room("room A", participants=["mock", "mock_cli"], judge="mock")
    b = rooms.create_room("room B", participants=["mock"], judge="mock")
    check("two distinct room ids", a != b and rooms.room_exists(a) and rooms.room_exists(b))

    modes.research(a, "what is the capital of France?", effort="low")
    a_turns, b_turns = T.load(rooms.main_path(a)), T.load(rooms.main_path(b))
    check("room B completely untouched", b_turns == [])
    speakers = {t["speaker"] for t in a_turns}
    check("A used only its own roster (+human)", speakers <= {"human", "mock", "mock_cli"})
    check("A has a human turn", any(t["role"] == "human" for t in a_turns))
    check("A has >=1 raw panelist turn",
          any((t.get("meta") or {}).get("is_panelist_raw") for t in a_turns))
    check("A has exactly one judge synthesis", sum(t["role"] == "judge" for t in a_turns) == 1)

    # --- 3. build_context reads the room's own file -------------------------
    print("3. build_context reads the specified room's transcript")
    ctx = build_context(T.load(rooms.main_path(a)), "mock", "converse",
                        participants=meta["participants"])
    body = ctx["messages"][0]["content"]
    check("context built from A includes A's prompt", "capital of France" in body)
    raw = [t for t in a_turns if (t.get("meta") or {}).get("is_panelist_raw")]
    check("synthesis-only filter holds (raw panel text excluded)",
          all(t["text"] not in body for t in raw) if raw else True)
    ctx_b = build_context(T.load(rooms.main_path(b)), "mock", "converse")
    check("context built from B is empty of A's prompt",
          "capital of France" not in ctx_b["messages"][0]["content"])

    # --- 4. converse appends to the addressed room only ---------------------
    print("4. converse writes to one room only")
    before_b = len(T.load(rooms.main_path(b)))
    modes.converse(a, "and its population?", addressed_to="mock")
    check("converse appended to A", len(T.load(rooms.main_path(a))) > len(a_turns))
    check("converse left B untouched", len(T.load(rooms.main_path(b))) == before_b)

    # --- 5. CLI drives a round against an explicit (active) room -------------
    print("5. CLI drives a round against an explicit room")
    from cli import room as cli   # noqa: E402
    rc_new = cli.main(["new", "cli smoke room"])
    rc_ask = cli.main(["ask", "name one ocean", "--effort", "low"])
    active = settings.CURRENT_PTR.read_text().strip()
    cli_turns = T.load(rooms.main_path(active))
    check("CLI new+ask returned success", rc_new == 0 and rc_ask == 0)
    check("CLI round landed in the active room", any(t["role"] == "judge" for t in cli_turns))
    check("CLI room is distinct from A and B", active not in (a, b))

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m")
        return 1
    print("\033[32mall Phase 8 Done-when checks passed\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
