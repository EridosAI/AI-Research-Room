"""engine_phase24.py — context-window accuracy (effective routed window + flags).

OpenRouter routes a model across providers who may serve a SMALLER window than the
headline. Phase 24 calibrates the ring to the effective window and flags reduced/changed:
  - model_catalog exposes `effective_window` (top_provider.context_length) beside the
    headline `context_length`;
  - endpoints_min_window parses the conservative floor across a model's endpoints;
  - window_info resolves effective (top_provider, else endpoints-min), flags `reduced`
    (effective < headline) and `changed` (fresh headline != seeded config window);
  - off-OR seats fall back to the configured window with no comparison.

Run:  python tests/engine_phase24.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_TMP = tempfile.mkdtemp(prefix="rr-phase24-")
_CFG = Path(_TMP) / "config.toml"
shutil.copy(REPO / "tests" / "config.toml", _CFG)
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(_CFG)
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
os.environ["RESEARCH_ROOM_SECRETS"] = str(Path(_TMP) / "secrets.json")
sys.path.insert(0, str(REPO))

import httpx as _httpx                                     # noqa: E402
from engine import providers, secrets                       # noqa: E402
from engine.adapters import openai_style                    # noqa: E402

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


class _Stub:
    """Stubs httpx.get; returns the endpoints payload for an /endpoints URL, else /models."""
    HTTPStatusError = _httpx.HTTPStatusError
    HTTPError = _httpx.HTTPError

    def __init__(self, models, endpoints=None): self.models = models; self.endpoints = endpoints
    def get(self, url, headers=None, timeout=None):
        return _Resp(self.endpoints if url.endswith("/endpoints") else self.models)


def _clear_caches():
    providers._model_cat.clear()
    providers._win_cache.clear()


def main() -> int:
    GLM = "z-ai/glm-5.2"   # or_test's model

    # --- 1. model_catalog: effective_window from top_provider, headline from context_length
    print("1. model_catalog — effective_window (top_provider) beside the headline")
    models_reduced = {"data": [
        {"id": GLM, "context_length": 131072, "top_provider": {"context_length": 64000},
         "reasoning": {"supported_efforts": ["high"]}},
        {"id": "full/model", "context_length": 200000, "top_provider": {"context_length": 200000}},
    ]}
    P = providers.Provider
    orp = P("or", "api", "openai", GLM, True, "#fff", base_url="https://openrouter.ai/api/v1")
    openai_style.httpx = _Stub(models_reduced)
    cat = openai_style.model_catalog(orp, "k")
    openai_style.httpx = _httpx
    glm = next(m for m in cat if m["id"] == GLM)
    check("headline context_length parsed", glm["context_length"] == 131072)
    check("effective_window = top_provider.context_length", glm["effective_window"] == 64000)

    # --- 2. endpoints_min_window: conservative floor across endpoints --------------
    print("2. endpoints_min_window — MIN context_length across routed providers")
    eps = {"data": {"endpoints": [{"context_length": 64000}, {"context_length": 32000},
                                  {"context_length": 96000}]}}
    openai_style.httpx = _Stub(models_reduced, endpoints=eps)
    mn = openai_style.endpoints_min_window(orp, GLM, "k")
    openai_style.httpx = _httpx
    check("endpoints-min = 32000", mn == 32000)

    # --- 3. window_info: reduced + changed flags ----------------------------------
    print("3. window_info — reduced (eff<headline) + changed (headline!=seeded)")
    secrets.set("or_test", "k")
    providers.update_provider("or_test", context_window=999)     # seeded != headline → changed
    _clear_caches()
    openai_style.httpx = _Stub(models_reduced)
    w = providers.window_info(providers.provider("or_test"))
    openai_style.httpx = _httpx
    check("effective resolved to the routed window (64000)", w["effective"] == 64000)
    check("headline resolved (131072)", w["headline"] == 131072)
    check("reduced flagged (64000 < 131072)", w["reduced"] is True)
    check("changed flagged (seeded 999 != headline 131072)", w["changed"] is True)

    print("   seed == headline → changed clears; reduced persists")
    providers.update_provider("or_test", context_window=131072)
    providers._win_cache.clear()                                  # keep _model_cat; recompute flags
    openai_style.httpx = _Stub(models_reduced)
    w2 = providers.window_info(providers.provider("or_test"))
    openai_style.httpx = _httpx
    check("changed cleared after re-seed", w2["changed"] is False)
    check("reduced still flagged", w2["reduced"] is True)

    # --- 4. endpoints fallback when top_provider is absent inline ------------------
    print("4. window_info — falls back to endpoints-min when no inline top_provider")
    models_noinline = {"data": [{"id": GLM, "context_length": 131072,
                                 "reasoning": {"supported_efforts": ["high"]}}]}
    providers.update_provider("or_test", context_window=131072)
    _clear_caches()
    openai_style.httpx = _Stub(models_noinline, endpoints=eps)
    w3 = providers.window_info(providers.provider("or_test"))
    openai_style.httpx = _httpx
    check("effective = endpoints-min (32000) when top_provider absent", w3["effective"] == 32000)
    check("reduced flagged via endpoints floor", w3["reduced"] is True)

    # --- 5. full-window model → no flags ------------------------------------------
    print("5. window_info — full window (effective == headline) → no flags")
    models_full = {"data": [{"id": GLM, "context_length": 131072,
                             "top_provider": {"context_length": 131072}}]}
    providers.update_provider("or_test", context_window=131072)
    _clear_caches()
    openai_style.httpx = _Stub(models_full)
    w4 = providers.window_info(providers.provider("or_test"))
    openai_style.httpx = _httpx
    check("not reduced (eff == headline)", w4["reduced"] is False)
    check("not changed (seed == headline)", w4["changed"] is False)

    # --- 6. off-OR seat → configured window, no comparison ------------------------
    print("6. off-OR seat — configured window, no headline/flags")
    w5 = providers.window_info(providers.provider("mock"))   # mock: no base_url
    check("off-OR effective = configured window", w5["effective"] == (providers.provider("mock").context_window or 0))
    check("off-OR headline None", w5["headline"] is None)
    check("off-OR no flags", w5["reduced"] is False and w5["changed"] is False)

    secrets.set("or_test", None)
    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 24 (context-window accuracy) checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
