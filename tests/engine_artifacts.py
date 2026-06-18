"""engine_artifacts.py — Phase 14D gate (markdown artifacts), mock-only.

Scope is deliberately tiny: detect a fenced ```markdown block, save it as a .md
with a collision-safe name, never produce anything but .md.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_TMP = tempfile.mkdtemp(prefix="rr-artifacts-")
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(REPO / "tests" / "config.toml")
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
sys.path.insert(0, str(REPO))

from engine import artifacts, rooms   # noqa: E402

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0


def check(label, cond):
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}")
    if not cond:
        _fails += 1


def main() -> int:
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)
    adir = Path(_TMP) / "artifacts"
    rid = rooms.create_room("Spec Room", participants=["mock"], judge="mock")

    print("1. detection — one rule: a fenced ```markdown block")
    spec = "Here is the spec:\n\n```markdown\n# Title\n- a\n- b\n```\n\ndone."
    blocks = artifacts.extract_blocks(spec)
    check("extracts the markdown block's content", blocks == ["# Title\n- a\n- b"])
    check("no fence → no artifact", artifacts.extract_blocks("just prose, no fence") == [])
    two = "```markdown\nA\n```\nmid\n```markdown\nB\n```"
    check("multiple blocks → multiple artifacts", artifacts.extract_blocks(two) == ["A", "B"])

    print("2. save — collision-safe .md in the artifacts dir")
    p1 = artifacts.save_artifact(rid, blocks[0], str(adir))
    check("writes a .md file", p1 is not None and p1.is_file() and p1.suffix == ".md")
    check("filename keyed on <slug>-<room_id>-<n>", p1.name == f"spec-room-{rid}-1.md")
    check("content is the raw markdown", p1.read_text() == "# Title\n- a\n- b")
    p2 = artifacts.save_artifact(rid, "second", str(adir))
    check("second save doesn't collide (-2)", p2.name == f"spec-room-{rid}-2.md")

    print("3. auto-write + skips")
    paths = artifacts.auto_write(rid, two, str(adir))
    check("auto-write saves every block", len(paths) == 2)
    check("unset dir → skip (None), no error", artifacts.save_artifact(rid, "x", "") is None)
    check("unset dir → auto-write no-op", artifacts.auto_write(rid, spec, None) == [])
    check("empty content → skip", artifacts.save_artifact(rid, "   ", str(adir)) is None)

    print("4. only .md is ever produced")
    check("every file in the artifacts dir is .md",
          all(f.suffix == ".md" for f in adir.iterdir()))

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 14D (artifacts) checks passed\033[0m"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
