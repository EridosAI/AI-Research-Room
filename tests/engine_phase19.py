"""engine_phase19.py — Grok via the Hermes xAI-OAuth proxy (mock + stubbed httpx).

Phase 19's claim is "a config row, not a runner": the Hermes proxy returns a
standard OpenAI chat.completion, so the EXISTING openai_style adapter + call_model
already capture everything. This proves it against the real captured response shape
(grok-4.3 via the proxy): no new adapter code, just a provider row.

  - the adapter parses content / reasoning_content / usage / finish_reason /
    response.model from the proxy's chat.completion;
  - call_model on the proxy provider yields a ModelReply whose served_model is the
    HONEST 'grok-4.3' (not what the prose claims — the live probe's model insisted it
    was 'grok-1'), with reasoning + usage + finish_reason populated;
  - the localhost proxy base_url is NOT mistaken for OpenRouter (no web_search tool
    is attached — search doesn't traverse the proxy; see the 19.2 probe / DEFERRED).

Run:  python tests/engine_phase19.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_TMP = tempfile.mkdtemp(prefix="rr-phase19-")
_CFG = Path(_TMP) / "config.toml"
shutil.copy(REPO / "tests" / "config.toml", _CFG)
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(_CFG)
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
os.environ["RESEARCH_ROOM_SECRETS"] = str(Path(_TMP) / "secrets.json")
sys.path.insert(0, str(REPO))

import httpx as _httpx                                  # noqa: E402
from engine import providers, secrets                  # noqa: E402
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

    def __init__(self, resp): self.resp = resp; self.sent = None; self.url = None
    def post(self, url, headers=None, json=None, timeout=None):
        self.url = url; self.sent = json; return self.resp


# The exact shape the Hermes xAI proxy returned for grok-4.3 in the live probe:
# chat.completion with reasoning_content + usage.reasoning_tokens. Note the prose
# 'content' lies ("grok-1"); response.model is the truth.
_PROXY_RESP = {
    "id": "2e2f0d83", "object": "chat.completion", "model": "grok-4.3",
    "choices": [{"index": 0, "finish_reason": "stop", "message": {
        "role": "assistant",
        "content": "PONG\ngrok-1",
        "reasoning_content": "The task is to reply PONG then state the model id.",
    }}],
    "usage": {"prompt_tokens": 149, "completion_tokens": 7, "total_tokens": 826,
              "completion_tokens_details": {"reasoning_tokens": 670}},
}


def main() -> int:
    P = providers.Provider
    payload = {"system": "", "messages": [{"role": "user", "content": "ping"}]}

    # --- 1. adapter parses the proxy's chat.completion (zero new code) --------
    print("1. openai_style parses the proxy grok-4.3 response (content/reasoning/usage/model/finish)")
    pr = P("grok_proxy", "api", "openai", "grok-4.3", True, "#fff",
           base_url="http://127.0.0.1:8645/v1", reasoning=True)
    rec = _Recorder(_Resp(_PROXY_RESP))
    openai_style.httpx = rec
    text, reasoning, usage, served, search, finish = openai_style.chat(
        pr, "dummy-proxy-key", payload, reasoning=True)
    openai_style.httpx = _httpx
    check("content parsed", text == "PONG\ngrok-1")
    check("reasoning_content captured", reasoning == "The task is to reply PONG then state the model id.")
    check("usage mapped (input/output)", usage == {"input": 149, "output": 7})
    check("served_model is the HONEST grok-4.3 (prose said grok-1)", served == "grok-4.3")
    check("finish_reason captured", finish == "stop")
    check("localhost proxy is NOT treated as OpenRouter (no search tool)",
          not openai_style._is_openrouter(pr) and "tools" not in (rec.sent or {}))
    check("request went to the proxy /chat/completions", rec.url == "http://127.0.0.1:8645/v1/chat/completions")

    # --- 2. full call_model path on the configured proxy row ------------------
    print("2. call_model on the grok_proxy row → ModelReply with honest provenance")
    secrets.set("grok_proxy", "dummy-proxy-key")
    rec2 = _Recorder(_Resp(_PROXY_RESP))
    openai_style.httpx = rec2
    try:
        reply = providers.call_model("grok_proxy", payload, tools=True)   # research-style call
    finally:
        openai_style.httpx = _httpx
        secrets.set("grok_proxy", None)
    check("ModelReply.served_model == grok-4.3", reply.served_model == "grok-4.3")
    check("ModelReply.reasoning populated", bool(reply.reasoning))
    check("ModelReply.usage exact", reply.usage and reply.usage.get("exact") is True)
    check("ModelReply.finish_reason == stop", reply.finish_reason == "stop")
    check("no search trace (proxy carries none)", reply.search is None)

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 19 Done-when checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
