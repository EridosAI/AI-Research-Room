"""engine_phase28.py — reasoning-token capture + requested-thinking-level stamp (offline).

Prompted by the RR Loom 4 bug: Claude answered fast/shallow because its reasoning toggle
was OFF, so no effort was ever sent — and nothing in the transcript recorded that.
  - openai_style captures completion_tokens_details.reasoning_tokens → usage.reasoning
    (the ACTUAL think, vs the requested level);
  - run_mode stamps meta.reasoning_effort on every output turn: 'off' when the provider's
    reasoning toggle is off (effort dial inert), the override when set, else 'default';
  - both ride meta — never serialized into forward context.

Run:  python tests/engine_phase28.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_TMP = tempfile.mkdtemp(prefix="rr-phase28-")
_CFG = Path(_TMP) / "config.toml"
shutil.copy(REPO / "tests" / "config.toml", _CFG)
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(_CFG)
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
os.environ["RESEARCH_ROOM_SECRETS"] = str(Path(_TMP) / "secrets.json")
sys.path.insert(0, str(REPO))

import httpx as _httpx                                     # noqa: E402
from engine import modes, providers, rooms, transcript     # noqa: E402
from engine.adapters import openai_style                    # noqa: E402
from engine.context import build_context                    # noqa: E402

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0


def check(label, cond):
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}")
    if not cond:
        _fails += 1


class _Resp:
    def __init__(self, d): self._d = d
    def raise_for_status(self): pass
    def json(self): return self._d


class _Rec:
    HTTPStatusError = _httpx.HTTPStatusError
    HTTPError = _httpx.HTTPError

    def __init__(self, resp): self.resp = resp; self.sent = None
    def post(self, url, headers=None, json=None, timeout=None): self.sent = json; return self.resp


def main() -> int:
    P = providers.Provider
    payload = {"system": "", "messages": [{"role": "user", "content": "q"}]}
    orp = P("or", "api", "openai", "anthropic/claude-opus-4.8", True, "#fff",
            base_url="https://openrouter.ai/api/v1", reasoning=True)

    # --- 1. reasoning_tokens captured into usage --------------------------------
    print("1. reasoning-token capture — usage.reasoning = completion_tokens_details.reasoning_tokens")
    resp = {"model": "anthropic/claude-opus-4.8", "choices": [{"finish_reason": "stop",
            "message": {"content": "A"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 800, "cost": 0.02,
                      "completion_tokens_details": {"reasoning_tokens": 640}}}
    rec = _Rec(_Resp(resp)); openai_style.httpx = rec
    _t, _r, usage, _s, _se, _f = openai_style.chat(orp, "k", payload, reasoning=True, reasoning_effort="high")
    openai_style.httpx = _httpx
    check("usage.reasoning captured (640)", usage.get("reasoning") == 640)
    check("input/output/cost still parse", usage.get("input") == 10 and usage.get("output") == 800 and usage.get("cost") == 0.02)

    print("   a no-reasoning response → no usage.reasoning key (the RR Loom 4 shape)")
    rec = _Rec(_Resp({"model": "x", "choices": [{"message": {"content": "B"}}],
                      "usage": {"prompt_tokens": 5, "completion_tokens": 50}}))
    openai_style.httpx = rec
    _, _, u2, _, _, _ = openai_style.chat(orp, "k", payload, reasoning=True)
    openai_style.httpx = _httpx
    check("absent reasoning_tokens → no 'reasoning' key", "reasoning" not in u2)

    # --- 2. requested thinking level stamped per turn ---------------------------
    print("2. requested thinking level stamped on output turns (meta.reasoning_effort)")
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)

    # mockthink has reasoning=True; with a per-room override the turn records that effort
    rid = rooms.create_room("eff", participants=["mockthink"], judge="mockthink")
    rooms.update_room(rid, reasoning_effort={"mockthink": "xhigh"})
    modes.converse(rid, "hello?", addressed_to="mockthink")
    ai = next(t for t in transcript.load(rooms.main_path(rid)) if t["role"] == "ai")
    check("reasoning-on seat with override → records the effort ('xhigh')",
          ai["meta"].get("reasoning_effort") == "xhigh")

    # reasoning on, no override → 'default'
    rid_d = rooms.create_room("effd", participants=["mockthink"], judge="mockthink")
    modes.converse(rid_d, "hello?", addressed_to="mockthink")
    aid = next(t for t in transcript.load(rooms.main_path(rid_d)) if t["role"] == "ai")
    check("reasoning-on seat, no override → 'default'", aid["meta"].get("reasoning_effort") == "default")

    # reasoning OFF (plain `mock`) → 'off' — the dial would be inert (the bug, now visible)
    rid_off = rooms.create_room("effoff", participants=["mock"], judge="mock")
    rooms.update_room(rid_off, reasoning_effort={"mock": "xhigh"})   # set, but inert
    modes.converse(rid_off, "hello?", addressed_to="mock")
    aoff = next(t for t in transcript.load(rooms.main_path(rid_off)) if t["role"] == "ai")
    check("reasoning-OFF seat → 'off' even with an effort set (inert dial recorded)",
          aoff["meta"].get("reasoning_effort") == "off")

    # judge turn is stamped too
    rid_j = rooms.create_room("effj", participants=["mockthink", "mock"], judge="mockthink")
    rooms.update_room(rid_j, reasoning_effort={"mockthink": "high"})
    modes.research(rid_j, "task?", panel=["mockthink", "mock"], judge="mockthink")
    judge = next(t for t in transcript.load(rooms.main_path(rid_j)) if t["role"] == "judge")
    check("judge turn records its requested effort ('high')", judge["meta"].get("reasoning_effort") == "high")

    # --- 3. neither leaks into forward context ----------------------------------
    print("3. isolation — reasoning_effort + reasoning tokens stay in meta")
    turns = transcript.load(rooms.main_path(rid_j))
    body = build_context(turns, "mockthink", "converse", participants=["mockthink", "mock"])["messages"][0]["content"]
    check("reasoning_effort not in build_context body", "reasoning_effort" not in body)

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 28 (reasoning-token capture + thinking-level stamp) checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
