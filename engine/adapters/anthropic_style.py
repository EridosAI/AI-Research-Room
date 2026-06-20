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


# Claude's server-side web search tool. The dated type string BUMPS over time —
# verify against current docs at wire time (the live probe checks this).
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}


def _anthropic_search(blocks: list[dict]) -> dict | None:
    """Normalize Claude's web-search blocks into the shared {searches, citations}
    shape: queries from `server_tool_use`, results from `web_search_tool_result`,
    in-text citations from text blocks' `citations`."""
    searches: list[dict] = []
    for b in blocks:
        if b.get("type") == "server_tool_use" and b.get("name") == "web_search":
            searches.append({"query": (b.get("input") or {}).get("query"), "sources": []})
        elif b.get("type") == "web_search_tool_result":
            results = b.get("content") or []
            sources = [{"url": r.get("url"), "title": r.get("title") or r.get("url"),
                        "snippet": r.get("page_age")}
                       for r in results if isinstance(r, dict) and r.get("url")]
            if searches and not searches[-1]["sources"]:
                searches[-1]["sources"] = sources        # pair result with its preceding query
            else:
                searches.append({"sources": sources})
    citations: list[dict] = []
    for b in blocks:
        if b.get("type") != "text":
            continue
        for c in b.get("citations") or []:
            if c.get("url"):
                citations.append({"url": c.get("url"), "title": c.get("title") or c.get("url"),
                                  "cited_text": c.get("cited_text")})
    if not searches and not citations:
        return None
    return {"searches": searches, "citations": citations}


# Claude's stop_reason vocabulary → the canonical finish_reason the UI keys off.
_STOP_REASON = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
                "tool_use": "tool_calls", "refusal": "content_filter"}


def chat(provider, key: str | None, payload: dict, max_tokens: int | None = None,
         reasoning: bool = False, web_search: bool = False
         ) -> tuple[str, str | None, dict | None, str | None, dict | None, str | None]:
    """Returns (answer_text, reasoning_or_None, usage_or_None, served_model_or_None,
    search_or_None, finish_reason_or_None). When `reasoning` is on, request SUMMARIZED thinking (Opus 4.8
    omits thinking by default; do NOT send budget_tokens — it 400s on the
    adaptive-thinking model). When `web_search` is on, attach Claude's web_search
    tool (it runs the loop server-side) and normalize its result/citation blocks.
    usage is exact token counts if provided; served_model is the response `model`."""
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
    if web_search:
        body.setdefault("tools", []).append(WEB_SEARCH_TOOL)
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
    search = (_anthropic_search(blocks) if web_search else None)
    sr = data.get("stop_reason")
    finish = _STOP_REASON.get(sr, sr) if sr else None   # normalize to the canonical vocab
    return text, rc, usage, (data.get("model") or None), search, finish


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
