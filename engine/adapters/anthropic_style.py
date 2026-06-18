"""anthropic_style.py — Claude. THE divergent adapter; treat as the risky one.

Differs from openai_style in three ways that are easy to get silently wrong:
  - `system` is a TOP-LEVEL param, not a message in the array.
  - `max_tokens` is REQUIRED (set generous — judge syntheses run long).
  - the response is content BLOCKS; text lives at content[*].text, not
    choices[0].message.content. We join all text blocks (≥1).

POST {base_url}/v1/messages with x-api-key + anthropic-version. base_url has no
/v1 (config), so the adapter appends /v1/messages and /v1/models itself.
"""

from __future__ import annotations

import httpx

from .. import settings
from . import TIMEOUT, redact


def chat(provider, key: str | None, payload: dict, max_tokens: int | None = None,
         reasoning: bool = False) -> tuple[str, str | None, dict | None]:
    """Returns (answer_text, reasoning_or_None, usage_or_None). When `reasoning` is
    on, request SUMMARIZED thinking (Opus 4.8 omits thinking by default; do NOT send
    budget_tokens — it 400s on the adaptive-thinking model) and capture the thinking
    blocks' text. Reasoning is a summary, not the raw stream. usage is the exact
    input/output token counts from the response, if provided."""
    if not key:
        raise RuntimeError(f"no API key configured for '{provider.key}'")
    body = {
        "model": provider.model,
        "max_tokens": max_tokens or settings.CONVERSE_MAX_TOKENS,   # required
        "messages": payload["messages"],
    }
    if payload.get("system"):
        body["system"] = payload["system"]                          # top-level
    if reasoning:
        # adaptive + summarized: readable reasoning without a token budget.
        body["thinking"] = {"type": "adaptive", "display": "summarized"}
    url = f"{provider.base_url}/v1/messages"
    headers = {"x-api-key": key, "anthropic-version": settings.ANTHROPIC_VERSION}
    try:
        r = httpx.post(url, headers=headers, json=body, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(redact(f"HTTP {e.response.status_code}: {e.response.text[:400]}", key)) from None
    except httpx.HTTPError as e:
        raise RuntimeError(redact(f"request failed: {e}", key)) from None
    # content blocks → join every text block (the single most likely silent bug
    # is grabbing only content[0] when a thinking/other block precedes the text)
    blocks = data.get("content", [])
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
    rc = None
    if reasoning:
        # thinking blocks carry their text in `thinking` (fallback `text`)
        rc = "".join(b.get("thinking", "") or b.get("text", "")
                     for b in blocks if b.get("type") == "thinking").strip() or None
    u = data.get("usage") or {}
    usage = ({"input": u.get("input_tokens", 0), "output": u.get("output_tokens", 0)}
             if u else None)
    return text, rc, usage


def list_models(provider, key: str | None) -> list[str]:
    if not key:
        raise RuntimeError("no API key configured")
    url = f"{provider.base_url}/v1/models"
    headers = {"x-api-key": key, "anthropic-version": settings.ANTHROPIC_VERSION}
    try:
        r = httpx.get(url, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        raise RuntimeError(redact(f"model discovery failed (enter a model id manually): {e}", key)) from None
    return sorted(m["id"] for m in data.get("data", []) if m.get("id"))
