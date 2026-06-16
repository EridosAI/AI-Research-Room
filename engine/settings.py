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

# Transcript dir = the vault path. Defaults to <repo>/vault for dev; point
# RESEARCH_ROOM_VAULT at your Obsidian vault in real use.
VAULT_DIR = Path(os.environ.get("RESEARCH_ROOM_VAULT", REPO_ROOT / "vault"))
CURRENT_PTR = VAULT_DIR / ".current"   # per-machine active-transcript pointer

# Secrets dir — OUTSIDE the vault and the repo. Never git-tracked.
CONFIG_DIR = Path(os.environ.get("RESEARCH_ROOM_HOME", Path.home() / ".config" / "research-room"))
SECRETS_FILE = Path(os.environ.get("RESEARCH_ROOM_SECRETS", CONFIG_DIR / "secrets.json"))

# Converse chat-completion output cap (well under the non-streaming timeout ceiling).
CONVERSE_MAX_TOKENS = int(os.environ.get("RESEARCH_ROOM_MAX_TOKENS", "8192"))

ANTHROPIC_VERSION = "2023-06-01"


def secrets_outside_vault() -> bool:
    """True iff the secrets file is not inside the vault tree (a hard invariant)."""
    try:
        SECRETS_FILE.resolve().relative_to(VAULT_DIR.resolve())
        return False
    except ValueError:
        return True
