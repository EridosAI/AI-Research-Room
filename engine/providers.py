"""providers.py — the provider registry + call_model dispatch.

Loads the NON-secret registry from config.toml (base_urls, models, auth_mode,
enabled, colour). Keys come from secrets.py, never from here. The registry is
user-extensible: the presets in config.toml are not a hardcoded enum.

`call_model` (Phase 2) is the single interface over every backend and both auth
modes (api → HTTP adapter with a key; cli → shell out to a runner, no key).
"""

from __future__ import annotations

import subprocess
import tempfile
import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import secrets, settings
from .adapters import anthropic_style, openai_style
# opencode imported lazily inside call_model (agent backend) to avoid import cost

DEFAULT_JUDGE = "claude"

# Connection-test output budget. Must clear reasoning models' minimum: GPT-5.x
# (and others) route to a Responses API where `max_tokens`→`max_output_tokens` and
# hidden reasoning tokens come out of that budget, so the API floors it at 16. A
# 1-token ping 400s ("integer_below_min_value"). 32 = comfortably above the floor,
# still a cheap ping (the test only checks the call succeeds, not the content).
TEST_MAX_TOKENS = 32


class RunnerUnavailable(Exception):
    """A cli provider was asked to run but its runner/CLI isn't available."""


@dataclass(frozen=True)
class Provider:
    key: str
    auth_mode: str           # "api" | "cli"
    backend: str             # "anthropic" | "openai" | "cli"
    model: str
    enabled: bool
    color: str
    base_url: str | None = None      # api providers
    runner: str | None = None        # cli providers: research panelist runner
    converse_runner: str | None = None  # cli providers: converse-turn runner
    reasoning: bool = False  # opt-in: capture this provider's reasoning (cost/latency)
    web_search: bool = False  # opt-in: attach server-side web search on tools=True calls (bills per search)
    supported_efforts: list | None = None  # optional config override (ascending); else read from OR /models
    context_window: int = 0  # token window for the fill gauge; 0 = unknown (you set it)


@dataclass(frozen=True)
class ModelReply:
    """One model turn's result. `reasoning` is best-effort: present only when the
    provider's reasoning toggle is on AND the backend surfaced it. It is stored on
    the turn's meta (never in `text`), so it never re-enters forward context.
    `usage` is {input, output, exact}: exact from an API usage block, else an
    estimate (cli/mock) — exact=False signals the UI to mark it with a ~.
    `served_model` is what the API REPORTED serving (response.model) — distinct from
    the configured `meta.model`; when they differ, the mismatch is now recorded. It
    rides the turn's meta like reasoning, so it never re-enters forward context."""
    text: str
    reasoning: str | None = None
    reasoning_kind: str | None = None   # "summarized" | "full"
    usage: dict | None = None
    served_model: str | None = None     # API-reported model (response.model); None = unreported (cli)
    search: dict | None = None          # web-search provenance: {"searches": [...], "citations": [...]} or None
    finish_reason: str | None = None    # canonical: stop | length (truncated) | tool_calls | content_filter


# ---- registry load / write-back ---------------------------------------------
_registry: dict[str, Provider] = {}
_research_judge: str = DEFAULT_JUDGE
_raw: dict = {}   # the raw toml dict, kept for mutation + write-back


def _load() -> None:
    global _registry, _research_judge, _raw
    if not settings.CONFIG_TOML.is_file():
        raise FileNotFoundError(f"provider registry not found: {settings.CONFIG_TOML}")
    with settings.CONFIG_TOML.open("rb") as f:
        _raw = tomllib.load(f)
    reg: dict[str, Provider] = {}
    for key, d in _raw.get("providers", {}).items():
        reg[key] = Provider(
            key=key,
            auth_mode=d.get("auth_mode", "api"),
            backend=d.get("backend", "openai"),
            model=d.get("model", ""),
            enabled=bool(d.get("enabled", True)),
            color=d.get("color", "#9aa3b2"),
            base_url=(d.get("base_url") or None),
            runner=d.get("runner"),
            converse_runner=d.get("converse_runner"),
            reasoning=bool(d.get("reasoning", False)),
            web_search=bool(d.get("web_search", False)),
            supported_efforts=(list(d["supported_efforts"])
                               if isinstance(d.get("supported_efforts"), list) else None),
            context_window=int(d.get("context_window", 0) or 0),
        )
    _registry = reg
    _research_judge = _raw.get("research_judge", DEFAULT_JUDGE)


