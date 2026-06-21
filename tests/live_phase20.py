"""live_phase20.py — OPT-IN real-key probe: OpenRouter reasoning effort (costs a few cents).

Confirms the Phase-20 claim AND the instant-Claude fix in one call: through OpenRouter,
`reasoning: {enabled, effort: "high"}` makes Opus 4.8 actually think and return non-empty
reasoning (`reasoning_details`/`reasoning`). SKIPPED unless RR_LIVE=1. Uses the REAL config +
secrets. Picks the OpenRouter provider automatically (base contains openrouter.ai); override the
model with RR_OR_MODEL (default anthropic/claude-opus-4.8):

  RR_LIVE=1 python tests/live_phase20.py
  RR_LIVE=1 RR_OR_MODEL=openai/gpt-5.5 python tests/live_phase20.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

if os.environ.get("RR_LIVE") != "1":
    print("live_phase20: SKIPPED (set RR_LIVE=1 to run a real, billed probe)")
    raise SystemExit(0)

from engine import providers, secrets                  # noqa: E402
from engine.adapters import openai_style                # noqa: E402

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0


def check(label, cond, detail=""):
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fails += 1


def main() -> int:
    or_key = None
    for k, p in providers.registry().items():
        if "openrouter.ai" in (p.base_url or ""):
            or_key = k
            break
    if not or_key:
        print("no OpenRouter provider in the registry — add one, then re-run."); return 1
    base = providers.provider(or_key)
    key = secrets.get(or_key)
    if not key:
        print(f"no API key for '{or_key}' — set it, then re-run."); return 1

    model = os.environ.get("RR_OR_MODEL", "anthropic/claude-opus-4.8")
    probe = providers.Provider(or_key, "api", "openai", model, True, "#fff",
                               base_url=base.base_url, reasoning=True)
    payload = {"system": "", "messages": [{"role": "user",
               "content": "Briefly: what's heavier, a kilo of feathers or a kilo of steel? Think it through."}]}
    print(f"live probe — provider={or_key!r} model={model!r}, reasoning effort=high")
    try:
        text, reasoning, usage, served, _search, finish = openai_style.chat(
            probe, key, payload, reasoning=True, reasoning_effort="high", max_tokens=2048)
    except Exception as e:  # noqa: BLE001
        check("reasoning:{effort:high} call succeeded (OR mapped it)", False, str(e)[:200]); return 1
    check("call succeeded (OR mapped reasoning.effort to the backend)", True, f"served={served} finish={finish}")
    check("non-empty reasoning returned (instant-Claude fix confirmed)", bool(reasoning),
          f"{len((reasoning or ''))} chars")
    check("answer text returned", bool(text and text.strip()))
    if reasoning:
        print(f"      reasoning head: {reasoning[:160]!r}")
    print()
    if _fails:
        print(f"\033[31m{_fails} live check(s) failed — reasoning may not be wired for this model\033[0m"); return 1
    print("\033[32mlive reasoning-effort probe passed — effort high → real thinking\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
