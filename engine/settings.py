"""settings.py — paths and locations. No secrets here.

Hard requirement: the transcript lives in the git-tracked (Obsidian) vault; API
keys never do. So the vault/transcript dir and the secrets dir are deliberately
separate, and secrets sit OUTSIDE the repo entirely.
"""

from __future__ import annotations

import os
from pathlib import Path

# repo root = parent of the engine/ package
REPO_ROOT = Path(__file__).resolve().parents[1]

# Provider registry (NON-secret). Lives in the repo; safe to commit.
CONFIG_TOML = Path(os.environ.get("RESEARCH_ROOM_CONFIG", REPO_ROOT / "config.toml"))

# Runners (research CLI + converse CLI + mocks).
RUNNERS_DIR = REPO_ROOT / "engine" / "runners"

# Judge rubric (reused from the fusion package).
REFS_DIR = REPO_ROOT / "references"

# Vault path. Defaults to <repo>/vault for dev; point RESEARCH_ROOM_VAULT at your
# Obsidian vault in real use.
VAULT_DIR = Path(os.environ.get("RESEARCH_ROOM_VAULT", REPO_ROOT / "vault"))

# Rooms are folders inside the vault (each room = one folder: main.jsonl +
# margin.jsonl + room.json). The rooms dir defaults to the vault path; override
# the vault location via RESEARCH_ROOM_VAULT.
ROOMS_DIR = VAULT_DIR

# Per-machine pointer to the client's *active room id*. This is a UI/CLI
# convenience only — the engine never reads it (no engine-level "current").
CURRENT_PTR = VAULT_DIR / ".current"

# Secrets dir — OUTSIDE the vault and the repo. Never git-tracked.
CONFIG_DIR = Path(os.environ.get("RESEARCH_ROOM_HOME", Path.home() / ".config" / "research-room"))
SECRETS_FILE = Path(os.environ.get("RESEARCH_ROOM_SECRETS", CONFIG_DIR / "secrets.json"))

# App-level UI state (sidebar collapsed/width). Per-machine, NOT secret, and NOT
# per-room (room.json owns per-room splitter width + roster). Stored server-side
# so the web UI keeps the no-browser-storage rule — reload reconstructs from here
# plus room.json, never from localStorage.
UI_FILE = Path(os.environ.get("RESEARCH_ROOM_UI", CONFIG_DIR / "ui.json"))

# Converse chat-completion output cap (well under the non-streaming timeout ceiling).
CONVERSE_MAX_TOKENS = int(os.environ.get("RESEARCH_ROOM_MAX_TOKENS", "8192"))

# Research output cap — far more generous: panelist answers + the judge synthesis run
# long, and agentic web-search models (e.g. GLM via OpenRouter) narrate many searches
# before the answer, so the converse ceiling truncated them. Generous-but-bounded on
# purpose: a ceiling above a model's own max-output 400s on some direct providers, and
# the cap is also the circuit breaker on a runaway agentic loop. Raise per your model
# set via RESEARCH_ROOM_RESEARCH_MAX_TOKENS; a truncation still shows a ⚠ badge.
RESEARCH_MAX_TOKENS = int(os.environ.get("RESEARCH_ROOM_RESEARCH_MAX_TOKENS", "32768"))

ANTHROPIC_VERSION = "2023-06-01"

# Prompt caching (Phase 29). On a transcript-context call (converse / yes-and /
# transcript-panel) the whole conversation is re-sent each turn; caching marks the stable
# transcript prefix so OpenRouter/Anthropic serve it from cache (~10% cost, big latency
# win) instead of re-prefilling. TTL defaults to "1h" — the 5-minute default expires
# between long deep-research turns, so the prefix would never hit. Set "" to use the
# provider default (5m), or "5m"/"1h". A cached request that errors transparently retries
# without caching, so this can never break a turn.
PROMPT_CACHE = os.environ.get("RESEARCH_ROOM_PROMPT_CACHE", "1") not in ("0", "false", "False", "")
PROMPT_CACHE_TTL = os.environ.get("RESEARCH_ROOM_PROMPT_CACHE_TTL", "1h")


def secrets_outside_vault() -> bool:
    """True iff the secrets file is not inside the vault tree (a hard invariant)."""
    try:
        SECRETS_FILE.resolve().relative_to(VAULT_DIR.resolve())
        return False
    except ValueError:
        return True
