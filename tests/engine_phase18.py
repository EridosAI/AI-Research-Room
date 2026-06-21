"""engine_phase18.py — research token ceiling + finish_reason capture (mock + stubbed httpx).

A truncated answer used to look identical to a complete one. This captures why a turn
stopped (meta.finish_reason, canonical vocab) and gives research its own, larger token
budget. Covers:
  - adapter normalizes finish_reason: openai stop/length/tool_calls pass through;
    anthropic stop_reason max_tokens→length, tool_use→tool_calls, end_turn→stop;
  - max_tokens passes through the adapter request body;
  - modes.research threads settings.RESEARCH_MAX_TOKENS into BOTH panelists and judge
    (and it's larger than the converse ceiling);
  - end-to-end: a mock research turn carries meta.finish_reason; a clean stop never
    forces a footer-only marker.

Run:  python tests/engine_phase18.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_TMP = tempfile.mkdtemp(prefix="rr-phase18-")
_CFG = Path(_TMP) / "config.toml"
shutil.copy(REPO / "tests" / "config.toml", _CFG)
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(_CFG)
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
sys.path.insert(0, str(REPO))

import httpx as _httpx                                  # noqa: E402
from engine import modes, providers, settings, rooms   # noqa: E402
from engine import transcript as T                      # noqa: E402
from engine.adapters import anthropic_style, openai_style  # noqa: E402

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
    HTTPStatusError = _httpx.HTTPStatusError
    HTTPError = _httpx.HTTPError

    def __init__(self, resp): self.resp = resp; self.sent = None
    def post(self, url, headers=None, json=None, timeout=None):
        self.sent = json; return self.resp


def main() -> int:
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)
    P = providers.Provider
    payload = {"system": "", "messages": [{"role": "user", "content": "q"}]}

    # --- 1. finish_reason normalization --------------------------------------
    print("1. finish_reason — normalized to a canonical vocab across backends")
    op = P("op", "api", "openai", "x", True, "#fff", base_url="https://api.deepseek.com")
    for fr in ("stop", "length", "tool_calls"):
        rec = _Recorder(_Resp({"choices": [{"message": {"content": "A"}, "finish_reason": fr}]}))
        openai_style.httpx = rec
        _, _, _, _, _, got = openai_style.chat(op, "k", payload)
        check(f"openai finish_reason {fr!r} passes through", got == fr)
    openai_style.httpx = _httpx

    cp = P("cp", "api", "anthropic", "x", True, "#fff", base_url="https://api.anthropic.com")
    for sr, canon in (("end_turn", "stop"), ("max_tokens", "length"), ("tool_use", "tool_calls")):
        arec = _Recorder(_Resp({"content": [{"type": "text", "text": "A"}], "stop_reason": sr}))
        anthropic_style.httpx = arec
        _, _, _, _, _, got = anthropic_style.chat(cp, "k", payload)
        check(f"anthropic stop_reason {sr!r} → {canon!r}", got == canon)
    anthropic_style.httpx = _httpx

    # --- 2. max_tokens passes through to the request body --------------------
    print("2. max_tokens — threaded into the adapter request body")
    rec = _Recorder(_Resp({"choices": [{"message": {"content": "A"}, "finish_reason": "stop"}]}))
    openai_style.httpx = rec
    openai_style.chat(op, "k", payload, max_tokens=31337)
    check("openai: explicit max_tokens used in body", (rec.sent or {}).get("max_tokens") == 31337)
    openai_style.chat(op, "k", payload)
    check("openai: default falls back to CONVERSE_MAX_TOKENS",
          (rec.sent or {}).get("max_tokens") == settings.CONVERSE_MAX_TOKENS)
    openai_style.httpx = _httpx

    # --- 3. research threads RESEARCH_MAX_TOKENS into panelists AND judge -----
    print("3. modes.research uses the (larger) research budget for panelists + judge")
    check("RESEARCH_MAX_TOKENS > CONVERSE_MAX_TOKENS",
          settings.RESEARCH_MAX_TOKENS > settings.CONVERSE_MAX_TOKENS)
    seen = []
    real_call = providers.call_model

    def _spy(provider_key, payload, tools=False, effort="medium", max_tokens=None, **kw):
        seen.append((provider_key, tools, max_tokens))
        return real_call(provider_key, payload, tools=tools, effort=effort, max_tokens=max_tokens, **kw)

    providers.call_model = _spy   # modes calls providers.call_model by attribute → this patch is seen
    try:
        rid = rooms.create_room("budget room", participants=["mock"], judge="mock")
        modes.research(rid, "thorough question?", effort="low")
    finally:
        providers.call_model = real_call
    research_budgets = [mt for (_k, tools, mt) in seen if tools]
    check("at least panelist + judge calls were tools=True", len(research_budgets) >= 2)
    check("every research call requested RESEARCH_MAX_TOKENS",
          bool(research_budgets) and all(mt == settings.RESEARCH_MAX_TOKENS for mt in research_budgets))

    # --- 4. end-to-end: meta.finish_reason recorded (mock → "stop") ----------
    print("4. end-to-end — research turns carry meta.finish_reason (read-back)")
    turns = T.load(rooms.main_path(rid))
    panel = next(t for t in turns if (t.get("meta") or {}).get("is_panelist_raw"))
    judge = next(t for t in turns if t["role"] == "judge")
    check("panel turn carries meta.finish_reason == 'stop'", panel["meta"].get("finish_reason") == "stop")
    check("judge turn carries meta.finish_reason == 'stop'", judge["meta"].get("finish_reason") == "stop")

    # --- 5. connection-test ping clears the reasoning-model floor (>=16) -----
    print("5. test_provider ping uses a reasoning-safe budget, not 1 (GPT-5.x floor=16)")
    from engine import secrets                       # noqa: E402
    cap = {}

    def _rec(provider, key, payload, max_tokens=None, **kw):
        cap["max_tokens"] = max_tokens
        return ("ok", None, None, None, None, "stop")

    secrets.set("deepseek", "dummy-key")             # deepseek = openai backend in the fixture
    orig = openai_style.chat
    openai_style.chat = _rec
    try:
        res = providers.test_provider("deepseek")
    finally:
        openai_style.chat = orig
        secrets.set("deepseek", None)
    check("test ping >= 16 (clears the reasoning floor)", (cap.get("max_tokens") or 0) >= 16)
    check("test ping uses TEST_MAX_TOKENS", cap.get("max_tokens") == providers.TEST_MAX_TOKENS)
    check("test reports ok", res.get("ok") is True)

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 18 Done-when checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
