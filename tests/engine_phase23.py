"""engine_phase23.py — Cluster-1 surface wins + the no-search guard (offline).

  - 23.1 cost: OR rows request usage.include and capture the authoritative usage.cost
    into meta.usage; cost is EXCLUDED from build_context (mirrors token-usage isolation).
  - 23.6 guard: a seat with no active web search gets the no-search guard folded into
    its system prompt; a search-on seat does NOT — capability-driven (web_search flag).
  - 23.3 converse: the per-room reasoning effort threads into the converse call.
  - 23.5 dropdown: model_catalog parses /models into {id, context_length, reasoning,
    efforts}; or_model_catalog is [] with no OR key.

Run:  python tests/engine_phase23.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_TMP = tempfile.mkdtemp(prefix="rr-phase23-")
_CFG = Path(_TMP) / "config.toml"
shutil.copy(REPO / "tests" / "config.toml", _CFG)
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(_CFG)
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
os.environ["RESEARCH_ROOM_SECRETS"] = str(Path(_TMP) / "secrets.json")
sys.path.insert(0, str(REPO))

import httpx as _httpx                                     # noqa: E402
from engine import modes, providers, rooms, secrets        # noqa: E402
from engine.adapters import openai_style                   # noqa: E402
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


class _Recorder:
    HTTPStatusError = _httpx.HTTPStatusError
    HTTPError = _httpx.HTTPError

    def __init__(self, resp): self.resp = resp; self.sent = None
    def post(self, url, headers=None, json=None, timeout=None):
        self.sent = json; return self.resp
    def get(self, url, headers=None, timeout=None):
        return self.resp


def main() -> int:
    P = providers.Provider
    payload = {"system": "", "messages": [{"role": "user", "content": "q"}]}
    orp = P("or", "api", "openai", "z-ai/glm-5.2", True, "#fff",
            base_url="https://openrouter.ai/api/v1", reasoning=True)

    # --- 1. cost capture: OR requests usage.include; usage.cost lands in meta ----
    print("1. cost — OR requests usage.include and captures usage.cost")
    resp = {"model": "z-ai/glm-5.2", "choices": [{"finish_reason": "stop",
            "message": {"content": "A"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001234}}
    rec = _Recorder(_Resp(resp)); openai_style.httpx = rec
    text, _r, usage, _s, _se, _f = openai_style.chat(orp, "k", payload)
    openai_style.httpx = _httpx
    check("OR body sends usage:{include:true}", rec.sent.get("usage") == {"include": True})
    check("usage.cost captured into usage dict", usage.get("cost") == 0.001234)
    check("input/output tokens still parsed", usage.get("input") == 10 and usage.get("output") == 5)

    print("   no-cost response → no cost key (off-OR / not returned)")
    rec = _Recorder(_Resp({"model": "x", "choices": [{"message": {"content": "B"}}],
                           "usage": {"prompt_tokens": 1, "completion_tokens": 1}}))
    openai_style.httpx = rec
    _, _, u2, _, _, _ = openai_style.chat(orp, "k", payload)
    openai_style.httpx = _httpx
    check("absent cost → no 'cost' key", "cost" not in u2)

    # --- 2. cost isolation: build_context never serializes meta.usage.cost -------
    print("2. isolation — cost stays in meta, never in forward context")
    turns = [
        {"role": "human", "speaker": "human", "text": "hi", "meta": {}},
        {"role": "ai", "speaker": "or", "text": "answer body",
         "meta": {"usage": {"input": 10, "output": 5, "cost": 0.001234}}},
    ]
    body = build_context(turns, "or", "converse", participants=["or"])["messages"][0]["content"]
    check("cost value not in build_context body", "0.001234" not in body and "cost" not in body)
    check("answer text IS in build_context body", "answer body" in body)

    # --- 3. no-search guard: helper + capability-driven via call_model ----------
    print("3. no-search guard — folded into system when search off, absent when on")
    g = providers._guard_no_search({"system": "BASE", "messages": []}, searches=False)
    check("guard appended to an existing system prompt",
          providers.NO_SEARCH_GUARD in g["system"] and g["system"].startswith("BASE"))
    g2 = providers._guard_no_search({"system": "", "messages": []}, searches=False)
    check("guard becomes the system prompt when none set", g2["system"] == providers.NO_SEARCH_GUARD)
    g3 = providers._guard_no_search({"system": "BASE", "messages": []}, searches=True)
    check("search on → payload unchanged (no guard)", g3["system"] == "BASE")

    secrets.set("or_test", "k"); secrets.set("or_search", "k")
    rec = _Recorder(_Resp({"model": "z-ai/glm-5.2", "choices": [{"message": {"content": "C"}}],
                           "usage": {"prompt_tokens": 1, "completion_tokens": 1}}))
    openai_style.httpx = rec
    providers.call_model("or_test", {"system": "", "messages": [{"role": "user", "content": "q"}]}, tools=True)
    openai_style.httpx = _httpx
    check("search-OFF seat (or_test): guard in assembled system",
          providers.NO_SEARCH_GUARD in json.dumps(rec.sent))

    rec = _Recorder(_Resp({"model": "z-ai/glm-5.2", "choices": [{"message": {"content": "D"}}],
                           "usage": {"prompt_tokens": 1, "completion_tokens": 1}}))
    openai_style.httpx = rec
    providers.call_model("or_search", {"system": "", "messages": [{"role": "user", "content": "q"}]}, tools=True)
    openai_style.httpx = _httpx
    check("search-ON seat (or_search): NO guard", providers.NO_SEARCH_GUARD not in json.dumps(rec.sent))

    # --- 4. converse threads the per-room reasoning effort ----------------------
    print("4. converse — per-room reasoning effort reaches the call")
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)
    rid = rooms.create_room("conv effort", participants=["mock"], judge="mock")
    rooms.update_room(rid, reasoning_effort={"mock": "high"})
    seen = []
    real = providers.call_model

    def _spy(provider_key, payload, tools=False, effort="medium", max_tokens=None, reasoning_effort=None, **kw):
        seen.append((provider_key, tools, reasoning_effort))
        return real(provider_key, payload, tools=tools, effort=effort,
                    max_tokens=max_tokens, reasoning_effort=reasoning_effort, **kw)

    providers.call_model = _spy
    try:
        modes.converse(rid, "hello?", addressed_to="mock")
    finally:
        providers.call_model = real
    conv = [re for (k, tools, re) in seen if not tools and k == "mock"]
    check("converse to 'mock' received room effort 'high'", conv and conv[-1] == "high")

    # --- 5. OR model catalog parse + empty without a key -----------------------
    print("5. model dropdown — model_catalog parse; or_model_catalog [] with no key")
    rec = _Recorder(_Resp({"data": [
        {"id": "z-ai/glm-5.2", "context_length": 131072, "reasoning": {"supported_efforts": ["xhigh", "high"]}},
        {"id": "openai/gpt-5.5", "top_provider": {"context_length": 400000},
         "reasoning": {"supported_efforts": ["high"]}},
        {"id": "x/no-reasoning", "context_length": 8000, "supported_parameters": ["tools"]},
    ]}))
    openai_style.httpx = rec
    cat = openai_style.model_catalog(orp, "k")
    openai_style.httpx = _httpx
    by = {m["id"]: m for m in cat}
    check("catalog sorted + complete (3 models)", len(cat) == 3 and cat[0]["id"] <= cat[1]["id"])
    check("glm context_length parsed", by["z-ai/glm-5.2"]["context_length"] == 131072)
    check("gpt-5.5 context_length from top_provider", by["openai/gpt-5.5"]["context_length"] == 400000)
    check("glm reasoning + ascending efforts", by["z-ai/glm-5.2"]["reasoning"]
          and by["z-ai/glm-5.2"]["supported_efforts"] == ["high", "xhigh"])
    check("non-reasoning model flagged reasoning=False", by["x/no-reasoning"]["reasoning"] is False)

    secrets.set("or_test", None); secrets.set("or_search", None)   # drop keys → no OR row with a key
    providers._model_cat.clear()
    check("or_model_catalog [] when no OR row has a key", providers.or_model_catalog() == [])

    # --- 6. config round-trip: list fields (supported_efforts) survive a UI write ---
    print("6. config write — supported_efforts (a list) round-trips as a TOML array")
    providers.update_provider("mock", context_window=12345)   # any write → _dump_toml + reload
    providers.reload()
    rt = providers.provider("or_test")
    check("supported_efforts still a list after a save (not stringified → None)",
          rt.supported_efforts == ["high", "xhigh"])
    check("create_provider seeds context_window + reasoning",
          (lambda k: (providers.provider(k).context_window == 99000
                      and providers.provider(k).reasoning is True))(
              providers.create_provider("seedtest", "https://openrouter.ai/api/v1",
                                        "vendor/x", context_window=99000, reasoning=True)))

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 23 (cost + guard + converse-effort + OR catalog) checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
