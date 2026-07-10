"""engine_phase37.py — margin window anchoring (offline, mock).

Phase 37's one engine edit: a margin question turn records `window_ids`, the exact
forward main turns its window resolved to. The point is the SNAPSHOT — the ids must
come from the same read that produced the background text, never from a later
re-read. The margin runs under its own lock (it is *designed* to race a main round)
and `ts` is second-granular with no tiebreaker, so a re-read (or any ts-correlation)
can silently attribute a turn the margin never saw.

  - window_ids == the ids of exactly the turns whose text reached the background,
    for last_1 / last_3 / full;
  - raw panelist ids never appear (the synthesis-only filter is reused, not re-implemented);
  - empty main → [];
  - REGRESSION: a concurrent main append landing between the snapshot and the stamp
    is excluded from window_ids — even though its ts satisfies `ts <= question.ts`,
    which is precisely what a ts-correlation would have got wrong;
  - main.jsonl is read exactly ONCE per margin_turn (proves "no re-read").

Run:  python tests/engine_phase37.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_TMP = tempfile.mkdtemp(prefix="rr-phase37-")
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(REPO / "tests" / "config.toml")
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
os.environ["RESEARCH_ROOM_SECRETS"] = str(Path(_TMP) / "secrets.json")
sys.path.insert(0, str(REPO))

from engine import margin, rooms          # noqa: E402
from engine import transcript as T        # noqa: E402
from engine.context import build_context  # noqa: E402

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0


def check(label: str, cond: bool) -> None:
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}")
    if not cond:
        _fails += 1


def _seed(rid: str) -> list[dict]:
    """A room whose forward view is [H1, S1, H2, A2] and whose raw panel is excluded."""
    p = rooms.main_path(rid)
    T.append(T.make_turn("converse", "human", "human", "H1_MARK first ask", {}), p)
    T.append(T.make_turn("research", "ai", "mock", "RAW_MARK panel answer",
                         {"round_id": "r1", "is_panelist_raw": True}), p)
    T.append(T.make_turn("research", "judge", "mock", "S1_MARK synthesis", {"round_id": "r1"}), p)
    T.append(T.make_turn("converse", "human", "human", "H2_MARK second ask", {}), p)
    T.append(T.make_turn("converse", "ai", "mock", "A2_MARK reply", {}), p)
    return T.load(p)


def _question(rid: str, n: int = -1) -> dict:
    """The n-th margin QUESTION turn (role human)."""
    qs = [t for t in T.load(rooms.margin_path(rid)) if t["role"] == "human"]
    return qs[n]


def main() -> int:
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)
    rid = rooms.create_room("phase37", participants=["mock"], judge="mock")
    rooms.update_room(rid, margin_model="mock")
    main_turns = _seed(rid)
    by_id = {t["id"]: t for t in main_turns}
    raw_ids = {t["id"] for t in main_turns if (t.get("meta") or {}).get("is_panelist_raw")}

    # --- 1. window_ids == exactly the turns whose text reached the background ----
    print("1. window_ids mirror the background, for every window option")
    for window, expect_marks in (("last_1", ["A2_MARK"]),
                                 ("last_3", ["S1_MARK", "H2_MARK", "A2_MARK"]),
                                 ("full", ["H1_MARK", "S1_MARK", "H2_MARK", "A2_MARK"])):
        margin.margin_turn(rid, f"ask about {window}", window=window, model="mock")
        q = _question(rid)
        ids = q["meta"]["window_ids"]
        bg = margin.windowed_background(main_turns, window)

        got_marks = [by_id[i]["text"].split()[0] for i in ids]
        check(f"{window}: window_ids resolve to exactly {expect_marks}", got_marks == expect_marks)
        check(f"{window}: every windowed id's text is in the background",
              all(by_id[i]["text"] in bg for i in ids))
        # nothing outside the window leaked into the background it was formatted from
        outside = [t for t in main_turns if t["id"] not in ids]
        check(f"{window}: no turn outside window_ids appears in the background",
              all(t["text"] not in bg for t in outside))
        check(f"{window}: raw panelist id never appears", not (set(ids) & raw_ids))
        check(f"{window}: policy string retained for back-compat", q["meta"]["window"] == window)

    # --- 2. empty main → [] ------------------------------------------------------
    print("2. an empty main yields an empty window")
    rid2 = rooms.create_room("phase37-empty", participants=["mock"], judge="mock")
    rooms.update_room(rid2, margin_model="mock")
    margin.margin_turn(rid2, "nothing to see", window="last_3", model="mock")
    check("window_ids == [] on an empty transcript", _question(rid2)["meta"]["window_ids"] == [])
    check("windowed_forward([]) == []", margin.windowed_forward([], "full") == [])

    # --- 3. THE REGRESSION: a concurrent append after the snapshot is excluded ----
    # margin_turn reads main once, then stamps. Simulate a main round appending a
    # forward turn in that gap (its own lock does not exclude the margin, by design).
    # Its ts lands in the same second as the question's, so a ts-correlation would
    # wrongly include it. window_ids must not.
    print("3. a main turn appended after the snapshot is NOT in window_ids (the ts race)")
    rid3 = rooms.create_room("phase37-race", participants=["mock"], judge="mock")
    rooms.update_room(rid3, margin_model="mock")
    seeded = _seed(rid3)
    mpath3 = rooms.main_path(rid3)

    real_load = T.load
    calls = {"main": 0}
    intruder: dict = {}

    def racing_load(path):
        out = real_load(path)
        if Path(path) == Path(mpath3):
            calls["main"] += 1
            if calls["main"] == 1:            # right after the snapshot the margin sees
                t = T.make_turn("converse", "human", "human", "INTRUDER_MARK", {})
                T.append(t, mpath3)
                intruder.update(t)
        return out

    margin.transcript.load = racing_load     # patch the module the margin calls through
    try:
        margin.margin_turn(rid3, "ask while a round lands", window="last_1", model="mock")
    finally:
        margin.transcript.load = real_load

    q3 = _question(rid3)
    ids3 = q3["meta"]["window_ids"]
    check("main.jsonl was read exactly once (no re-read to recover ids)", calls["main"] == 1)
    check("the intruder turn really did land in main",
          intruder["id"] in {t["id"] for t in T.load(mpath3)})
    check("window_ids EXCLUDES the concurrently-appended turn",
          intruder["id"] not in ids3)
    check("window_ids is the pre-race last forward turn (A2_MARK)",
          ids3 == [seeded[-1]["id"]])
    # the exact trap this replaces: the intruder's ts is <= the question's ts, so the
    # old "last forward turn with ts <= question.ts" rule would have picked it.
    check("a ts-correlation WOULD have wrongly included it (the race is real)",
          intruder["ts"] <= q3["ts"])

    # --- 4. isolation still holds — the new meta never reaches forward context ----
    print("4. isolation: window_ids is display-only")
    main_after = T.load(rooms.main_path(rid))
    check("margin turns never entered main", len(main_after) == len(main_turns))
    ctx = build_context(main_after, "mock", "converse")
    blob = ctx["system"] + ctx["messages"][0]["content"]
    check("no window_ids in build_context", "window_ids" not in blob)
    check("no margin question text in build_context", "ask about last_1" not in blob)
    check("raw panel text still filtered from forward context", "RAW_MARK" not in blob)

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 37.1 (margin window anchoring) checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
