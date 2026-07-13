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


def room_system(for_speaker: str, participants: list[str] | None = None,
                human_label: str = "human") -> str:
    roster = participants if participants is not None else providers.enabled()
    others = [k for k in roster if k != for_speaker]
    others_str = ", ".join(others) if others else "(none)"
    return (
        f"You are [{for_speaker}] in a multi-model research room.\n"
        f"Below is the full conversation, labeled by speaker. [{human_label}] is the researcher.\n"
        f"{others_str} are other AI participants — peers, not you.\n"
        f"Read all of it, then respond as yourself ([{for_speaker}]) to the latest "
        f"[{human_label}] turn — unless the latest turn is from the code seat "
        f"(labeled · code seat / from_code), in which case respond to that message.\n"
        "You may agree with, build on, or push back against what other participants said.\n"
        "\n"
        "Code seat: a separate coding harness may be attached to this room. It works in an "
        "isolated workspace and crosses into this transcript only via approved notes "
        "(from_code). Those notes are deliberate messages into the room — treat them as "
        "addressed to the room (status, findings, handshakes, questions). Acknowledge or "
        "act on them; do not ignore them. You cannot call the code seat's tools; the human "
        "drives the code pane. You may ask the human to relay a request to the code seat."
    )


def forward_turns(transcript: list[dict]) -> list[dict]:
    """The synthesis-only forward view: every turn EXCEPT raw panelist answers.
    This is the single definition of the Phase-1 filter — build_context and the
    margin's background both build on it, so they agree on what flows forward."""
    return [t for t in transcript if not (t.get("meta") or {}).get("is_panelist_raw")]


def format_turns(turns: list[dict], human_label: str = "human") -> str:
    """Flatten turns into one labelled block: `[speaker]: text` per turn. The human
    role is shown as `human_label` (the user's chosen display name) — this is the only
    place the name reaches the model; storage keeps the `human` role untouched.
    Code-seat notes are labeled so main seats can see them as deliberate crossings."""
    def lbl(t: dict) -> str:
        if t.get("speaker") == "human":
            return human_label
        meta = t.get("meta") or {}
        if meta.get("from_code"):
            return f"{t['speaker']} · code seat"
        if meta.get("from_margin"):
            return f"{t['speaker']} · margin"
        return t["speaker"]
    return "".join(f"[{lbl(t)}]: {t['text']}\n\n" for t in turns)


def build_context(transcript: list[dict], for_speaker: str, mode: str,
                  participants: list[str] | None = None, human_label: str = "human") -> dict:
    """Return {"system": str, "messages": [{"role": "user", "content": str}]}."""
    body = format_turns(forward_turns(transcript), human_label)
    body += f"Respond as [{for_speaker}]."
    return {
        "system": room_system(for_speaker, participants, human_label),
        "messages": [{"role": "user", "content": body}],
    }


def build_cli_prompt(ctx: dict) -> str:
    """A CLI runner takes a prompt string, not a messages array."""
    return f"{ctx['system']}\n\n{ctx['messages'][0]['content']}"