def _toml_scalar(v) -> str:
    if isinstance(v, bool):          # bool before int (bool is a subclass of int)
        return "true" if v else "false"
    if isinstance(v, int):           # emit ints unquoted (e.g. context_window)
        return str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _toml_value(v) -> str:
    """Scalar or a TOML array — lists (e.g. supported_efforts) must round-trip as
    arrays, not be stringified (which would reload as None and drop the override)."""
    if isinstance(v, list):
        return "[" + ", ".join(_toml_scalar(x) for x in v) + "]"
    return _toml_scalar(v)


_TOML_BANNER = (
    "# MACHINE-MANAGED — written by the model-management UI (PUT /providers).\n"
    "# Comments are NOT preserved across UI writes; hand edits may be overwritten.\n"
)


def _dump_toml() -> str:
    """Minimal serializer for our flat registry schema (strings + bools).
    Emits the machine-managed banner so it survives every UI write."""
    lines = [_TOML_BANNER,
             f'research_judge = {_toml_scalar(_raw.get("research_judge", DEFAULT_JUDGE))}', ""]
    for name, d in _raw.get("providers", {}).items():
        lines.append(f"[providers.{name}]")
        for k, v in d.items():
            if v is None:
                continue
            lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")
    return "\n".join(lines)


def _save() -> None:
    settings.CONFIG_TOML.write_text(_dump_toml(), encoding="utf-8")
    _load()


def reload() -> None:
    _load()


# load the registry at import time (Phase 0 Done-when: `import engine.providers`)
_load()


# ---- accessors --------------------------------------------------------------
def registry() -> dict[str, Provider]:
    return dict(_registry)


def provider(key: str) -> Provider:
    if key not in _registry:
        raise ValueError(f"unknown provider '{key}' (known: {', '.join(_registry)})")
    return _registry[key]


def provider_keys() -> list[str]:
    return list(_registry)


def enabled() -> list[str]:
    return [k for k, p in _registry.items() if p.enabled]


def research_judge() -> str:
    return _research_judge


# ---- reasoning-effort metadata (per-model, from OpenRouter's /models) --------
_effort_cat_lock = threading.Lock()
_effort_cat: dict[str, dict] = {}   # base_url -> {model_id: efforts ascending}


def effort_catalog(p: Provider) -> dict:
    """Cached OR /models effort metadata, keyed by base_url. Non-OR → {}. Best-effort:
    an empty/failed fetch isn't cached, so it retries once a key/connection appears."""
    base = p.base_url or ""
    if "openrouter.ai" not in base:
        return {}
    with _effort_cat_lock:
        if base in _effort_cat:
            return _effort_cat[base]
    cat: dict = {}
    try:
        cat = openai_style.reasoning_catalog(p, secrets.get(p.key))
    except Exception:  # noqa: BLE001 — offline / no key → no selector, never a crash
        cat = {}
    if cat:
        with _effort_cat_lock:
            _effort_cat[base] = cat
    return cat


def effort_options(p: Provider) -> list | None:
    """Effort choices for a provider's selector (ASCENDING), or None (no control):
    config `supported_efforts` override → OR /models metadata → None."""
    if p.supported_efforts:
        return list(p.supported_efforts)
    return effort_catalog(p).get(p.model)


# ---- OR model catalog (for the add-a-model dropdown) ------------------------
_model_cat_lock = threading.Lock()
_model_cat: dict[str, list] = {}   # base_url -> [{id, context_length, reasoning, supported_efforts}]


def or_model_catalog() -> list[dict]:
    """The full OpenRouter model list (id + metadata) for the add-a-model dropdown,
    fetched via the first enabled-or-not OR provider that has a key. Cached by
    base_url (best-effort; an empty/failed fetch isn't cached). [] when there's no
    OR row with a key (the UI falls back to a typed model id)."""
    for k, p in _registry.items():
        if "openrouter.ai" not in (p.base_url or ""):
            continue
        key = secrets.get(k)
        if not key:
            continue
        base = p.base_url or ""
        with _model_cat_lock:
            if base in _model_cat:
                return _model_cat[base]
        try:
            cat = openai_style.model_catalog(p, key)
        except Exception:  # noqa: BLE001 — offline / bad key → no dropdown, never a crash
            cat = []
        if cat:
            with _model_cat_lock:
                _model_cat[base] = cat
        return cat
    return []


