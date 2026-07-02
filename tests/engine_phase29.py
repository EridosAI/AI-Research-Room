"""engine_phase29.py — prompt caching: cache the re-sent transcript prefix (offline).

Converse/transcript-context re-sends the whole conversation every turn. Phase 29 marks the
stable transcript prefix with a cache_control breakpoint so OR/Anthropic serve it from
cache (~10% cost) instead of re-prefilling:
  - the last user message is split at "Respond as […]" → cached head (cache_control + ttl)
    + volatile tail; the full text is preserved;
  - OR-only, and a cached request that 400s transparently retries WITHOUT caching (caching
    can never break a turn);
  - cached-token count (prompt_tokens_details.cached_tokens) → usage.cached;
  - modes pass cache=True for transcript-context rounds (converse), False for blind panels.

Run:  python tests/engine_phase29.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_TMP = tempfile.mkdtemp(prefix="rr-phase29-")
_CFG = Path(_TMP) / "config.toml"
shutil.copy(REPO / "tests" / "config.toml", _CFG)
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(_CFG)
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
os.environ["RESEARCH_ROOM_SECRETS"] = str(Path(_TMP) / "secrets.json")
sys.path.insert(0, str(REPO))

import copy                                                 # noqa: E402
import httpx as _httpx                                     # noqa: E402
from engine import modes, providers, rooms, settings, secrets   # noqa: E402
from engine.adapters import openai_style                   # noqa: E402

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0


def check(label, cond):
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}")
    if not cond:
        _fails += 1


class _Resp:
    def __init__(self, d, status=200): self._d = d; self.status_code = status
    def raise_for_status(self):
        if self.status_code >= 400:
            raise _httpx.HTTPStatusError("err", request=None, response=self)
    @property
    def text(self): return "error body"
    def json(self): return self._d


class _Rec:
    HTTPStatusError = _httpx.HTTPStatusError
    HTTPError = _httpx.HTTPError

    def __init__(self, resp): self.resp = resp; self.sent = None
    def post(self, url, headers=None, json=None, timeout=None): self.sent = json; return self.resp


class _Fail400Once:
    """Rejects the first (cached) request with 400, accepts the plain retry — proves the
    transparent fallback. Records the body of each attempt."""
    HTTPStatusError = _httpx.HTTPStatusError
    HTTPError = _httpx.HTTPError

    def __init__(self, ok_resp): self.ok = ok_resp; self.sent = []
    def post(self, url, headers=None, json=None, timeout=None):
        self.sent.append(copy.deepcopy(json))   # snapshot: chat() reuses+mutates the body for the retry
        if len(self.sent) == 1:
            return _Resp({}, status=400)
        return self.ok


def _user_msg(body):
    return next(m for m in body["messages"] if m["role"] == "user")


def main() -> int:
    P = providers.Provider
    orp = P("or", "api", "openai", "anthropic/claude-opus-4.8", True, "#fff",
            base_url="https://openrouter.ai/api/v1")
    # a transcript-context payload looks like build_context output: ends with "Respond as […]"
    convo = "[human]: hi\n\n[claude]: hello\n\n[human]: go on\n\nRespond as [claude]."
    payload = {"system": "you are claude", "messages": [{"role": "user", "content": convo}]}

    # --- 1. cache=True (OR): the transcript prefix is split + marked, text preserved ---
    print("1. cache split — stable prefix gets cache_control; tail stays volatile")
    ok = {"model": "anthropic/claude-opus-4.8", "choices": [{"finish_reason": "stop",
          "message": {"content": "A"}}], "usage": {"prompt_tokens": 100, "completion_tokens": 5}}
    rec = _Rec(_Resp(ok)); openai_style.httpx = rec
    openai_style.chat(orp, "k", payload, cache=True)
    openai_style.httpx = _httpx
    um = _user_msg(rec.sent)
    check("user content became a 2-part list (head + tail)", isinstance(um["content"], list) and len(um["content"]) == 2)
    head, tail = um["content"]
    check("head carries cache_control with the configured ttl",
          head.get("cache_control", {}).get("type") == "ephemeral"
          and head["cache_control"].get("ttl") == settings.PROMPT_CACHE_TTL)
    check("tail (Respond as …) is NOT cached", "cache_control" not in tail)
    check("full text preserved across the split", head["text"] + tail["text"] == convo)
    check("the cached head holds the transcript; the tail holds 'Respond as'",
          "go on" in head["text"] and tail["text"].startswith("Respond as ["))

    # --- 2. cache=False → plain string (unchanged) ------------------------------
    print("2. cache off → plain string body (unchanged)")
    rec = _Rec(_Resp(ok)); openai_style.httpx = rec
    openai_style.chat(orp, "k", payload, cache=False)
    openai_style.httpx = _httpx
    check("no cache → user content stays a plain string", isinstance(_user_msg(rec.sent)["content"], str))

    # --- 3. non-OR provider → never cached --------------------------------------
    print("3. non-OR provider → cache_control never attached")
    direct = P("ds", "api", "openai", "deepseek-x", True, "#fff", base_url="https://api.deepseek.com")
    rec = _Rec(_Resp(ok)); openai_style.httpx = rec
    openai_style.chat(direct, "k", payload, cache=True)
    openai_style.httpx = _httpx
    check("non-OR row: content stays a plain string even with cache=True",
          isinstance(_user_msg(rec.sent)["content"], str))

    # --- 4. transparent fallback: a cached 400 retries without cache ------------
    print("4. fallback — a rejected cached request retries plain (caching never breaks a turn)")
    fail = _Fail400Once(_Resp(ok)); openai_style.httpx = fail
    text, _r, _u, _s, _se, finish = openai_style.chat(orp, "k", payload, cache=True)
    openai_style.httpx = _httpx
    check("two attempts made (cached, then plain retry)", len(fail.sent) == 2)
    check("attempt 1 was cached (list content)", isinstance(_user_msg(fail.sent[0])["content"], list))
    check("attempt 2 (retry) was plain (string content)", isinstance(_user_msg(fail.sent[1])["content"], str))
    check("the turn still succeeded after fallback", text == "A" and finish == "stop")

    # --- 5. cached-token capture → usage.cached ---------------------------------
    print("5. cached-token capture — prompt_tokens_details.cached_tokens → usage.cached")
    hit = {"model": "anthropic/claude-opus-4.8", "choices": [{"message": {"content": "A"}}],
           "usage": {"prompt_tokens": 5000, "completion_tokens": 5,
                     "prompt_tokens_details": {"cached_tokens": 4800}}}
    rec = _Rec(_Resp(hit)); openai_style.httpx = rec
    _, _, usage, _, _, _ = openai_style.chat(orp, "k", payload, cache=True)
    openai_style.httpx = _httpx
    check("usage.cached = cached_tokens (4800)", usage.get("cached") == 4800)
    rec = _Rec(_Resp(ok)); openai_style.httpx = rec          # `ok` has no prompt_tokens_details
    _, _, u_nohit, _, _, _ = openai_style.chat(orp, "k", payload, cache=True)
    openai_style.httpx = _httpx
    check("a no-cache-hit response → no 'cached' key", "cached" not in u_nohit)

    # --- 6. modes pass cache for transcript context, not blind panels -----------
    print("6. routing — converse caches (transcript); a blind panel does not")
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)
    rid = rooms.create_room("c", participants=["mock"], judge="mock")
    seen = []
    real = providers.call_model

    def spy(provider_key, payload, tools=False, effort="medium", max_tokens=None, reasoning_effort=None, cache=False, **kw):
        seen.append((provider_key, tools, cache))
        return real(provider_key, payload, tools=tools, effort=effort,
                    max_tokens=max_tokens, reasoning_effort=reasoning_effort, cache=cache, **kw)

    providers.call_model = spy
    try:
        modes.converse(rid, "hello?", addressed_to="mock")                 # transcript → cache
        modes.research(rid, "task?", panel=["mock"], judge="mock")         # blind panel → no cache
    finally:
        providers.call_model = real
    conv_cache = [c for (k, tools, c) in seen if not tools and k == "mock"]
    panel_cache = [c for (k, tools, c) in seen if tools and k == "mock"]
    check("converse call requested caching", conv_cache and conv_cache[-1] is True)
    check("blind panel call did NOT request caching", panel_cache and all(c is False for c in panel_cache))

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 29 (prompt caching: prefix cache + fallback + capture + routing) checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
