"""engine_phase11.py — Phase 11 Done-when gate (visible reasoning), mock-only.

Reasoning is a field on the answer turn (`meta.reasoning`), never a separate turn
and never in `text`. The headline is the ISOLATION gate — the mirror of the
synthesis-only filter: a turn carrying reasoning must NOT leak that reasoning into
any model's forward context. Asserted directly. Also covers:
  - capture is opt-in: a reasoning-on provider's turns carry meta.reasoning; off → absent;
  - the per-provider toggle persists in the registry;
  - the adapter capture/enable logic (DeepSeek-shape + Claude-shape) via a stubbed httpx.

Run:  python tests/engine_phase11.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_TMP = tempfile.mkdtemp(prefix="rr-phase11-")
# Copy the fixture into a throwaway dir — this test toggles `reasoning` via
# update_provider(), which rewrites config.toml; never mutate the committed fixture.
_CFG = Path(_TMP) / "config.toml"
shutil.copy(REPO / "tests" / "config.toml", _CFG)
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(_CFG)
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
sys.path.insert(0, str(REPO))

import httpx as _httpx                                  # noqa: E402
from engine import modes, providers, rooms             # noqa: E402
from engine import transcript as T                      # noqa: E402
from engine.adapters import anthropic_style, openai_style  # noqa: E402
from engine.context import build_context                # noqa: E402

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


class _Recorder:
    """Drop-in for the adapter's `httpx`: records the request body, returns canned."""
    HTTPStatusError = _httpx.HTTPStatusError
    HTTPError = _httpx.HTTPError

    def __init__(self, resp): self.resp = resp; self.sent = None
    def post(self, url, headers=None, json=None, timeout=None):
        self.sent = json; return self.resp


def main() -> int:
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)

    # --- 1. ISOLATION: reasoning in meta never enters forward context --------
    print("1. ISOLATION — meta.reasoning excluded from build_context by construction")
    crafted = [
        T.make_turn("converse", "human", "human", "MAIN_Q"),
        T.make_turn("converse", "ai", "mock", "VISIBLE_ANSWER",
                    {"model": "m", "reasoning": "SECRET_REASONING_TRACE", "reasoning_kind": "full"}),
    ]
    body = build_context(crafted, "mock", "converse")["messages"][0]["content"]
    check("forward context contains the answer text", "VISIBLE_ANSWER" in body)
    check("forward context contains ZERO reasoning text", "SECRET_REASONING_TRACE" not in body)

    # --- 2. capture is opt-in (mock honours the toggle) ----------------------
    print("2. capture opt-in — reasoning-on provider stamps meta.reasoning; off → absent")
    on = rooms.create_room("reasoning on", participants=["mockthink"], judge="mockthink")
    modes.research(on, "why is the sky blue?", effort="low")
    modes.converse(on, "and at sunset?", addressed_to="mockthink")
    turns_on = T.load(rooms.main_path(on))
    panel = next(t for t in turns_on if (t.get("meta") or {}).get("is_panelist_raw"))
    judge = next(t for t in turns_on if t["role"] == "judge")
    conv = next(t for t in turns_on if t["role"] == "ai" and t["mode"] == "converse")
    check("panel turn carries meta.reasoning", bool(panel["meta"].get("reasoning")))
    check("judge turn carries meta.reasoning", bool(judge["meta"].get("reasoning")))
    check("converse turn carries meta.reasoning", bool(conv["meta"].get("reasoning")))
    check("reasoning_kind recorded", panel["meta"].get("reasoning_kind") == "full")

    off = rooms.create_room("reasoning off", participants=["mock"], judge="mock")
    modes.research(off, "same question", effort="low")
    turns_off = T.load(rooms.main_path(off))
    check("toggle off → NO meta.reasoning on any turn",
          all("reasoning" not in (t.get("meta") or {}) for t in turns_off))

    # multi-turn: the on-room's next forward context still excludes all reasoning
    ctx_on = build_context(turns_on, "mockthink", "converse")["messages"][0]["content"]
    check("on-room forward context excludes every reasoning trace",
          "[mock reasoning" not in ctx_on)

    # --- 3. per-provider toggle persists in the registry ---------------------
    print("3. providers toggle persists to the registry")
    providers.update_provider("mock", reasoning=True)
    check("reasoning flag written + reloaded", providers.provider("mock").reasoning is True)
    providers.update_provider("mock", reasoning=False)
    check("reasoning flag clears", providers.provider("mock").reasoning is False)

    # --- 4. adapter capture/enable logic (stubbed httpx) ---------------------
    print("4. adapters — enable + capture (DeepSeek-shape + Claude-shape)")
    P = providers.Provider
    dp = P("ds", "api", "openai", "deepseek-x", True, "#fff", base_url="https://api.deepseek.com")
    payload = {"system": "", "messages": [{"role": "user", "content": "q"}]}

    rec = _Recorder(_Resp({"choices": [{"message":
          {"content": "DS_ANSWER", "reasoning_content": "DS_THOUGHTS"}}],
          "usage": {"prompt_tokens": 11, "completion_tokens": 7}}))
    openai_style.httpx = rec
    text, reasoning, usage = openai_style.chat(dp, "k", payload, reasoning=True)
    check("openai: thinking enabled in request body", "thinking" in (rec.sent or {}))
    check("openai: captured reasoning_content", text == "DS_ANSWER" and reasoning == "DS_THOUGHTS")
    check("openai: captured exact usage", usage == {"input": 11, "output": 7})
    text2, reasoning2, _ = openai_style.chat(dp, "k", payload, reasoning=False)
    check("openai: toggle off → no thinking field, no reasoning",
          "thinking" not in (rec.sent or {}) and reasoning2 is None)
    openai_style.httpx = _httpx

    cp = P("cl", "api", "anthropic", "opus", True, "#fff", base_url="https://api.anthropic.com")
    arec = _Recorder(_Resp({"content": [
        {"type": "thinking", "thinking": "CL_SUMMARY"}, {"type": "text", "text": "CL_ANSWER"}],
        "usage": {"input_tokens": 13, "output_tokens": 5}}))
    anthropic_style.httpx = arec
    atext, areasoning, ausage = anthropic_style.chat(cp, "k", payload, reasoning=True)
    check("anthropic: summarized thinking requested",
          (arec.sent or {}).get("thinking", {}).get("display") == "summarized")
    check("anthropic: NO budget_tokens sent (400s on 4.8)",
          "budget_tokens" not in (arec.sent or {}).get("thinking", {}))
    check("anthropic: text from text blocks, reasoning from thinking blocks",
          atext == "CL_ANSWER" and areasoning == "CL_SUMMARY")
    check("anthropic: captured exact usage", ausage == {"input": 13, "output": 5})
    anthropic_style.httpx = _httpx

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 11 Done-when checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
