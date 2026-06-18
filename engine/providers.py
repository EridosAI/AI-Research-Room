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
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import secrets, settings
from .adapters import anthropic_style, openai_style

DEFAULT_JUDGE = "claude"


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
    context_window: int = 0  # token window for the fill gauge; 0 = unknown (you set it)


@dataclass(frozen=True)
class ModelReply:
    """One model turn's result. `reasoning` is best-effort: present only when the
    provider's reasoning toggle is on AND the backend surfaced it. It is stored on
    the turn's meta (never in `text`), so it never re-enters forward context.
    `usage` is {input, output, exact}: exact from an API usage block, else an
    estimate (cli/mock) — exact=False signals the UI to mark it with a ~."""
    text: str
    reasoning: str | None = None
    reasoning_kind: str | None = None   # "summarized" | "full"
    usage: dict | None = None


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
            lines.append(f"{k} = {_toml_scalar(v)}")
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


# ---- mutation (write-back to config.toml) -----------------------------------
def update_provider(name: str, *, base_url: str | None = None, model: str | None = None,
                    enabled: bool | None = None, auth_mode: str | None = None,
                    backend: str | None = None, display_name: str | None = None,
                    reasoning: bool | None = None, context_window: int | None = None) -> None:
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
                    auth_mode: str = "api", backend: str = "openai") -> str:
    """Add an OpenAI-compatible (or other) provider via the UI. Returns its key."""
    base = _slug(name)
    key = base
    i = 2
    while key in _raw.get("providers", {}):
        key = f"{base}-{i}"
        i += 1
    _raw.setdefault("providers", {})[key] = {
        "display_name": name, "auth_mode": auth_mode, "backend": backend,
        "base_url": (base_url or "").rstrip("/"), "model": model,
        "enabled": True, "color": _auto_color(key),
    }
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


def call_model(provider_key: str, payload: dict, tools: bool = False,
               effort: str = "medium") -> ModelReply:
    """payload = {"system": str, "messages": [{role, content}]} → ModelReply.

    Reasoning capture is best-effort and gated by the provider's `reasoning`
    toggle: when on, api adapters enable + capture the model's reasoning into
    ModelReply.reasoning; otherwise it's None. cli/mock contribute none (except
    the mock honours the toggle so the capture path is testable offline).

    Note: tools=True only actually searches on the cli (Grok) path. On the api
    adapters it's currently a no-op (per-provider web-search tools not yet wired),
    so api panelists answer from parametric knowledge.
    """
    p = provider(provider_key)
    if p.backend == "mock":
        text = _mock_text(p, payload)
        rsn = (f"[mock reasoning · {p.key}] step 1 … step 2 … therefore." if p.reasoning else None)
        return ModelReply(text, rsn, "full" if rsn else None, _estimate_usage(payload, text))
    if p.auth_mode == "cli":
        text = _cli_call(p, payload, tools, effort)               # cli surfaces no trace/usage
        return ModelReply(text, usage=_estimate_usage(payload, text))
    # api
    key = secrets.get(provider_key)
    if p.backend == "anthropic":
        text, reasoning, raw = anthropic_style.chat(p, key, payload, reasoning=p.reasoning)
        kind = "summarized" if reasoning else None
    else:
        text, reasoning, raw = openai_style.chat(p, key, payload, reasoning=p.reasoning)
        kind = "full" if reasoning else None
    usage = ({**raw, "exact": True} if raw else _estimate_usage(payload, text))
    return ModelReply(text, reasoning, kind, usage)


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
    """1-token / single-reply connection test → {"ok": bool, "error"?: str}.
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
            adapter.chat(p, key, payload, max_tokens=1)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
