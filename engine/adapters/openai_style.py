"""openai_style.py — OpenAI / xAI / DeepSeek / Kimi.

POST {base_url}/chat/completions, Authorization: Bearer <key>. base_url is used
verbatim (append /chat/completions; never inject /v1, so a base already ending in
/v1 isn't doubled). system folds into the messages array as a leading system role.
Response text at choices[0].message.content.
"""

from __future__ import annotations

import httpx

from .. import settings
from . import TIMEOUT, redact


def _messages(payload: dict) -> list[dict]:
    msgs: list[dict] = []
    if payload.get("system"):
        msgs.append({"role": "system", "content": payload["system"]})
    msgs.extend(payload["messages"])
    return msgs


def _is_openrouter(provider) -> bool:
    return "openrouter.ai" in (provider.base_url or "")


def _extract_reasoning(msg: dict) -> str | None:
    """Pull the visible reasoning from a chat message, across shapes:
    - OpenRouter `reasoning_details` (array of {type, text/summary, …}) — preferred;
      render reasoning.summary + reasoning.text, SKIP reasoning.encrypted (redacted).
    - OpenRouter flat `reasoning` string (fallback).
    - direct providers' `reasoning_content` (DeepSeek/Kimi)."""
    details = msg.get("reasoning_details")
    if isinstance(details, list) and details:
        parts = []
        for d in details:
            if not isinstance(d, dict) or d.get("type") == "reasoning.encrypted":
                continue                                  # encrypted = redacted; skip cleanly
            t = (d.get("text") or d.get("summary") or "").strip()
            if t:
                parts.append(t)
        if parts:
            return "\n\n".join(parts)
    s = (msg.get("reasoning") or msg.get("reasoning_content") or "").strip()
    return s or None


def _openrouter_search(data: dict) -> dict | None:
    """Normalize OpenRouter web-search provenance from the message's `url_citation`
    annotations into the shared {searches, citations} shape. OpenRouter exposes no
    per-query grouping, so all sources land in one (query-less) group."""
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    cites = []
    for ann in msg.get("annotations") or []:
        if ann.get("type") != "url_citation":
            continue
        uc = ann.get("url_citation") or {}
        url = uc.get("url")
        if not url:
            continue
        cites.append({"url": url, "title": uc.get("title") or url,
                      "snippet": (uc.get("content") or "").strip() or None})
    if not cites:
        return None
    return {"searches": [{"sources": cites}], "citations": cites}


# The transcript-context payload (build_context) ends every user message with
# "Respond as [speaker].". Split there: the head (system + whole transcript) is the
# STABLE prefix to cache; the short tail is volatile. Next turn the head grows by
# appending, so the prior head is a byte-prefix → a cache hit on it.
_CACHE_MARK = "\n\nRespond as ["


def _cache_messages(msgs: list[dict], ttl: str | None) -> list[dict]:
    """Mark the stable transcript prefix of the last user message with a cache breakpoint
    (OpenRouter/Anthropic `cache_control`). Splits at _CACHE_MARK so the big transcript head
    is cached and the trailing 'Respond as […]' stays volatile. No marker → unchanged."""
    out = []
    cc = {"type": "ephemeral"}
    if ttl:
        cc["ttl"] = ttl
    for m in msgs:
        c = m.get("content")
        if m.get("role") == "user" and isinstance(c, str) and _CACHE_MARK in c:
            i = c.rfind(_CACHE_MARK)
            head, tail = c[:i + 2], c[i + 2:]          # keep the "\n\n" with the cached head
            out.append({"role": "user", "content": [
                {"type": "text", "text": head, "cache_control": cc},
                {"type": "text", "text": tail}]})
        else:
            out.append(m)
    return out


