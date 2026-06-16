"""context.py — build_context (+ build_cli_prompt).

A model isn't present between its turns; it only exists when you call it. So when
called on a thread it didn't start, it just needs to perceive the transcript:

- The whole transcript flattens into ONE labeled block, delivered as a single
  `user` message. Other models' turns are NOT mapped to the `assistant` role.
- A system prompt says who it is and that other AI speakers are peers.

**Synthesis-only filter (the hardest correctness property):** every turn with
`meta.is_panelist_raw == true` is excluded from forward context — only the judge
synthesis (`role == "judge"`) of a research round flows forward. Raw panel answers
remain in the transcript (for the UI's "view full" and the record) but never enter
another model's context.
"""

from __future__ import annotations

from . import providers


def room_system(for_speaker: str) -> str:
    others = [k for k in providers.enabled() if k != for_speaker]
    others_str = ", ".join(others) if others else "(none)"
    return (
        f"You are [{for_speaker}] in a multi-model research room.\n"
        "Below is the full conversation, labeled by speaker. [human] is the researcher.\n"
        f"{others_str} are other AI participants — peers, not you.\n"
        f"Read all of it, then respond as yourself ([{for_speaker}]) to the latest "
        "[human] turn.\n"
        "You may agree with, build on, or push back against what other participants said."
    )


def build_context(transcript: list[dict], for_speaker: str, mode: str) -> dict:
    """Return {"system": str, "messages": [{"role": "user", "content": str}]}."""
    included = [t for t in transcript
               if not (t.get("meta") or {}).get("is_panelist_raw")]
    body = "".join(f"[{t['speaker']}]: {t['text']}\n\n" for t in included)
    body += f"Respond as [{for_speaker}]."
    return {
        "system": room_system(for_speaker),
        "messages": [{"role": "user", "content": body}],
    }


def build_cli_prompt(ctx: dict) -> str:
    """A CLI runner takes a prompt string, not a messages array."""
    return f"{ctx['system']}\n\n{ctx['messages'][0]['content']}"
