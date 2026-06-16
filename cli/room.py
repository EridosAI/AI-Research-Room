"""room.py — CLI smoke test for the engine. Validates orchestration headlessly
before any UI. Not the product.

  room new "<title>"          create a transcript in the vault
  room ask "<question>"       research mode: all enabled models + judge
  room say @grok "<message>"  converse mode, addressed
  room say "<message>"        converse mode, default speaker (last AI)
  room show                   print the transcript
  room who                    list providers + models + key status

Run as `python -m cli.room <cmd>` from the repo root (or via the ./room wrapper).
"""

from __future__ import annotations

import argparse
import sys

from engine import modes, providers, secrets
from engine import transcript as T


def _err(msg: str) -> int:
    print(f"room: {msg}", file=sys.stderr)
    return 2


def cmd_new(args) -> int:
    path = T.new(args.title)
    print(f"created {path}")
    print("(now the active transcript)")
    return 0


def cmd_ask(args) -> int:
    print(f">> research: panel={','.join(providers.enabled())} "
          f"judge={providers.research_judge()} effort={args.effort}", file=sys.stderr)
    synthesis = modes.research(args.question, effort=args.effort)
    print()
    print(synthesis)
    return 0


def cmd_say(args) -> int:
    message = args.message
    addressed_to = None
    if message and message[0].startswith("@"):
        addressed_to = message[0][1:]
        message = message[1:]
    text = " ".join(message).strip()
    if not text:
        return _err('nothing to say (usage: room say [@speaker] "<message>")')
    if addressed_to and addressed_to not in providers.provider_keys():
        return _err(f"unknown speaker '@{addressed_to}' "
                    f"(known: {', '.join(providers.provider_keys())})")

    target = (addressed_to or T.last_ai_speaker(T.current())
              or (providers.enabled() or providers.provider_keys())[0])
    print(f">> converse: @{target}", file=sys.stderr)
    reply = modes.converse(text, addressed_to=addressed_to)
    print()
    print(f"[{target}]: {reply}")
    return 0


def cmd_show(args) -> int:
    path = T.current()
    print(f"# {T.title(path)}\n# {path}\n")
    for t in T.load(path):
        meta = t.get("meta", {})
        tag = t["speaker"]
        if t["role"] == "judge":
            tag += " (judge)"
        elif meta.get("is_panelist_raw"):
            tag += " (panel)"
        if meta.get("addressed_to"):
            tag += f" → {meta['addressed_to']}"
        print(f"[{t['ts']}] [{tag}]")
        print(t["text"])
        print()
    return 0


def cmd_who(args) -> int:
    print("providers (key : auth : backend : model : key/status):")
    for key, p in providers.registry().items():
        if p.auth_mode == "cli":
            keytag = "subscription (cli, no key)"
        else:
            l4 = secrets.last4(key)
            keytag = (f"…{l4}" if l4 and l4 != "set" else ("set" if l4 else "NO KEY"))
        flag = "" if p.enabled else "  [disabled]"
        print(f"  {key:9} : {p.auth_mode:3} : {p.backend:9} : {p.model:18} : {keytag}{flag}")
    print(f"\nresearch_judge: {providers.research_judge()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="room", description="multi-model research room")
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="create a transcript")
    n.add_argument("title")
    n.set_defaults(func=cmd_new)

    a = sub.add_parser("ask", help="research mode: all enabled models + judge")
    a.add_argument("question")
    a.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    a.set_defaults(func=cmd_ask)

    s = sub.add_parser("say", help="converse mode (optionally @speaker)")
    s.add_argument("message", nargs="+")
    s.set_defaults(func=cmd_say)

    sh = sub.add_parser("show", help="print the transcript")
    sh.set_defaults(func=cmd_show)

    w = sub.add_parser("who", help="list providers + models + key status")
    w.set_defaults(func=cmd_who)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        return _err(str(e))


if __name__ == "__main__":
    raise SystemExit(main())