# ---- effective context window (Phase 24) ------------------------------------
_win_lock = threading.Lock()
_win_cache: dict[tuple, dict] = {}   # (base_url, model) -> {effective, headline}


def _off_or_window(p: Provider) -> dict:
    """Off-OR / no-data fallback: the configured window, nothing to compare against."""
    return {"effective": p.context_window or 0, "headline": None,
            "reduced": False, "changed": False}


def _resolve_or_window(p: Provider, key: str) -> dict | None:
    """{effective, headline} for an OR seat: headline = /models context_length;
    effective = top_provider.context_length, falling back to the endpoints MIN when the
    inline value is absent. None when the model isn't in the catalog."""
    entry = next((m for m in or_model_catalog() if m["id"] == p.model), None)
    if not entry:
        return None
    headline = entry.get("context_length") or 0
    eff = entry.get("effective_window") or 0
    if not eff:
        try:
            eff = openai_style.endpoints_min_window(p, p.model, key)
        except Exception:  # noqa: BLE001 — endpoints unavailable → fall back to headline
            eff = 0
    return {"effective": eff or headline, "headline": headline}


def window_info(p: Provider) -> dict:
    """The context gauge's window facts: {effective, headline, reduced, changed}.
    OR seats resolve the effective routed window (cached) and compare to the headline +
    the seeded config window; off-OR seats use the configured window with no comparison.
      - reduced: effective < headline (the route serves a smaller window than advertised)
      - changed: a fresh headline differs from the seeded config window (re-seed cue)."""
    base = p.base_url or ""
    if "openrouter.ai" not in base:
        return _off_or_window(p)
    key = secrets.get(p.key)
    if not key:
        return _off_or_window(p)
    ck = (base, p.model)
    with _win_lock:
        cached = _win_cache.get(ck)
    if cached is None:
        cached = _resolve_or_window(p, key)
        if cached:
            with _win_lock:
                _win_cache[ck] = cached
    if not cached:
        return _off_or_window(p)
    eff, headline = cached["effective"], cached["headline"]
    return {
        "effective": eff or headline or (p.context_window or 0),
        "headline": headline,
        "reduced": bool(headline and eff and eff < headline),
        "changed": bool(headline and p.context_window and headline != p.context_window),
    }


# ---- mutation (write-back to config.toml) -----------------------------------
def update_provider(name: str, *, base_url: str | None = None, model: str | None = None,
                    enabled: bool | None = None, auth_mode: str | None = None,
                    backend: str | None = None, display_name: str | None = None,
                    reasoning: bool | None = None, web_search: bool | None = None,
                    context_window: int | None = None) -> None:
    if name not in _raw.get("providers", {}):
        raise ValueError(f"unknown provider '{name}'")
    p = _raw["providers"][name]
    if base_url is not None:
        p["base_url"] = base_url.rstrip("/")
    if model is not None:
        p["model"] = model
    if enabled is not None:
        p["enabled"] = bool(enabled)
    if auth_mode is not None:
        p["auth_mode"] = auth_mode
    if backend is not None:
        p["backend"] = backend
    if display_name is not None:
        p["display_name"] = display_name
    if reasoning is not None:
        p["reasoning"] = bool(reasoning)
    if web_search is not None:
        p["web_search"] = bool(web_search)
    if context_window is not None:
        p["context_window"] = int(context_window)
    _save()


def set_judge(name: str) -> None:
    if name not in _raw.get("providers", {}):
        raise ValueError(f"unknown provider '{name}'")
    _raw["research_judge"] = name
    _save()


_PALETTE = ["#d6a667", "#7dd3fc", "#fca5a5", "#c4b5fd", "#5eead4",
            "#f0abfc", "#a3e635", "#fbbf24", "#60a5fa", "#f87171"]


def _auto_color(name: str) -> str:
    return _PALETTE[sum(ord(c) for c in name) % len(_PALETTE)]


def _slug(s: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in s.strip())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "provider"


def create_provider(name: str, base_url: str, model: str = "",
                    auth_mode: str = "api", backend: str = "openai",
                    context_window: int | None = None, reasoning: bool | None = None) -> str:
    """Add an OpenAI-compatible (or other) provider via the UI. Returns its key.
    `context_window`/`reasoning` seed metadata-driven defaults when adding from the OR
    model dropdown (the fill gauge's window + the reasoning toggle)."""
    base = _slug(name)
    key = base
    i = 2
    while key in _raw.get("providers", {}):
        key = f"{base}-{i}"
        i += 1
    row = {
        "display_name": name, "auth_mode": auth_mode, "backend": backend,
        "base_url": (base_url or "").rstrip("/"), "model": model,
        "enabled": True, "color": _auto_color(key),
    }
    if context_window:
        row["context_window"] = int(context_window)
    if reasoning is not None:
        row["reasoning"] = bool(reasoning)
    _raw.setdefault("providers", {})[key] = row
    _save()
    return key


