"""HTTP adapters: openai_style + anthropic_style.

Both consume the canonical payload {"system": str, "messages": [{role, content}]}
but map it to each provider's wire shape. Shared here: a generous timeout (judge
syntheses run long) and key redaction so a key can never reach a log or error body.
"""

from __future__ import annotations

import httpx

# generous timeouts — a slow model must raise cleanly on timeout, never hang
# (Phase 3's graceful degradation depends on a failed call raising, not blocking).
TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)


def redact(text: str, key: str | None) -> str:
    if key and len(key) > 4:
        return text.replace(key, "****" + key[-4:])
    return text
