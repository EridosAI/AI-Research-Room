"""room.py — CLI smoke test for the engine. Validates orchestration headlessly
before any UI. Not the product.

  room new "<title>"          create a room (folder) in the vault, make it active
  room rooms                  list rooms (newest first); * marks the active one
  room use <room_id>          switch the active room
  room ask "<question>"       research mode in the active room (panel + judge)
  room say @grok "<message>"  converse mode in the active room, addressed
  room say "<message>"        converse mode, default speaker (last AI)
  room show                   print the active room's transcript
  room who                    list providers + models + key status

The "active room" is a CLI-local convenience pointer (settings.CURRENT_PTR holds
a room id); the engine itself is stateless about which room is current — every
engine call here passes an explicit room id.

Run as `python -m cli.room <cmd>` from the repo root (or via the ./room wrapper).
"""

from __future__ import annotations

import argparse
import sys

from engine import modes, providers, rooms, secrets, settings
from engine import transcript as T


def _err(msg: str) -> int:
    print(f"room: {msg}", file=sys.stderr)
    return 2


# ---- CLI-local active-room pointer (not an engine concern) ------------------
def _set_active(room_id: str) -> None:
    settings.ROOMS_DIR.mkdir(parents=True, exist_ok=True)
    settings.CURRENT_PTR.write_text(room_id, encoding="utf-8")


def _active() -> str:
    try:
        room_id = settings.CURRENT_PTR.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        room_id = ""
    if not room_id or not rooms.room_exists(room_id):
        raise FileNotFoundError('no active room — run `room new "<title>"` first')
    return room_id


def cmd_new(args) -> int:
    # Seed the CLI's room with the currently-enabled providers + judge so a
    # `room new` / `room ask` smoke test works immediately. (New rooms in the
    # web UI start empty — a forced decision — per Phase 9.)
    room_id = rooms.create_room(args.title, participants=providers.enabled(),
                                judge=providers.research_judge())
    _set_active(room_id)
    print(f"created room {room_id}")
    print("(now the active room)")
    return 0


def cmd_rooms(args) -> int:
    active = ""
    try:
        active = _active()
    except FileNotFoundError:
        pass
    items = rooms.list_rooms()
    if not items:
        print("(no rooms yet — run `room new \"<title>\"`)")
        return 0
    for m in items:
        mark = "*" if m["id"] == active else " "
        roster = ",".join(m["participants"]) or "(none)"
        judge = m["judge"] or "(none)"
        print(f"{mark} {m['id']:30}  panel={roster}  judge={judge}")
    return 0


def cmd_use(args) -> int:
    if not rooms.room_exists(args.room_id):
        return _err(f"no such room: {args.room_id}")
    _set_active(args.room_id)
    print(f"active room → {args.room_id}")
    return 0


def cmd_ask(args) -> int:
    room_id = _active()
    room = rooms.load_room(room_id)
    print(f">> research [{room_id}]: panel={','.join(room['participants']) or '(none)'} "
          f"judge={room['judge'] or '(none)'} effort={args.effort}", file=sys.stderr)
    synthesis = modes.research(room_id, args.question, effort=args.effort)
    print()
    print(synthesis)
    return 0


def cmd_say(args) -> int:
    room_id = _active()
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

    target = (addressed_to or T.last_ai_speaker(rooms.main_path(room_id))
              or (providers.enabled() or providers.provider_keys())[0])
    print(f">> converse [{room_id}]: @{target}", file=sys.stderr)
    reply = modes.converse(room_id, text, addressed_to=addressed_to)
    print()
    print(f"[{target}]: {reply}")
    return 0


def cmd_show(args) -> int:
    room_id = _active()
    room = rooms.load_room(room_id)
    print(f"# {room['title']}\n# {room_id}\n")
    for t in T.load(rooms.main_path(room_id)):
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

    n = sub.add_parser("new", help="create a room")
    n.add_argument("title")
    n.set_defaults(func=cmd_new)

    r = sub.add_parser("rooms", help="list rooms")
    r.set_defaults(func=cmd_rooms)

    u = sub.add_parser("use", help="switch the active room")
    u.add_argument("room_id")
    u.set_defaults(func=cmd_use)

    a = sub.add_parser("ask", help="research mode: room panel + judge")
    a.add_argument("question")
    a.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    a.set_defaults(func=cmd_ask)

    s = sub.add_parser("say", help="converse mode (optionally @speaker)")
    s.add_argument("message", nargs="+")
    s.set_defaults(func=cmd_say)

    sh = sub.add_parser("show", help="print the active room's transcript")
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
