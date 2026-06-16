"""secrets.py — API keys, stored OUTSIDE the vault and the repo.

File: ~/.config/research-room/secrets.json, created with mode 600. Keys are
write-only over the API (callers only ever see last-4). This module never logs
key values.
"""

from __future__ import annotations

import json
import os

from . import settings


def _load() -> dict:
    if settings.SECRETS_FILE.is_file():
        try:
            return json.loads(settings.SECRETS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(data: dict) -> None:
    settings.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # write then chmod 600 (owner read/write only)
    settings.SECRETS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(settings.SECRETS_FILE, 0o600)
    except OSError:
        pass


def get(provider: str) -> str | None:
    return _load().get(provider) or None


def set(provider: str, key: str | None) -> None:  # noqa: A003 — deliberate verb
    data = _load()
    if key:
        data[provider] = key
    else:
        data.pop(provider, None)
    _save(data)


def last4(provider: str) -> str | None:
    k = get(provider)
    if not k:
        return None
    return k[-4:] if len(k) >= 4 else "set"


def has_key(provider: str) -> bool:
    return get(provider) is not None
