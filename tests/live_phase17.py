"""live_phase17.py — OPT-IN real-key probe for web search (costs a few cents).

Mirrors the phase-11 live check. SKIPPED unless RR_LIVE=1. Uses the REAL config +
secrets (so set RESEARCH_ROOM_CONFIG / keys as you normally run the app). It issues
one Anthropic web_search call and one OpenRouter web_search call with a prompt that
*requires* fresh info, then confirms the trace parsed — i.e. that:
  - the dated Anthropic tool string (anthropic_style.WEB_SEARCH_TOOL) is still
    accepted (no 400) and returns search blocks, and
  - OpenRouter's `openrouter:web_search` tool returns url_citation annotations,
both normalizing into meta-shaped {searches, citations}.

If the API shapes have drifted (the dated string bumped, OR changed the tool id or
the annotation field names), this is where it surfaces — fix the adapter to match,
then re-run. Pick the providers via env or it auto-detects by backend/base_url:
  RR_LIVE=1 python tests/live_phase17.py
  RR_LIVE=1 RR_ANTHROPIC=claude RR_OPENROUTER=openrouter python tests/live_phase17.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

if os.environ.get("RR_LIVE") != "1":
    print("live_phase17: SKIPPED (set RR_LIVE=1 to run a real, billed probe)")
    raise SystemExit(0)

from engine import providers, secrets                  # noqa: E402
from engine.adapters import anthropic_style, openai_style  # noqa: E402

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0


def check(label, cond, detail=""):
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fails += 1


def _find(backend=None, base_substr=None, override_env=None):
    if override_env and os.environ.get(override_env):
        return os.environ[override_env]
    for k, p in providers.registry().items():
        if backend and p.backend != backend:
            continue
        if base_substr and base_substr not in (p.base_url or ""):
            continue
        return k
    return None


PROMPT = ("Use web search. What is a news headline from the last 48 hours? "
          "Cite the source URL.")


def _probe(name, adapter):
    p = providers.provider(name)
    key = secrets.get(name)
    if not key:
        check(f"{name}: has an API key", False, "no key in secrets — skip"); return
    payload = {"system": "", "messages": [{"role": "user", "content": PROMPT}]}
    try:
        text, _reasoning, _usage, served, search = adapter.chat(p, key, payload, web_search=True)
    except Exception as e:  # noqa: BLE001
        check(f"{name}: web_search call succeeded (tool string accepted)", False, str(e)[:200]); return
    check(f"{name}: web_search call succeeded (tool string accepted)", True, f"served={served}")
    n = len(search["searches"]) if (search and search.get("searches")) else 0
    cites = len(search["citations"]) if (search and search.get("citations")) else 0
    check(f"{name}: search trace parsed (searches/citations > 0)", bool(search) and (n or cites),
          f"searches={n} citations={cites}")
    if search and search.get("citations"):
        print(f"      e.g. {search['citations'][0].get('url')}")


def main() -> int:
    anth = _find(backend="anthropic", override_env="RR_ANTHROPIC")
    orr = _find(base_substr="openrouter.ai", override_env="RR_OPENROUTER")
    print(f"live probe — anthropic={anth!r}  openrouter={orr!r}")
    if anth:
        print(f"1. Anthropic web_search ({anth}) — tool {anthropic_style.WEB_SEARCH_TOOL['type']}")
        _probe(anth, anthropic_style)
    else:
        print("1. (no anthropic provider found — skip)")
    if orr:
        print(f"2. OpenRouter web_search ({orr})")
        _probe(orr, openai_style)
    else:
        print("2. (no openrouter provider found — skip)")
    print()
    if _fails:
        print(f"\033[31m{_fails} live check(s) failed — the API shape may have drifted; "
              f"update the adapter to match\033[0m"); return 1
    print("\033[32mlive web-search probe passed — adapter shapes match current APIs\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
