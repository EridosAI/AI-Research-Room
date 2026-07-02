"""engine_phase32.py — per-room artifacts (offline).

  32.1 resolution: per-room artifacts_dir with global fallback (room wins → global → None);
       the key is a default-meta field + mutable + survives a round-trip.
  32.2 guard: the artifacts-awareness line is folded into EVERY seat's system prompt when a
       dir resolves (blind panel + transcript panel + judge + converse), absent when none;
       the margin is unaffected (its own _system, read-only by design). Applied in call_model
       like _guard_no_search, so it reaches the seats room_system() misses.
  32.3 stamp: forward turns (converse/yes-and reply + judge synthesis) auto-write their
       ```markdown blocks BEFORE append and carry meta.artifact_paths; raw panels don't;
       a failure stamps nothing; the field NEVER enters build_context (byte-identical).

Run:  python tests/engine_phase32.py
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_TMP = tempfile.mkdtemp(prefix="rr-phase32-")
_CFG = Path(_TMP) / "config.toml"
shutil.copy(REPO / "tests" / "config.toml", _CFG)
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(_CFG)
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
os.environ["RESEARCH_ROOM_SECRETS"] = str(Path(_TMP) / "secrets.json")
os.environ["RESEARCH_ROOM_UI"] = str(Path(_TMP) / "ui.json")
sys.path.insert(0, str(REPO))

from engine import artifacts, modes, providers, rooms, transcript   # noqa: E402
from engine.context import build_context                            # noqa: E402
from engine import margin as margin_mod                             # noqa: E402

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0
_MARK = "is automatically saved as a .md file to:"   # stable substring of the guard line


def check(label, cond):
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}")
    if not cond:
        _fails += 1


# capture the POST-guard system every mock seat sees (call_model applies the guards before
# _mock_text), so we can assert the artifacts line reaches each seat type offline.
_seen: list[str] = []
_REAL_MT = providers._mock_text


def _cap(p, payload):
    _seen.append(payload.get("system", ""))
    return _REAL_MT(p, payload)


def _fence(key):
    return f"answer from {key}\n\n```markdown\n# Spec {key}\nbody\n```\n"


def main() -> int:
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)
    ui = Path(os.environ["RESEARCH_ROOM_UI"])

    # ---- 32.1 resolution matrix -------------------------------------------------
    print("32.1 resolution — per-room artifacts_dir with global fallback")
    rid = rooms.create_room("a", participants=["mock", "mockthink"], judge="mock")
    check("default meta carries artifacts_dir=''", rooms.load_room(rid).get("artifacts_dir") == "")
    check("neither room nor global set → None", artifacts.resolve_artifacts_dir(rid) is None)
    ui.write_text(json.dumps({"artifacts_dir": "/global/dir"}))
    check("global only → global", artifacts.resolve_artifacts_dir(rid) == "/global/dir")
    rooms.update_room(rid, artifacts_dir="/room/dir")
    check("room override wins over global", artifacts.resolve_artifacts_dir(rid) == "/room/dir")
    check("artifacts_dir round-trips through room.json", rooms.load_room(rid).get("artifacts_dir") == "/room/dir")
    rooms.update_room(rid, artifacts_dir="")
    check("room blank → back to global (inherit)", artifacts.resolve_artifacts_dir(rid) == "/global/dir")
    ui.write_text(json.dumps({}))   # clear global for the rest

    # ---- 32.2 guard: unit + across seat types -----------------------------------
    print("32.2 guard — the awareness line reaches every seat when a dir resolves")
    g = providers._guard_artifacts({"system": "BASE", "messages": []}, "/a/b")
    check("appended to an existing system prompt", "/a/b" in g["system"] and g["system"].startswith("BASE"))
    g2 = providers._guard_artifacts({"system": "", "messages": []}, "/a/b")
    check("becomes the system prompt when none set (blind rounds)", g2["system"].startswith("Artifacts:"))
    check("no dir → payload unchanged", providers._guard_artifacts({"system": "BASE", "messages": []}, None)["system"] == "BASE")

    art = str(Path(_TMP) / "arts")
    rid2 = rooms.create_room("b", participants=["mock", "mockthink"], judge="mock")
    rooms.update_room(rid2, artifacts_dir=art)
    providers._mock_text = _cap
    try:
        _seen.clear()
        modes.research(rid2, "task?", panel=["mock", "mockthink"], judge="mock")   # blind panel + judge
        blind = list(_seen)
        check("blind research: 2 panel + judge systems captured", len(blind) >= 3)
        check("blind panel + judge ALL carry the artifacts line", all(_MARK in s for s in blind))

        _seen.clear()
        modes.converse(rid2, "hi?", addressed_to="mock")                            # converse speaker
        check("converse speaker carries the line (on top of room_system)",
              _seen and all(_MARK in s for s in _seen) and any("You are [" in s for s in _seen))

        _seen.clear()
        modes.research(rid2, "task2?", panel=["mock"], judge="mock", panel_context="transcript")
        check("transcript panel + judge carry the line (with room_system present)",
              all(_MARK in s for s in _seen) and any("You are [" in s for s in _seen))

        # margin is unaffected — its own _system, no artifacts_dir threaded
        _seen.clear()
        margin_mod.margin_turn(rid2, "side question?", model="mock")
        check("margin seat does NOT get the artifacts line", _seen and not any(_MARK in s for s in _seen))

        # no dir resolves → no line anywhere
        rid3 = rooms.create_room("c", participants=["mock"], judge="mock")
        _seen.clear()
        modes.research(rid3, "task?", panel=["mock"], judge="mock")
        check("no dir resolved → line absent for every seat", _seen and not any(_MARK in s for s in _seen))
    finally:
        providers._mock_text = _REAL_MT

    # ---- 32.3 stamp: forward turns carry meta.artifact_paths ---------------------
    print("32.3 stamp — forward turns auto-write + carry meta.artifact_paths; raw panels don't")
    providers._mock_text = lambda p, payload: _fence(p.key)   # every reply emits a fenced block
    try:
        rid4 = rooms.create_room("d", participants=["mock", "mockthink"], judge="mock")
        rooms.update_room(rid4, artifacts_dir=art)
        modes.research(rid4, "make a spec", panel=["mock", "mockthink"], judge="mock")
        modes.converse(rid4, "and a doc?", addressed_to="mock")
    finally:
        providers._mock_text = _REAL_MT
    turns = transcript.load(rooms.main_path(rid4))
    judge = next(t for t in turns if t["role"] == "judge")
    panels = [t for t in turns if (t.get("meta") or {}).get("is_panelist_raw")]
    conv = [t for t in turns if t["role"] == "ai" and not (t.get("meta") or {}).get("is_panelist_raw")][-1]
    check("judge synthesis carries meta.artifact_paths", bool(judge["meta"].get("artifact_paths")))
    check("converse reply carries meta.artifact_paths", bool(conv["meta"].get("artifact_paths")))
    check("raw panels do NOT auto-save (no artifact_paths)",
          panels and all("artifact_paths" not in (p.get("meta") or {}) for p in panels))
    files = sorted(Path(art).glob(f"*{rid4}*.md"))
    check("the artifact files were actually written", len(files) >= 2)

    # failure / no-dir stamps nothing, never raises
    m: dict = {}
    modes._stamp_artifacts(m, rid4, "x", None)
    check("no dir → stamp is a no-op (never raises)", m == {})

    # ---- meta.artifact_paths NEVER enters forward context -----------------------
    print("meta isolation — artifact_paths stays in meta (build_context byte-identical)")
    body = build_context(turns, "mock", "converse", participants=["mock", "mockthink"])["messages"][0]["content"]
    check("no saved path leaks into build_context", judge["meta"]["artifact_paths"][0] not in body)
    check("the field name never appears in forward context", "artifact_paths" not in body)
    stripped = copy.deepcopy(turns)
    for t in stripped:
        (t.get("meta") or {}).pop("artifact_paths", None)
    b_stamped = build_context(turns, "mock", "converse", participants=["mock", "mockthink"])
    b_plain = build_context(stripped, "mock", "converse", participants=["mock", "mockthink"])
    check("build_context is byte-identical with/without the stamp", b_stamped == b_plain)

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 32 (per-room artifacts) checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
