"""engine_phase20.py — OpenRouter reasoning request + capture (mock + stubbed httpx).

Phase 20 routes the reasoning panelists through OpenRouter, so the adapter speaks OR's
unified reasoning shape:
  - REQUEST: OR rows send `reasoning: {enabled, effort}` (maps to each backend incl.
    Claude's adaptive API); direct providers keep the `thinking`/`reasoning_effort` switch.
  - CAPTURE: reasoning comes from `reasoning_details` (render summary+text, SKIP
    encrypted) → flat `reasoning` string → `reasoning_content` (direct). Miss this and
    every disclosure goes blank post-switch.
  - served_model + usage still parse; effort threads from call_model.

Run:  python tests/engine_phase20.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_TMP = tempfile.mkdtemp(prefix="rr-phase20-")
_CFG = Path(_TMP) / "config.toml"
shutil.copy(REPO / "tests" / "config.toml", _CFG)
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(_CFG)
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
os.environ["RESEARCH_ROOM_SECRETS"] = str(Path(_TMP) / "secrets.json")
sys.path.insert(0, str(REPO))

import httpx as _httpx                                  # noqa: E402
from engine import modes, providers, rooms              # noqa: E402
from engine.adapters import openai_style                # noqa: E402

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
    P = providers.Provider
    payload = {"system": "", "messages": [{"role": "user", "content": "q"}]}
    orp = P("or", "api", "openai", "anthropic/claude-opus-4.8", True, "#fff",
            base_url="https://openrouter.ai/api/v1", reasoning=True)

    # --- 1. REQUEST shape: OR reasoning param + effort, no direct thinking switch ---
    print("1. request — OR sends reasoning:{enabled,effort}; direct keeps thinking switch")
    resp = {"model": "anthropic/claude-opus-4.8", "choices": [{"finish_reason": "stop", "message": {
        "content": "A", "reasoning_details": [
            {"type": "reasoning.summary", "summary": "SUM"},
            {"type": "reasoning.text", "text": "TXT"},
            {"type": "reasoning.encrypted", "data": "ENCRYPTED_BLOB"}]}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3,
                  "completion_tokens_details": {"reasoning_tokens": 99}}}
    rec = _Recorder(_Resp(resp))
    openai_style.httpx = rec
    text, reasoning, usage, served, search, finish = openai_style.chat(
        orp, "k", payload, reasoning=True, reasoning_effort="high")
    openai_style.httpx = _httpx
    check("OR sends reasoning:{enabled,effort}", rec.sent.get("reasoning") == {"enabled": True, "effort": "high"})
    check("OR does NOT send the direct `thinking` switch", "thinking" not in rec.sent)
    check("OR does NOT send top-level reasoning_effort", "reasoning_effort" not in rec.sent)

    # --- 2. CAPTURE: reasoning_details summary+text rendered, encrypted skipped ---
    print("2. capture — reasoning_details (summary+text), encrypted skipped")
    check("summary + text joined", reasoning == "SUM\n\nTXT")
    check("encrypted blob skipped", "ENCRYPTED_BLOB" not in (reasoning or ""))
    check("served_model parsed (OR slug)", served == "anthropic/claude-opus-4.8")
    check("usage parsed (input/output + reasoning tokens captured)",
          usage == {"input": 5, "output": 3, "reasoning": 99})
    check("finish_reason parsed", finish == "stop")

    # --- 3. fallback: flat `reasoning` string when no details ---
    print("3. capture fallback — flat message.reasoning string")
    rec = _Recorder(_Resp({"model": "z-ai/glm-5.2", "choices": [{"message": {
        "content": "B", "reasoning": "FLAT_REASONING"}}]}))
    openai_style.httpx = rec
    _, r2, _, _, _, _ = openai_style.chat(orp, "k", payload, reasoning=True, reasoning_effort="medium")
    openai_style.httpx = _httpx
    check("flat reasoning string captured", r2 == "FLAT_REASONING")
    check("effort 'medium' threaded", rec.sent.get("reasoning") == {"enabled": True, "effort": "medium"})

    # --- 4. direct provider (non-OR) still uses reasoning_content + thinking switch ---
    print("4. direct provider — reasoning_content + thinking switch unchanged")
    dsp = P("ds", "api", "openai", "deepseek-x", True, "#fff", base_url="https://api.deepseek.com", reasoning=True)
    rec = _Recorder(_Resp({"choices": [{"message": {"content": "C", "reasoning_content": "DS_THOUGHTS"}}]}))
    openai_style.httpx = rec
    _, r3, _, _, _, _ = openai_style.chat(dsp, "k", payload, reasoning=True)
    openai_style.httpx = _httpx
    check("direct: reasoning_content captured", r3 == "DS_THOUGHTS")
    check("direct: still sends `thinking` switch", "thinking" in rec.sent and "reasoning" not in rec.sent)

    # --- 5. reasoning off → no reasoning requested or captured ---
    print("5. reasoning off → nothing requested/captured")
    rec = _Recorder(_Resp({"model": "x", "choices": [{"message": {"content": "D", "reasoning": "SHOULD_IGNORE"}}]}))
    openai_style.httpx = rec
    _, r4, _, _, _, _ = openai_style.chat(orp, "k", payload, reasoning=False)
    openai_style.httpx = _httpx
    check("off: no reasoning param", "reasoning" not in rec.sent)
    check("off: reasoning not captured", r4 is None)

    # --- 6. per-room effort threads from room.json → call_model --------------
    print("6. per-room reasoning_effort threads into the panelist call")
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)
    rid = rooms.create_room("effort room", participants=["mock"], judge="mock")
    rooms.update_room(rid, reasoning_effort={"mock": "low"})
    seen = []
    real = providers.call_model

    def _spy(provider_key, payload, tools=False, effort="medium", max_tokens=None, reasoning_effort=None, **kw):
        seen.append((provider_key, tools, reasoning_effort))
        return real(provider_key, payload, tools=tools, effort=effort,
                    max_tokens=max_tokens, reasoning_effort=reasoning_effort, **kw)

    providers.call_model = _spy
    try:
        modes.research(rid, "q?", effort="low")
        modes.converse(rid, "follow-up?", addressed_to="mock")
    finally:
        providers.call_model = real
    research_efforts = [re for (_k, tools, re) in seen if tools]
    check("panelist/judge calls received room effort 'low'",
          bool(research_efforts) and all(e == "low" for e in research_efforts))
    conv = [re for (k, tools, re) in seen if not tools and k == "mock"]
    check("converse to 'mock' received room effort 'low'", conv and conv[-1] == "low")

    rid2 = rooms.create_room("default room", participants=["mock"], judge="mock")  # no overrides
    seen.clear()
    providers.call_model = _spy
    try:
        modes.research(rid2, "q?", effort="low")
    finally:
        providers.call_model = real
    check("no override → reasoning_effort is None (model default)",
          all(re is None for (_k, tools, re) in seen if tools))

    # --- 7. effort metadata: parse OR /models, reverse to ascending, per-model ----
    print("7. effort metadata — parsed per-model from /models (reversed to ascending)")
    catalog = openai_style._parse_effort_catalog({"data": [
        {"id": "z-ai/glm-5.2", "reasoning": {"supported_efforts": ["xhigh", "high"]}},      # highest-first
        {"id": "openai/gpt-5.5", "reasoning": {"supported_efforts": ["xhigh", "high", "medium", "low", "none"]}},
        # the bug: Claude via OR is adaptive → reasoning object but NO enumerated efforts.
        {"id": "anthropic/claude-opus-4.8", "supported_parameters": ["reasoning"], "reasoning": {"mandatory": False}},
        {"id": "x/all-accepted", "reasoning": {"supported_efforts": None}},                  # null = all
        {"id": "x/no-reasoning", "supported_parameters": ["tools"]},                         # no reasoning → omitted
    ]})
    check("GLM efforts reversed to ascending [high, xhigh]", catalog.get("z-ai/glm-5.2") == ["high", "xhigh"])
    check("gpt-5.5 enumerated set ascending", catalog.get("openai/gpt-5.5") == ["none", "low", "medium", "high", "xhigh"])
    check("Claude (reasoning, no enumerated efforts) → OR ladder, NOT dropped",
          catalog.get("anthropic/claude-opus-4.8") == openai_style._OR_LADDER)
    check("null supported_efforts → full ladder", catalog.get("x/all-accepted") == openai_style._OR_LADDER)
    check("non-reasoning model omitted (no selector)", "x/no-reasoning" not in catalog)
    # config override wins (no network), and is returned ascending as-authored
    glm = providers.provider("or_test")
    check("config supported_efforts override is used verbatim",
          providers.effort_options(glm) == ["high", "xhigh"])
    check("non-OR row → no effort options", providers.effort_options(providers.provider("mock")) is None)

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 20 (reasoning request+capture+effort+metadata) checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