def chat(provider, key: str | None, payload: dict, max_tokens: int | None = None,
         reasoning: bool = False, web_search: bool = False, reasoning_effort: str | None = None,
         cache: bool = False
         ) -> tuple[str, str | None, dict | None, str | None, dict | None, str | None]:
    """Returns (answer_text, reasoning_or_None, usage_or_None, served_model_or_None,
    search_or_None, finish_reason_or_None). When `reasoning` is on: OpenRouter rows get the
    unified `reasoning: {enabled, effort}` param (OR maps it to each backend incl. Claude's
    adaptive API — fixing the Opus-4.8 budget_tokens trap); direct providers keep the
    DeepSeek `thinking`/`reasoning_effort` switch. Reasoning is captured from
    reasoning_details/reasoning/reasoning_content (see _extract_reasoning). When
    `web_search` is on AND OpenRouter, attach the server-side search tool + normalize
    citations. usage = exact token counts if provided; served_model = response `model`."""
    if not key:
        raise RuntimeError(f"no API key configured for '{provider.key}'")
    url = f"{provider.base_url}/chat/completions"
    body = {
        "model": provider.model,
        "messages": _messages(payload),
        "max_tokens": max_tokens or settings.CONVERSE_MAX_TOKENS,
    }
    if reasoning:
        if _is_openrouter(provider):
            # OR's uniform reasoning param — maps to every backend's native API.
            body["reasoning"] = {"enabled": True}
            if reasoning_effort:
                body["reasoning"]["effort"] = reasoning_effort
        else:
            body["thinking"] = {"type": "enabled"}     # DeepSeek-direct: enable thinking mode
            body["reasoning_effort"] = reasoning_effort or "high"
    if web_search and _is_openrouter(provider):
        # OpenRouter's server-side web search tool. The legacy `:online` suffix and
        # `web` plugin are deprecated; this is the current path. Verify at wire time.
        body.setdefault("tools", []).append({"type": "openrouter:web_search"})
    if _is_openrouter(provider):
        # ask OR to include the authoritative per-request USD cost in usage.cost
        # (reflects the actual provider route; no price table needed our side).
        body["usage"] = {"include": True}
    # Prompt caching: mark the stable transcript prefix so OR/Anthropic serve it from cache.
    # OR-only (cache_control is the Anthropic shape; OR ignores it for non-supporting models).
    use_cache = cache and _is_openrouter(provider)
    if use_cache:
        body["messages"] = _cache_messages(body["messages"], settings.PROMPT_CACHE_TTL)
    hdr = {"Authorization": f"Bearer {key}"}
    try:
        r = httpx.post(url, headers=hdr, json=body, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as e:
        # caching must NEVER break a turn: if the cached shape is rejected, retry once
        # plain (without cache_control). Any other 4xx/5xx propagates as before.
        if use_cache and e.response.status_code == 400:
            body["messages"] = _messages(payload)
            try:
                r = httpx.post(url, headers=hdr, json=body, timeout=TIMEOUT)
                r.raise_for_status()
                data = r.json()
            except httpx.HTTPError as e2:
                raise RuntimeError(redact(f"request failed: {e2}", key)) from None
        else:
            raise RuntimeError(redact(f"HTTP {e.response.status_code}: {e.response.text[:400]}", key)) from None
    except httpx.HTTPError as e:
        raise RuntimeError(redact(f"request failed: {e}", key)) from None
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    text = (msg.get("content") or "").strip()
    finish = choice.get("finish_reason") or None   # openai vocab: stop | length | tool_calls | content_filter
    rc = _extract_reasoning(msg) if reasoning else None
    u = data.get("usage") or {}
    usage = None
    if u:
        usage = {"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0)}
        if u.get("cost") is not None:                  # OpenRouter's authoritative USD cost
            usage["cost"] = u["cost"]
        # how much the model ACTUALLY thought — the real signal vs the requested effort
        # (counted within completion_tokens). 0/absent ⇒ it didn't reason this turn.
        ctd = u.get("completion_tokens_details") or {}
        if ctd.get("reasoning_tokens") is not None:
            usage["reasoning"] = ctd["reasoning_tokens"]
        # prompt-cache hit: how many input tokens were served from cache (~10% cost) —
        # the visible proof the stable transcript prefix didn't re-prefill.
        ptd = u.get("prompt_tokens_details") or {}
        if ptd.get("cached_tokens") is not None:
            usage["cached"] = ptd["cached_tokens"]
    search = (_openrouter_search(data) if web_search and _is_openrouter(provider) else None)
    return text, rc, usage, (data.get("model") or None), search, finish


# OpenRouter's effort vocabulary (none < low < medium < high < xhigh), ascending —
# the fallback ladder for reasoning-capable models that DON'T enumerate efforts.
_OR_LADDER = ["none", "low", "medium", "high", "xhigh"]


def _parse_effort_catalog(data: dict) -> dict:
    """From a /models payload → {model_id: [supported_efforts ASCENDING]} for
    reasoning-capable models. A model counts as reasoning-capable if it has a
    `reasoning` object OR `supported_parameters` includes "reasoning". Then:
      - `reasoning.supported_efforts` is a non-empty list → that list, REVERSED
        (OR returns highest-first; the UI reads left = less);
      - efforts null/absent but reasoning is supported → OR's ladder (the
        adaptive case — e.g. Claude returns `reasoning: {"mandatory": false}`
        with no efforts; it still accepts effort values, so offer the ladder);
      - not reasoning-capable at all → omitted (no selector)."""
    out: dict[str, list] = {}
    items = data.get("data", data if isinstance(data, list) else [])
    for m in items:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        rinfo = m.get("reasoning")
        params = m.get("supported_parameters")
        reasoning_capable = isinstance(rinfo, dict) or (
            isinstance(params, list) and "reasoning" in params)
        if not reasoning_capable:
            continue
        effs = rinfo.get("supported_efforts") if isinstance(rinfo, dict) else None
        if isinstance(effs, list) and effs:
            out[m["id"]] = list(reversed(effs))      # enumerated → ascending
        else:
            out[m["id"]] = list(_OR_LADDER)          # reasoning-capable but unenumerated
    return out


def reasoning_catalog(provider, key: str | None) -> dict:
    """GET {base}/models → {model_id: ascending efforts} (best-effort; caller caches)."""
    if not key:
        raise RuntimeError("no API key configured")
    r = httpx.get(f"{provider.base_url}/models",
                  headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT)
    r.raise_for_status()
    return _parse_effort_catalog(r.json())


def _top_provider_context(m: dict) -> int:
    cl = (m.get("top_provider") or {}).get("context_length")
    return int(cl) if cl else 0


def _model_context_length(m: dict) -> int:
    """The HEADLINE window: the model object's `context_length`, falling back to the
    default route's window when the headline is absent."""
    cl = m.get("context_length") or _top_provider_context(m)
    return int(cl) if cl else 0


def model_catalog(provider, key: str | None) -> list[dict]:
    """GET {base}/models → a list of {id, context_length, effective_window, reasoning,
    supported_efforts} for the add-a-model dropdown + the context gauge. `context_length`
    is the HEADLINE window; `effective_window` is the default route's window
    (`top_provider.context_length`) — often equal, but smaller on multi-provider
    open-weight models (Phase 24). Sorted by id; reasoning/efforts come from the same
    parse as the effort selector, so a picked row seeds consistently with its popover."""
    if not key:
        raise RuntimeError("no API key configured")
    r = httpx.get(f"{provider.base_url}/models",
                  headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    eff = _parse_effort_catalog(data)
    items = data.get("data", data if isinstance(data, list) else [])
    out = []
    for m in items:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        out.append({
            "id": m["id"],
            "context_length": _model_context_length(m),       # headline
            "effective_window": _top_provider_context(m),     # default route (0 = unknown inline)
            "reasoning": m["id"] in eff,
            "supported_efforts": eff.get(m["id"]),
        })
    out.sort(key=lambda d: d["id"])
    return out


def endpoints_min_window(provider, model: str, key: str | None) -> int:
    """GET {base}/models/{author}/{slug}/endpoints → the MIN context_length across the
    providers OR would route to (the conservative floor) — used only when the inline
    `top_provider.context_length` is absent. 0 when unknown/unavailable."""
    if not key:
        raise RuntimeError("no API key configured")
    r = httpx.get(f"{provider.base_url}/models/{model}/endpoints",
                  headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    eps = ((data.get("data") or {}).get("endpoints")) or []
    wins = [e.get("context_length") for e in eps if isinstance(e, dict) and e.get("context_length")]
    return int(min(wins)) if wins else 0


def list_models(provider, key: str | None) -> list[str]:
    """Best-effort model discovery. The /models path isn't uniform (deepseek's base
    has no /v1, others do), so try {base}/models then {base}/v1/models. If both
    miss, raise — the UI falls back to a typed model id."""
    if not key:
        raise RuntimeError("no API key configured")
    headers = {"Authorization": f"Bearer {key}"}
    errors = []
    for url in (f"{provider.base_url}/models", f"{provider.base_url}/v1/models"):
        try:
            r = httpx.get(url, headers=headers, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as e:
            errors.append(redact(f"{url}: {e}", key))
            continue
        items = data.get("data", data if isinstance(data, list) else [])
        ids = sorted(m["id"] for m in items if isinstance(m, dict) and m.get("id"))
        if ids:
            return ids
    raise RuntimeError("model discovery failed (enter a model id manually): " + " | ".join(errors))
