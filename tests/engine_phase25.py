"""engine_phase25.py — the round/mode framework + side-by-side (offline, mock).

run_mode is the single executor under every interaction pattern. This covers the NEW
surface (the wrappers' faithfulness is the unchanged engine_phase* suite):
  - side-by-side: two ai-raw answers + a judge DIVERGENCE-note turn (not synthesis);
  - ai-raw answers are excluded from build_context (forward context);
  - the judge sees prior answers' TEXT only — never their reasoning/served_model;
  - degradation (failed seat → absent, abort if all fail) + judge→panelist fallback
    hold through run_mode.

Run:  python tests/engine_phase25.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_TMP = tempfile.mkdtemp(prefix="rr-phase25-")
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


def main() -> int:
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)

    # --- 1. side-by-side: two ai-raw answers + a divergence-note judge turn -------
    print("1. side-by-side — two ai-raw answers + a judge divergence note")
    rid = rooms.create_room("sxs", participants=["mockthink", "mock"], judge="mock")
    seen = []
    real = providers.call_model

    def spy(provider_key, payload, tools=False, effort="medium", max_tokens=None, reasoning_effort=None):
        seen.append((provider_key, payload))
        return real(provider_key, payload, tools=tools, effort=effort,
                    max_tokens=max_tokens, reasoning_effort=reasoning_effort)

    providers.call_model = spy
    try:
        modes.side_by_side(rid, "Is P=NP?", seats=["mockthink", "mock"], judge="mock")
    finally:
        providers.call_model = real

    turns = transcript.load(rooms.main_path(rid))
    raw = [t for t in turns if (t.get("meta") or {}).get("is_panelist_raw")]
    judges = [t for t in turns if t["role"] == "judge"]
    check("two ai-raw panel answers posted", len(raw) == 2)
    check("both panel turns are role 'ai' (raw via meta)", all(t["role"] == "ai" for t in raw))
    check("exactly one judge turn", len(judges) == 1)
    check("panel + judge share one round_id (grouped)",
          len({t["meta"]["round_id"] for t in raw + judges}) == 1)

    # the judge call used the side-by-side system + the divergence instruction
    judge_calls = [pl for (k, pl) in seen if pl.get("system") == modes.SIDE_SYSTEM]
    check("judge ran with the side-by-side system (not synthesis)", len(judge_calls) == 1)
    jcontent = judge_calls[0]["messages"][0]["content"]
    check("judge instruction is the divergence note", "where they differ" in jcontent)
    check("judge instruction says not to merge / pick", "do not pick a winner" in jcontent.lower()
          or "Do not merge" in jcontent)

    # --- 2. ai-raw excluded from forward context ----------------------------------
    print("2. ai-raw excluded from forward context (build_context)")
    raw_text = raw[0]["text"]
    check("raw answers NOT in forward_turns", all(t not in forward_turns(turns) for t in raw))
    body = build_context(turns, "mock", "converse", participants=["mockthink", "mock"])["messages"][0]["content"]
    check("a raw panel answer is absent from build_context", raw_text not in body)
    check("the judge turn IS forward (in build_context)", judges[0]["text"][:30] in body)

    # --- 3. judge saw TEXT only — never the panel's reasoning ----------------------
    print("3. meta-isolation — judge prompt carries panel TEXT, not reasoning")
    # mockthink emits reasoning "[mock reasoning · mockthink] …" on its turn meta
    mt = next(t for t in raw if t["speaker"] == "mockthink")
    check("mockthink's raw turn carries reasoning in meta", bool(mt["meta"].get("reasoning")))
    check("panel ANSWER text reached the judge prompt", mt["text"] in jcontent)
    check("panel REASONING did NOT reach the judge prompt", "[mock reasoning" not in jcontent)

    # --- 4. degradation: a failed seat → absent; judge still runs ------------------
    print("4. degradation — failed panelist becomes absent (not agreement)")
    rid2 = rooms.create_room("degrade", participants=["mock", "mockfail"], judge="mock")
    modes.research(rid2, "task?", panel=["mock", "mockfail"], judge="mock")
    t2 = transcript.load(rooms.main_path(rid2))
    raw2 = [t for t in t2 if (t.get("meta") or {}).get("is_panelist_raw")]
    judge2 = next(t for t in t2 if t["role"] == "judge")
    check("only the surviving panelist posted a raw answer", len(raw2) == 1 and raw2[0]["speaker"] == "mock")
    check("judge turn still produced", judge2["role"] == "judge")

    # --- 5. judge→panelist fallback through run_mode ------------------------------
    print("5. judge fallback — unavailable judge falls back to a seat that answered")
    rid3 = rooms.create_room("fallback", participants=["mock"], judge="mockfail")
    modes.research(rid3, "task?", panel=["mock"], judge="mockfail")
    j3 = next(t for t in transcript.load(rooms.main_path(rid3)) if t["role"] == "judge")
    check("judge fell back from the unavailable judge", j3["meta"].get("judge_fallback_from") == "mockfail")
    check("fallback judge is the seat that answered (mock)", j3["speaker"] == "mock")

    # --- 6. converse runs through the SAME executor (single-seat ai, forward) ------
    print("6. converse via run_mode — single seat, forward ai turn")
    rid4 = rooms.create_room("conv", participants=["mock"], judge="mock")
    modes.converse(rid4, "hello?", addressed_to="mock")
    t4 = transcript.load(rooms.main_path(rid4))
    ai4 = [t for t in t4 if t["role"] == "ai"]
    check("converse posts one ai turn (mode=converse, not raw)",
          len(ai4) == 1 and ai4[0]["mode"] == "converse" and not (ai4[0]["meta"].get("is_panelist_raw")))

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 25 (round/mode framework + side-by-side) checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
