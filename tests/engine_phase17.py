"""engine_phase17.py — per-panelist web search (mock + stubbed-httpx).

Web search is attached server-side on tools=True calls when the provider's
`web_search` toggle is on, and the search trace is captured into meta.search /
meta.citations — which, like reasoning, must NEVER leak into forward context.
Covers:
  - adapter ATTACH: anthropic adds web_search_20260209; openai+OpenRouter adds
    openrouter:web_search; flag off → no tool (request byte-identical to plain chat);
    non-OpenRouter openai base never attaches (no mechanism);
  - adapter CAPTURE: Claude search blocks + OpenRouter url_citation annotations
    normalize into {searches, citations};
  - end-to-end: a search-enabled mock panelist's turn carries meta.search +
    meta.citations, persisted (read-back);
  - ISOLATION: meta.search is excluded from build_context by construction.

Run:  python tests/engine_phase17.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_TMP = tempfile.mkdtemp(prefix="rr-phase17-")
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
    HTTPStatusError = _httpx.HTTPStatusError
    HTTPError = _httpx.HTTPError

    def __init__(self, resp): self.resp = resp; self.sent = None
    def post(self, url, headers=None, json=None, timeout=None):
        self.sent = json; return self.resp


def _tool_types(body):
    return [t.get("type") for t in (body or {}).get("tools", [])]


def main() -> int:
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)
    P = providers.Provider
    payload = {"system": "", "messages": [{"role": "user", "content": "q"}]}

    # --- 1. ATTACH: the right tool on, nothing off ---------------------------
    print("1. adapter attach — web_search tool added iff toggle on (+ correct backend)")
    cp = P("cl", "api", "anthropic", "opus", True, "#fff", base_url="https://api.anthropic.com")
    arec = _Recorder(_Resp({"model": "served", "content": [{"type": "text", "text": "A"}]}))
    anthropic_style.httpx = arec
    anthropic_style.chat(cp, "k", payload, web_search=True)
    check("anthropic: web_search_20260209 tool attached", "web_search_20260209" in _tool_types(arec.sent))
    anthropic_style.chat(cp, "k", payload, web_search=False)
    check("anthropic: flag off → no tools (byte-identical to plain chat)", "tools" not in (arec.sent or {}))
    anthropic_style.httpx = _httpx

    orp = P("or", "api", "openai", "x", True, "#fff", base_url="https://openrouter.ai/api/v1")
    dsp = P("ds", "api", "openai", "x", True, "#fff", base_url="https://api.deepseek.com")
    orec = _Recorder(_Resp({"model": "served", "choices": [{"message": {"content": "A"}}]}))
    openai_style.httpx = orec
    openai_style.chat(orp, "k", payload, web_search=True)
    check("openai+OpenRouter: openrouter:web_search tool attached", "openrouter:web_search" in _tool_types(orec.sent))
    openai_style.chat(orp, "k", payload, web_search=False)
    check("openai+OpenRouter: flag off → no tools", "tools" not in (orec.sent or {}))
    openai_style.chat(dsp, "k", payload, web_search=True)
    check("openai non-OpenRouter base: no tool attached (no mechanism)", "tools" not in (orec.sent or {}))
    openai_style.httpx = _httpx

    # --- 2. CAPTURE: provider blocks/annotations → normalized {searches, citations} ---
    print("2. adapter capture — normalize Claude blocks + OpenRouter annotations")
    arec2 = _Recorder(_Resp({"model": "served", "content": [
        {"type": "server_tool_use", "name": "web_search", "input": {"query": "optical computing"}},
        {"type": "web_search_tool_result", "content": [
            {"url": "https://a.example/x", "title": "A", "page_age": "2025"}]},
        {"type": "text", "text": "answer",
         "citations": [{"url": "https://a.example/x", "title": "A", "cited_text": "snip"}]}]}))
    anthropic_style.httpx = arec2
    _, _, _, _, asearch, _ = anthropic_style.chat(cp, "k", payload, web_search=True)
    check("anthropic: query captured", asearch and asearch["searches"][0]["query"] == "optical computing")
    check("anthropic: source captured", asearch["searches"][0]["sources"][0]["url"] == "https://a.example/x")
    check("anthropic: citation captured", asearch["citations"][0]["cited_text"] == "snip")
    anthropic_style.httpx = _httpx

    orec2 = _Recorder(_Resp({"model": "served", "choices": [{"message": {"content": "A", "annotations": [
        {"type": "url_citation", "url_citation": {"url": "https://b.example/y", "title": "B", "content": "ctx"}}]}}]}))
    openai_style.httpx = orec2
    _, _, _, _, osearch, _ = openai_style.chat(orp, "k", payload, web_search=True)
    check("openai+OpenRouter: annotation → source", osearch and osearch["searches"][0]["sources"][0]["url"] == "https://b.example/y")
    check("openai+OpenRouter: annotation → citation", osearch["citations"][0]["title"] == "B")
    openai_style.httpx = _httpx

    # --- 3. end-to-end: a search-enabled mock panelist stamps meta.search --------
    print("3. end-to-end — search-enabled mock panelist carries meta.search (persisted)")
    rid = rooms.create_room("search room", participants=["mocksearch"], judge="mocksearch")
    modes.research(rid, "state of optical computing?", effort="low")
    turns = T.load(rooms.main_path(rid))   # read back from disk → proves persistence
    panel = next(t for t in turns if (t.get("meta") or {}).get("is_panelist_raw"))
    judge = next(t for t in turns if t["role"] == "judge")
    check("panel turn carries meta.search", bool(panel["meta"].get("search")))
    check("panel turn carries meta.citations", bool(panel["meta"].get("citations")))
    check("synthesis turn carries meta.search", bool(judge["meta"].get("search")))
    check("a source url is recorded",
          panel["meta"]["search"][0]["sources"][0]["url"] == "https://example.com/a")

    # converse is OUT of scope (tools=False) → no search captured
    modes.converse(rid, "and the near-term outlook?", addressed_to="mocksearch")
    conv = next(t for t in T.load(rooms.main_path(rid)) if t["role"] == "ai" and t["mode"] == "converse")
    check("converse turn has NO meta.search (search is research-only)", "search" not in conv["meta"])

    # --- 4. ISOLATION: meta.search excluded from forward context -------------
    print("4. ISOLATION — meta.search excluded from build_context by construction")
    crafted = [
        T.make_turn("converse", "human", "human", "MAIN_Q"),
        T.make_turn("converse", "ai", "mock", "VISIBLE_ANSWER",
                    {"model": "m",
                     "search": [{"query": "q", "sources": [{"url": "https://secret.example/leak", "title": "S"}]}],
                     "citations": [{"url": "https://secret.example/leak", "title": "S"}]}),
    ]
    body = build_context(crafted, "mock", "converse")["messages"][0]["content"]
    check("forward context contains the answer text", "VISIBLE_ANSWER" in body)
    check("forward context contains ZERO source URLs", "secret.example" not in body)

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 17 Done-when checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
