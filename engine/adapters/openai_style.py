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


def chat(provider, key: str | None, payload: dict, max_tokens: int | None = None) -> str:
    if not key:
        raise RuntimeError(f"no API key configured for '{provider.key}'")
    url = f"{provider.base_url}/chat/completions"
    body = {
        "model": provider.model,
        "messages": _messages(payload),
        "max_tokens": max_tokens or settings.CONVERSE_MAX_TOKENS,
    }
    try:
        r = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(redact(f"HTTP {e.response.status_code}: {e.response.text[:400]}", key)) from None
    except httpx.HTTPError as e:
        raise RuntimeError(redact(f"request failed: {e}", key)) from None
    return (data["choices"][0]["message"]["content"] or "").strip()


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
