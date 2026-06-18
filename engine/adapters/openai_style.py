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


def chat(provider, key: str | None, payload: dict, max_tokens: int | None = None,
         reasoning: bool = False) -> tuple[str, str | None, dict | None]:
    """Returns (answer_text, reasoning_or_None, usage_or_None). When `reasoning` is
    on, enable the model's thinking mode (DeepSeek's documented switch) and capture
    `message.reasoning_content` if present — provider-agnostic, so it also picks up
    Kimi or any future OpenAI-shaped reasoner that exposes the field. usage is the
    exact prompt/completion token counts from the response, if provided."""
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
    try:
        r = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(redact(f"HTTP {e.response.status_code}: {e.response.text[:400]}", key)) from None
    except httpx.HTTPError as e:
        raise RuntimeError(redact(f"request failed: {e}", key)) from None
    msg = data["choices"][0]["message"]
    text = (msg.get("content") or "").strip()
    rc = (msg.get("reasoning_content") or "").strip() if reasoning else ""
    u = data.get("usage") or {}
    usage = ({"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0)}
             if u else None)
    return text, (rc or None), usage


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
