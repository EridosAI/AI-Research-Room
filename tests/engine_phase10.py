"""engine_phase10.py — Phase 10 Done-when gate (the margin), mock-only.

The headline property (flag 1) is ISOLATION — the exact mirror of the Phase-1
synthesis-only filter: a margin exchange must never appear in main.jsonl and
never enter main's forward context. Asserted directly, not trusted to
construction. Also covers:
  - background = synthesis-only FILTERED view of main, then windowed by LOGICAL
    turns (raw panel text never reaches the margin; a research round isn't split);
  - promote = exactly one attributed turn into main, and the asymmetry: invisible
    to main's context until promoted, then it correctly flows forward.

Run from the repo root:  python tests/engine_phase10.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_TMP = tempfile.mkdtemp(prefix="rr-phase10-")
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(REPO / "tests" / "config.toml")
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
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


def main() -> int:
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)
    rid = rooms.create_room("margin room", participants=["mock"], judge="mock")
    rooms.update_room(rid, margin_model="mock")
    main_path = rooms.main_path(rid)

    # --- seed main with a controlled research round: raw panel + judge synthesis.
    # Distinct, greppable markers so we can prove what reaches the margin vs main.
    print("0. seed main (raw panel RAWPANEL_SECRET + judge SYNTH_VISIBLE)")
    T.append(T.make_turn("research", "human", "human", "MAIN_PROMPT_Q",
                         {"round_id": "r1"}), main_path)
    T.append(T.make_turn("research", "ai", "mock", "RAWPANEL_SECRET text",
                         {"round_id": "r1", "is_panelist_raw": True, "model": "mock-1"}), main_path)
    T.append(T.make_turn("research", "judge", "mock", "SYNTH_VISIBLE synthesis",
                         {"round_id": "r1", "model": "mock-1"}), main_path)
    main_before = T.load(main_path)

    # --- background filtering + windowing -----------------------------------
    print("1. background = synthesis-only filtered, windowed by logical turns")
    bg_full = margin.windowed_background(main_before, "full")
    check("background includes the judge synthesis", "SYNTH_VISIBLE" in bg_full)
    check("background EXCLUDES raw panel text (Phase-1 filter reused)",
          "RAWPANEL_SECRET" not in bg_full)
    # window by logical turns: last_1 keeps the single most recent forward turn
    # (the synthesis), NOT a raw JSONL line, and not the human prompt before it.
    bg_last1 = margin.windowed_background(main_before, "last_1")
    check("last_1 window keeps the latest forward turn (synthesis)", "SYNTH_VISIBLE" in bg_last1)
    check("last_1 window drops the earlier human prompt", "MAIN_PROMPT_Q" not in bg_last1)
    check("last_1 never exposes raw panel text", "RAWPANEL_SECRET" not in bg_last1)

    # --- ask the margin → isolation gate ------------------------------------
    print("2. ISOLATION — margin exchange never touches main")
    answer = margin.margin_turn(rid, "MARGIN_Q_MARKER explain that", window="last_1", model="mock")
    margin_turns = T.load(rooms.margin_path(rid))
    main_after = T.load(main_path)
    check("margin Q+A stored in margin.jsonl", len(margin_turns) == 2)
    check("main.jsonl unchanged by the margin exchange", main_after == main_before)
    check("no margin-mode turn ever entered main",
          all(t.get("mode") != "margin" for t in main_after))
    ctx = build_context(main_after, "mock", "converse")["messages"][0]["content"]
    check("main's build_context contains ZERO margin question text", "MARGIN_Q_MARKER" not in ctx)
    check("main's build_context contains ZERO margin answer text", answer not in ctx)

    # --- promote: exactly one attributed turn, then it flows forward ---------
    print("3. promote — one attributed turn; invisible→forward asymmetry")
    ans_turn = next(t for t in margin_turns if t["role"] == "ai")
    ctx_before = build_context(T.load(main_path), "mock", "converse")["messages"][0]["content"]
    check("answer NOT in main context before promote", ans_turn["text"] not in ctx_before)

    n_before = len(T.load(main_path))
    note = margin.promote(rid, ans_turn["id"])
    main_promoted = T.load(main_path)
    check("promote appended EXACTLY one turn to main", len(main_promoted) == n_before + 1)
    check("promoted turn is attributed to the margin", note["role"] == "note"
          and (note.get("meta") or {}).get("from_margin") is True)
    ctx_after = build_context(main_promoted, "mock", "converse")["messages"][0]["content"]
    check("promoted answer NOW flows into main's forward context", ans_turn["text"] in ctx_after)

    # margin.jsonl itself is untouched by promotion (copy, not move)
    check("margin.jsonl unchanged by promote", len(T.load(rooms.margin_path(rid))) == 2)

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m")
        return 1
    print("\033[32mall Phase 10 Done-when checks passed\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
