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


def chat(provider, key: str | None, payload: dict, max_tokens: int | None = None,
         reasoning: bool = False, web_search: bool = False
         ) -> tuple[str, str | None, dict | None, str | None, dict | None, str | None]:
    """Returns (answer_text, reasoning_or_None, usage_or_None, served_model_or_None,
    search_or_None, finish_reason_or_None). When `reasoning` is on, enable the model's thinking mode
    (DeepSeek's documented switch) and capture `message.reasoning_content`. When
    `web_search` is on AND the base_url is OpenRouter, attach OpenRouter's
    `web_search` server tool (it runs the loop server-side) and normalize the
    returned `url_citation` annotations into the search trace. usage is exact token
    counts if provided; served_model is the response's top-level `model`."""
    if not key:
        raise RuntimeError(f"no API key configured for '{provider.key}'")
    url = f"{provider.base_url}/chat/completions"
    body = {
        "model": provider.model,
        "messages": _messages(payload),
        "max_tokens": max_tokens or settings.CONVERSE_MAX_TOKENS,
    }
    if reasoning:
        body["thinking"] = {"type": "enabled"}     # DeepSeek: enable the thinking mode
        body["reasoning_effort"] = "high"
    if web_search and _is_openrouter(provider):
        # OpenRouter's server-side web search tool. The legacy `:online` suffix and
        # `web` plugin are deprecated; this is the current path. Verify at wire time.
        body.setdefault("tools", []).append({"type": "openrouter:web_search"})
    try:
        r = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(redact(f"HTTP {e.response.status_code}: {e.response.text[:400]}", key)) from None
    except httpx.HTTPError as e:
        raise RuntimeError(redact(f"request failed: {e}", key)) from None
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    text = (msg.get("content") or "").strip()
    finish = choice.get("finish_reason") or None   # openai vocab: stop | length | tool_calls | content_filter
    rc = (msg.get("reasoning_content") or "").strip() if reasoning else ""
    u = data.get("usage") or {}
    usage = ({"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0)}
             if u else None)
    search = (_openrouter_search(data) if web_search and _is_openrouter(provider) else None)
    return text, (rc or None), usage, (data.get("model") or None), search, finish


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
