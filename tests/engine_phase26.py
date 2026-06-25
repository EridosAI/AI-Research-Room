"""engine_phase26.py — mapping, yes-and, panel context toggle, judge labels (offline).

All four are config-level adds on the Phase-25 rails (no executor surgery):
  - mapping: fusion's panel + a judge round that EXPOSES (mapping_rubric.md + a map
    instruction + neutral-self system); panel ai-raw, judge text-only, judge_kind="map";
  - yes-and: two transcript ai rounds (ordered pair) — B sees A via forward context, no
    sequential code; both forward;
  - panel context toggle: with panel_context="transcript" the panel READS forward context
    but its answers stay ai-raw (excluded from forward context);
  - judge_kind set per mode (synthesis | map | divergence).

Run:  python tests/engine_phase26.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_TMP = tempfile.mkdtemp(prefix="rr-phase26-")
_CFG = Path(_TMP) / "config.toml"
shutil.copy(REPO / "tests" / "config.toml", _CFG)
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(_CFG)
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
os.environ["RESEARCH_ROOM_SECRETS"] = str(Path(_TMP) / "secrets.json")
sys.path.insert(0, str(REPO))

from engine import modes, providers, rooms, transcript    # noqa: E402
from engine.context import build_context, forward_turns     # noqa: E402

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0


def check(label, cond):
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}")
    if not cond:
        _fails += 1


def _spy_runner():
    seen = []
    real = providers.call_model

    def spy(provider_key, payload, tools=False, effort="medium", max_tokens=None, reasoning_effort=None, **kw):
        seen.append((provider_key, payload))
        return real(provider_key, payload, tools=tools, effort=effort,
                    max_tokens=max_tokens, reasoning_effort=reasoning_effort, **kw)
    return seen, real, spy


def main() -> int:
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)

    # --- 1. mapping: panel ai-raw + a four-part MAP judge turn -------------------
    print("1. mapping — panel ai-raw + a judge map (exposes, doesn't merge)")
    rid = rooms.create_room("map", participants=["mockthink", "mock"], judge="mock")
    seen, real, spy = _spy_runner()
    providers.call_model = spy
    try:
        modes.mapping(rid, "Best caching strategy?", panel=["mockthink", "mock"], judge="mock")
    finally:
        providers.call_model = real
    turns = transcript.load(rooms.main_path(rid))
    raw = [t for t in turns if (t.get("meta") or {}).get("is_panelist_raw")]
    judge = next(t for t in turns if t["role"] == "judge")
    check("two ai-raw panel answers", len(raw) == 2)
    check("judge turn kind = 'map'", judge["meta"].get("judge_kind") == "map")
    jcall = next(pl for (k, pl) in seen if pl.get("system") == modes.MAPPING_SYSTEM)
    jc = jcall["messages"][0]["content"]
    check("mapping rubric (HOW TO JUDGE) reached the judge", "Consensus" in jc and "Divergences" in jc)
    check("map instruction present (expose, don't merge)", "do not pick a winner" in jc.lower() or "do not merge" in jc.lower())
    check("neutral-self note in the judge system", "one voice among many" in jcall["system"])
    # meta-isolation: panel reasoning never reaches the judge
    mt = next(t for t in raw if t["speaker"] == "mockthink")
    check("panel ANSWER text reached judge; REASONING did not",
          mt["text"] in jc and "[mock reasoning" not in jc)

    # --- 2. yes-and: A then B, B sees A via forward context (no sequential) ------
    print("2. yes-and — A then B; B sees A via forward context")
    rid2 = rooms.create_room("ya", participants=["mock", "mockthink"], judge="mock")
    seen2, real2, spy2 = _spy_runner()
    providers.call_model = spy2
    try:
        modes.yes_and(rid2, "Design a cache.", seats=["mock", "mockthink"])
    finally:
        providers.call_model = real2
    t2 = transcript.load(rooms.main_path(rid2))
    ai2 = [t for t in t2 if t["role"] == "ai"]
    check("two forward ai turns (A then B)", len(ai2) == 2 and ai2[0]["speaker"] == "mock" and ai2[1]["speaker"] == "mockthink")
    check("neither yes-and turn is ai-raw (both forward)", all(not (t["meta"].get("is_panelist_raw")) for t in ai2))
    # B's payload (the second mock call to 'mockthink') must contain A's answer text + the yes-and modifier
    b_calls = [pl for (k, pl) in seen2 if k == "mockthink"]
    b_content = b_calls[-1]["messages"][0]["content"]
    check("B's payload includes A's answer (forward context)", ai2[0]["text"] in b_content)
    check("B's payload carries the yes-and instruction", "yes, and" in b_content)
    check("no sequential-flow code path used (rounds are flow='parallel')",
          all(r.flow == "parallel" for r in modes.YES_AND_MODE.rounds))

    # --- 3. panel context toggle: transcript-aware panel stays ai-raw -----------
    print("3. panel context toggle — transcript panel READS context but stays ai-raw")
    rid3 = rooms.create_room("ctx", participants=["mock", "mockthink"], judge="mock")
    modes.converse(rid3, "Seed the room with a first message.", addressed_to="mock")
    seen3, real3, spy3 = _spy_runner()
    providers.call_model = spy3
    try:
        modes.research(rid3, "Now the panel task.", panel=["mock", "mockthink"], judge="mock",
                       panel_context="transcript")
    finally:
        providers.call_model = real3
    t3 = transcript.load(rooms.main_path(rid3))
    raw3 = [t for t in t3 if (t.get("meta") or {}).get("is_panelist_raw")]
    check("panel answers are still ai-raw under transcript context", len(raw3) == 2)
    check("ai-raw answers excluded from forward context", all(t not in forward_turns(t3) for t in raw3))
    # a transcript panelist's payload includes the seeded converse turn (it READ the room)
    panel_calls = [pl for (k, pl) in seen3 if k in ("mock", "mockthink") and pl.get("system")]
    panel_content = panel_calls[0]["messages"][0]["content"]
    check("transcript panel READ the room history", "Seed the room" in panel_content)
    check("transcript panel still got the panel instruction", "independent experts" in panel_content)

    # blind (default) panel does NOT see the room
    seen3b, real3b, spy3b = _spy_runner()
    providers.call_model = spy3b
    try:
        modes.research(rid3, "Blind panel task.", panel=["mock"], judge="mock")   # default blind
    finally:
        providers.call_model = real3b
    blind_content = next(pl for (k, pl) in seen3b if k == "mock" and "Blind panel task" in pl["messages"][0]["content"])["messages"][0]["content"]
    check("blind panel does NOT see the room history", "Seed the room" not in blind_content)

    # --- 4. judge_kind per mode ---------------------------------------------------
    print("4. judge_kind set per mode (synthesis | map | divergence)")
    check("fusion judge round kind = synthesis", modes.FUSION_MODE.rounds[-1].judge_kind == "synthesis")
    check("mapping judge round kind = map", modes.MAPPING_MODE.rounds[-1].judge_kind == "map")
    check("side-by-side judge round kind = divergence", modes.SIDE_BY_SIDE_MODE.rounds[-1].judge_kind == "divergence")

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 26 (mapping + yes-and + context toggle + judge labels) checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