def delete_provider(name: str) -> None:
    if name not in _raw.get("providers", {}):
        raise ValueError(f"unknown provider '{name}'")
    del _raw["providers"][name]
    if _raw.get("research_judge") == name:
        _raw["research_judge"] = next(iter(_raw.get("providers", {})), "")
    _save()
    secrets.set(name, None)   # drop its secret too


# ---- call_model: one interface over every backend + both auth modes ---------
def _mock_text(p: Provider, payload: dict) -> str:
    """Deterministic, no-network answer for orchestration tests."""
    last = payload["messages"][-1]["content"] if payload.get("messages") else ""
    snippet = " ".join(last.split())[:80]
    return f"[mock:{p.key}/{p.model}] {snippet}"


def _mock_stream(text: str, on_delta) -> None:
    """Streaming test double: emit `text` as per-word deltas so the streaming path is
    exercisable offline (mock backend only; cli/mock-cli seats never stream). Chunks
    concatenate back to `text`. on_delta may raise (abort) — propagate it, as a real stream
    would; the caller appends no turn (append is post-return). RR_STREAM_DELAY (seconds/word)
    paces the deltas so the browser gate can observe incremental growth + hit Stop mid-stream."""
    import os
    import time
    delay = float(os.environ.get("RR_STREAM_DELAY", "0") or 0)
    for i, w in enumerate(text.split(" ")):
        if delay and i:
            time.sleep(delay)
        on_delta(w if i == 0 else " " + w)


def _mock_search(p: Provider) -> dict:
    """Deterministic, no-network web-search trace for offline tests. Includes one
    http(s) source and one javascript: URL so the UI's link allowlist is exercised
    (mirrors how the mock honours the reasoning/served-model paths)."""
    sources = [
        {"url": "https://example.com/a", "title": f"{p.key}: Example Source A",
         "snippet": "A deterministic snippet for the sources disclosure."},
        {"url": "javascript:alert(1)", "title": "Unsafe link (must be blocked)"},
    ]
    return {
        "searches": [{"query": f"{p.key} background research", "sources": sources}],
        "citations": [{"url": "https://example.com/a", "title": f"{p.key}: Example Source A",
                       "cited_text": "deterministic snippet"}],
    }


def _estimate_usage(payload: dict, text: str) -> dict:
    """Cheap, tokenizer-agnostic token estimate (~chars/4) for paths with no usage
    block (cli/mock). Marked exact=False so the UI shows it with a ~."""
    pin = len(payload.get("system") or "") + sum(
        len(m.get("content") or "") for m in payload.get("messages", []))
    return {"input": pin // 4, "output": len(text or "") // 4, "exact": False}


def _cli_call(p: Provider, payload: dict, tools: bool, effort: str) -> str:
    """cli path: serialize payload → prompt file → runner → capture. No key.

    Research panelist uses `runner` (agentic web+shell); a converse turn uses
    `converse_runner` (single reply). Contract: exit 127 if the CLI is missing
    (→ RunnerUnavailable), exit 1 / empty output on other failure (→ RuntimeError).
    """
    runner_name = p.runner if tools else (p.converse_runner or p.runner)
    if not runner_name:
        raise RunnerUnavailable(f"no runner configured for '{p.key}'")
    runner = settings.RUNNERS_DIR / runner_name
    if not runner.is_file():
        raise RunnerUnavailable(f"runner not found: {runner}")

    from .context import build_cli_prompt   # lazy: avoid import cycle
    prompt = build_cli_prompt(payload)
    with tempfile.TemporaryDirectory(prefix="room-") as tmp:
        pf, of = Path(tmp) / "prompt.txt", Path(tmp) / "out.txt"
        pf.write_text(prompt, encoding="utf-8")
        proc = subprocess.run(
            ["bash", str(runner), str(pf), str(of), effort],
            capture_output=True, text=True,
        )
        if proc.returncode == 127:
            raise RunnerUnavailable(f"{p.key} CLI not installed (runner exit 127)")
        if proc.returncode != 0 or not of.is_file() or not of.read_text(encoding="utf-8").strip():
            tail = (proc.stderr or proc.stdout or "")[-400:]
            raise RuntimeError(f"{p.key} runner failed (exit {proc.returncode}): {tail}")
        return of.read_text(encoding="utf-8").strip()


# Appended to a seat's system prompt when it has NO active web search this response
# (capability-driven — fires for proxy-Grok and any search-off seat, never when search
# is on). Stops a search-less model dressing stale answers as freshly searched, without
# making it refuse to use its training knowledge.
NO_SEARCH_GUARD = (
    "You have no web search for this response. Answer from your own knowledge. When a "
    "question needs current or real-time information you cannot verify, say so plainly "
    "rather than presenting unverified specifics as if you had searched."
)


def _guard_no_search(payload: dict, searches: bool) -> dict:
    """Return payload with the no-search guard folded into its system prompt when the
    seat won't search this response; unchanged when it will. Returns a COPY (never
    mutates a caller's shared payload — research fans one blind payload to N seats)."""
    if searches:
        return payload
    sys = (payload.get("system") or "").strip()
    sys = f"{sys}\n\n{NO_SEARCH_GUARD}".strip() if sys else NO_SEARCH_GUARD
    return {**payload, "system": sys}


# Artifacts-awareness line (Phase 32.2). Folded into a seat's system prompt — like the
# no-search guard, and for the same reason: it's applied HERE in call_model, the single
# path EVERY seat flows through (panel + judge, blind + transcript), so `room_system`'s
# blind-spots (it skips the judge and blind panelists — both artifact producers) don't
# apply. Present only when the room resolves an artifacts dir; absent otherwise (never
# advertise a save that won't happen). System-slot config, not transcript content — the
# forward-context invariant is untouched (build_context still serializes only turn.text).
ARTIFACTS_GUARD_TMPL = (
    "Artifacts: any fenced ```markdown block you produce is automatically saved as a "
    ".md file to: {dir}. When a spec or document references companion files, use paths "
    "under that directory."
)


def _guard_artifacts(payload: dict, artifacts_dir: str | None) -> dict:
    """Fold the artifacts-awareness line into the system prompt when the room resolves an
    artifacts dir; unchanged otherwise. Returns a COPY (never mutates a shared payload),
    and handles the empty-system case (blind rounds) exactly like _guard_no_search."""
    if not artifacts_dir or not str(artifacts_dir).strip():
        return payload
    line = ARTIFACTS_GUARD_TMPL.format(dir=str(artifacts_dir).strip())
    sys = (payload.get("system") or "").strip()
    sys = f"{sys}\n\n{line}".strip() if sys else line
    return {**payload, "system": sys}


# Phase 39 — code-channel awareness. Folded into EVERY seat (incl. non-agent) so the
# panel/judge know what from_code notes mean. System-slot only; never transcript content.
CODE_CHANNEL_GUARD = (
    "A code seat may be attached to this room. Notes with meta.from_code are comments "
    "from that seat on the work in progress — treat them as deliberate crossings into "
    "the main transcript (they passed outbox/approval). The code seat has MCP tools for "
    "diplomatic crossing (comment_to_main, query_main_state, ask_design_question, "
    "workspace_status, request_compaction); other seats do not call those tools."
)


def _guard_code_channel(payload: dict, enabled: bool = True) -> dict:
    """Fold code-channel awareness into the system prompt. Returns a COPY."""
    if not enabled:
        return payload
    sys = (payload.get("system") or "").strip()
    sys = f"{sys}\n\n{CODE_CHANNEL_GUARD}".strip() if sys else CODE_CHANNEL_GUARD
    return {**payload, "system": sys}


def call_model(provider_key: str, payload: dict, tools: bool = False,
               effort: str = "medium", max_tokens: int | None = None,
               reasoning_effort: str | None = None, cache: bool = False,
               artifacts_dir: str | None = None, on_delta=None,
               room_id: str | None = None, abort=None) -> ModelReply:
    """payload = {"system": str, "messages": [{role, content}]} → ModelReply.

    Reasoning capture is best-effort and gated by the provider's `reasoning`
    toggle: when on, api adapters enable + capture the model's reasoning into
    ModelReply.reasoning; otherwise it's None. cli/mock contribute none (except
    the mock honours the toggle so the capture path is testable offline).

    Web search is attached server-side on tools=True calls when the provider's
    `web_search` toggle is on (anthropic web_search tool / OpenRouter web_search
    server tool); the provider runs the search→answer loop and returns in one call.
    The cli (Grok) path searches via its own agentic runner regardless of the flag.
    With the flag off the api request is byte-identical to a plain chat call.

    backend=="agent" (Phase 39): routes to the OpenCode adapter for one window-mode
    turn. `room_id` is required for agent seats (session/workspace lifecycle).
    """
    p = provider(provider_key)
    do_search = bool(tools and p.web_search)
    # a seat "searches" this response via the api web-search tool OR (cli) its agentic
    # runner on a tools=True call; otherwise it gets the no-search guard.
    searches = do_search or (p.auth_mode == "cli" and tools)
    payload = _guard_no_search(payload, searches)
    payload = _guard_artifacts(payload, artifacts_dir)   # room artifacts dir → awareness line (Phase 32.2)
    payload = _guard_code_channel(payload)               # Phase 39: code-channel awareness
    if p.backend == "agent":
        from .adapters import opencode
        if not room_id:
            raise ValueError("agent backend requires room_id")
        text, usage = opencode.chat(
            p, payload, room_id=room_id, on_delta=on_delta, abort=abort)
        return ModelReply(text, usage=usage or _estimate_usage(payload, text),
                          served_model=p.model, finish_reason="stop")
    if p.backend == "mock":
        text = _mock_text(p, payload)
        if on_delta is not None:
            _mock_stream(text, on_delta)          # streaming test double (per-word deltas)
        rsn = (f"[mock reasoning · {p.key}] step 1 … step 2 … therefore." if p.reasoning else None)
        # mock echoes its configured model as the "served" one — gives the provenance
        # path a value to render/assert offline (mirrors the reasoning toggle).
        return ModelReply(text, rsn, "full" if rsn else None,
                          _estimate_usage(payload, text), served_model=p.model,
                          search=(_mock_search(p) if do_search else None),
                          finish_reason="stop")
    if p.auth_mode == "cli":
        text = _cli_call(p, payload, tools, effort)               # cli surfaces no trace/usage/model
        return ModelReply(text, usage=_estimate_usage(payload, text))   # served/search/finish stay None
    # api
    key = secrets.get(provider_key)
    if p.backend == "anthropic":
        text, reasoning, raw, served, search, finish = anthropic_style.chat(
            p, key, payload, reasoning=p.reasoning, web_search=do_search, max_tokens=max_tokens,
            on_delta=on_delta)
        kind = "summarized" if reasoning else None
    else:
        text, reasoning, raw, served, search, finish = openai_style.chat(
            p, key, payload, reasoning=p.reasoning, web_search=do_search, max_tokens=max_tokens,
            reasoning_effort=reasoning_effort, cache=cache, on_delta=on_delta)
        kind = "full" if reasoning else None
    usage = ({**raw, "exact": True} if raw else _estimate_usage(payload, text))
    return ModelReply(text, reasoning, kind, usage, served_model=served,
                      search=search, finish_reason=finish)


def list_models(provider_key: str) -> list[str]:
    p = provider(provider_key)
    if p.backend == "mock":
        return [p.model]
    if p.auth_mode == "cli":
        raise RuntimeError(f"'{provider_key}' is a cli provider — no model list")
    key = secrets.get(provider_key)
    if p.backend == "anthropic":
        return anthropic_style.list_models(p, key)
    return openai_style.list_models(p, key)


def test_provider(provider_key: str) -> dict:
    """Single-reply connection test → {"ok": bool, "error"?: str}. Uses a small
    reasoning-safe output budget (TEST_MAX_TOKENS), not 1 — a 1-token ping 400s on
    reasoning models (GPT-5.x via OpenRouter/Azure floor max_output_tokens at 16).
    Never raises; adapter errors are already key-redacted."""
    p = provider(provider_key)
    payload = {"system": "", "messages": [{"role": "user", "content": "ping"}]}
    try:
        if p.backend == "mock":
            _mock_text(p, payload)
        elif p.auth_mode == "cli":
            _cli_call(p, payload, tools=False, effort="low")
        else:
            key = secrets.get(provider_key)
            if not key:
                return {"ok": False, "error": "no API key configured"}
            adapter = anthropic_style if p.backend == "anthropic" else openai_style
            adapter.chat(p, key, payload, max_tokens=TEST_MAX_TOKENS)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
