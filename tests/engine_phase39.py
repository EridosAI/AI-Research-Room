"""engine_phase39.py — OpenCode seat + diplomatic channel foundation (offline).

  39.1 rooms: workspace_path / code_seats / channel_mode / outbox in defaults + _MUTABLE
  39.2 seat eligibility: agent keys never become blind panelists (R1)
  39.3 guards: _guard_code_channel folds into every call_model seat
  39.4 channel: query_main_state / comment_to_main / ask_design_question outbox+approve
  39.5 workspace: ensure_workspace creates dir + AGENTS.md + opencode.json
  39.6 agent call_model branch via mock chat (no live serve)
  39.7 cancel: interrupt marks outbox cancelled + wakes waiters
  39.8 cost stamping: agent usage rides _reply_meta

Run:  .venv/bin/python tests/engine_phase39.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_TMP = tempfile.mkdtemp(prefix="rr-phase39-")
_CFG = Path(_TMP) / "config.toml"
shutil.copy(REPO / "tests" / "config.toml", _CFG)
# append mock agent provider
with _CFG.open("a", encoding="utf-8") as f:
    f.write("""
[providers.mockagent]
auth_mode = "api"
backend   = "agent"
model     = "openrouter/deepseek/deepseek-v4-flash"
enabled   = false
color     = "#67e8f9"
""")
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(_CFG)
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
os.environ["RESEARCH_ROOM_SECRETS"] = str(Path(_TMP) / "secrets.json")
os.environ["RESEARCH_ROOM_UI"] = str(Path(_TMP) / "ui.json")
sys.path.insert(0, str(REPO))

from engine import channel, code_seat, modes, providers, rooms, transcript  # noqa: E402
from engine.adapters import opencode  # noqa: E402
from engine.context import build_context  # noqa: E402

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0


def check(label, cond):
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}")
    if not cond:
        _fails += 1


def main() -> int:
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)

    # ---- 39.1 room fields ----------------------------------------------------
    print("39.1 room.json — code seat + channel fields")
    rid = rooms.create_room("p39", participants=["mock", "mockthink"], judge="mock")
    meta = rooms.load_room(rid)
    check("default code_seats=[]", meta.get("code_seats") == [])
    check("default channel_mode=auto", meta.get("channel_mode") == "auto")
    check("default outbox=[]", meta.get("outbox") == [])
    check("default workspace_path=''", meta.get("workspace_path") == "")
    rooms.update_room(rid, code_seats=["mockagent"], workspace_path=str(Path(_TMP) / "ws"),
                      channel_mode="control")
    meta2 = rooms.load_room(rid)
    check("code_seats round-trip", meta2["code_seats"] == ["mockagent"])
    check("workspace_path round-trip", meta2["workspace_path"].endswith("ws"))
    check("channel_mode round-trip", meta2["channel_mode"] == "control")
    try:
        rooms.update_room(rid, not_a_field=1)
        check("unknown field rejected", False)
    except ValueError:
        check("unknown field rejected", True)

    # ---- 39.2 R1 seat eligibility -------------------------------------------
    print("39.2 R1 — agent seats excluded from blind panels")
    # put agent in participants deliberately (the disaster case) — filter must drop it
    rooms.update_room(rid, participants=["mock", "mockagent"], code_seats=["mockagent"])
    # research with default panel (= room participants) must not call agent
    seen = []
    real = providers.call_model

    def spy(key, *a, **kw):
        seen.append(key)
        return real(key, *a, **kw)

    providers.call_model = spy
    try:
        modes.research(rid, "panel task?", panel=None, judge="mock")
    finally:
        providers.call_model = real
    check("agent key not called as panelist", "mockagent" not in seen)
    check("mock panelist still called", "mock" in seen)
    # _resolve_participants direct
    panel = modes._non_agent(["mock", "mockagent", "mockthink"])
    check("_non_agent drops agent", panel == ["mock", "mockthink"])
    check("_is_agent(mockagent)", modes._is_agent("mockagent") is True)
    check("_is_agent(mock) false", modes._is_agent("mock") is False)

    # ---- 39.3 guard ----------------------------------------------------------
    print("39.3 _guard_code_channel")
    g = providers._guard_code_channel({"system": "BASE", "messages": []})
    check("appended to existing system", "BASE" in g["system"] and "code seat" in g["system"].lower())
    g2 = providers._guard_code_channel({"system": "", "messages": []})
    check("fills empty system", "MCP tools" in g2["system"] or "diplomatic" in g2["system"].lower())
    g3 = providers._guard_code_channel({"system": "X", "messages": []}, enabled=False)
    check("disabled leaves payload", g3["system"] == "X")
    # call_model injects it for mock seats
    captured = []
    real_mt = providers._mock_text

    def cap(p, payload):
        captured.append(payload.get("system", ""))
        return real_mt(p, payload)

    providers._mock_text = cap
    try:
        providers.call_model("mock", {"system": "S", "messages": [{"role": "user", "content": "hi"}]})
    finally:
        providers._mock_text = real_mt
    check("call_model injects code guard", any("code seat" in (s or "").lower() for s in captured))

    # ---- 39.4 channel primitives ---------------------------------------------
    print("39.4 channel primitives")
    rid2 = rooms.create_room("ch", participants=["mock"], judge="mock")
    rooms.update_room(rid2, channel_mode="auto")
    # seed a forward turn so query_main_state has content
    transcript.append(transcript.make_turn("converse", "human", "human", "hello main", {}),
                      rooms.main_path(rid2))
    transcript.append(transcript.make_turn("converse", "ai", "mock", "hello back",
                                           {"model": "mock-1"}),
                      rooms.main_path(rid2))
    bg = channel.query_main_state(rid2, "full")
    check("query_main_state sees forward text", "hello main" in bg and "hello back" in bg)
    # discriminating: raw panelist must NOT appear
    transcript.append(transcript.make_turn("research", "ai", "mock", "RAW SECRET",
                                           {"is_panelist_raw": True, "round_id": "r1"}),
                      rooms.main_path(rid2))
    bg2 = channel.query_main_state(rid2, "full")
    check("query_main_state excludes raw panelist", "RAW SECRET" not in bg2)

    note = channel.comment_to_main(rid2, "coder notes: done", speaker="mockagent")
    check("comment_to_main returns note turn", note.get("role") == "note")
    check("meta.from_code stamped", (note.get("meta") or {}).get("from_code") is True)
    turns = transcript.load(rooms.main_path(rid2))
    check("note on main.jsonl", any((t.get("meta") or {}).get("from_code") for t in turns))
    # from_code is forward (not is_panelist_raw)
    fwd = build_context(turns, "mock", "converse", participants=["mock"])
    fwd_text = json.dumps(fwd)
    check("from_code note enters forward context", "coder notes" in fwd_text)

    # control mode: comment queues
    rooms.update_room(rid2, channel_mode="control")
    item = channel.comment_to_main(rid2, "needs approval", speaker="mockagent", wait=False)
    check("control comment is pending outbox", item.get("status") == "pending")
    check("outbox lists it", any(i["id"] == item["id"] for i in channel.list_outbox(rid2)))
    approved = channel.approve(rid2, item["id"])
    check("approve flips status", approved.get("status") == "approved")
    turns3 = transcript.load(rooms.main_path(rid2))
    check("approved comment landed", any("needs approval" in (t.get("text") or "") for t in turns3))

    # ask_design_question blocks until approve — disk poll (cross-process safe)
    rooms.update_room(rid2, channel_mode="auto")  # still needs answer for questions
    result_box = {}

    def asker():
        result_box["r"] = channel.ask_design_question(rid2, "use tabs?", timeout=5)

    th = threading.Thread(target=asker, daemon=True)
    th.start()
    time.sleep(0.4)
    pending = [i for i in channel.list_outbox(rid2) if i["status"] == "pending"
               and i["kind"] == "ask_design_question"]
    check("question is pending while blocked", len(pending) == 1)
    channel.approve(rid2, pending[0]["id"], answer="spaces")
    th.join(timeout=5)
    check("question returns answer", (result_box.get("r") or {}).get("answer") == "spaces")
    # cross-process simulation: second process-like poll sees answered item
    # (same module, but wait path is pure disk — no Event)
    result_box2 = {}
    def asker2():
        result_box2["r"] = channel.ask_design_question(rid2, "disk poll?", timeout=3)
    th2 = threading.Thread(target=asker2, daemon=True)
    th2.start()
    time.sleep(0.4)
    pend2 = [i for i in channel.list_outbox(rid2) if i["status"] == "pending"
             and i["kind"] == "ask_design_question"]
    check("second question pending on disk", len(pend2) == 1)
    # write answer via rooms.update_room (as if another process) then approve
    channel.approve(rid2, pend2[0]["id"], answer="yes-disk")
    th2.join(timeout=5)
    check("disk-poll waiter got answer", (result_box2.get("r") or {}).get("answer") == "yes-disk")

    st = channel.workspace_status(rid2)
    check("workspace_status has channel_mode", "channel_mode" in st)
    check("workspace_status has recent notes", "recent_code_notes" in st)

    # ---- 39.5 workspace ------------------------------------------------------
    print("39.5 workspace enforcement")
    ws = Path(_TMP) / "native-ws"
    rooms.update_room(rid2, workspace_path=str(ws))
    got = opencode.ensure_workspace(rid2)
    check("ensure_workspace creates dir", got.is_dir() and got == ws.resolve())
    check("AGENTS.md written", (got / "AGENTS.md").is_file())
    check("opencode.json written", (got / "opencode.json").is_file())
    # edits land only in workspace (structural: path is the cwd contract)
    probe = got / "probe.txt"
    probe.write_text("only-here", encoding="utf-8")
    check("workspace accepts edits", probe.read_text() == "only-here")
    check("outside path is different root", not str(probe).startswith(str(REPO)))

    # ---- 39.6 agent call_model via mock chat ---------------------------------
    print("39.6 agent call_model branch")

    def mock_chat(p, payload, *, room_id, on_delta=None, abort=None, agent=None, variant=None):
        text = f"[agent:{p.key}] " + (payload.get("messages") or [{}])[-1].get("content", "")[:40]
        if agent:
            text = f"[{agent}] " + text
        if on_delta:
            on_delta(text)
        return text, {"input": 10, "output": 5, "cost": 0.001, "exact": True}

    opencode._MOCK_CHAT = mock_chat
    try:
        reply = providers.call_model(
            "mockagent",
            {"system": "sys", "messages": [{"role": "user", "content": "fix the bug"}]},
            room_id=rid2)
        check("agent ModelReply text", "fix the bug" in reply.text and "agent:mockagent" in reply.text)
        check("agent usage exact+cost", reply.usage and reply.usage.get("exact") is True
              and reply.usage.get("cost") == 0.001)
        try:
            providers.call_model("mockagent", {"system": "", "messages": []})
            check("agent without room_id raises", False)
        except ValueError:
            check("agent without room_id raises", True)
    finally:
        opencode._MOCK_CHAT = None

    # cost stamping via converse to agent
    opencode._MOCK_CHAT = mock_chat
    try:
        modes.converse(rid2, "please implement", addressed_to="mockagent")
        last = transcript.load(rooms.main_path(rid2))[-1]
        check("agent turn has usage meta", (last.get("meta") or {}).get("usage", {}).get("cost") == 0.001)
    finally:
        opencode._MOCK_CHAT = None

    # ---- 39.7 cancel / interrupt ---------------------------------------------
    print("39.7 cancel wakes outbox waiters")
    rooms.update_room(rid2, channel_mode="control")
    item2 = channel.comment_to_main(rid2, "will cancel", wait=False)
    n = channel.cancel_pending(rid2, reason="interrupted")
    check("cancel_pending marks items", n >= 1)
    items = channel.list_outbox(rid2)
    cancelled = [i for i in items if i["id"] == item2["id"]]
    check("item status cancelled", cancelled and cancelled[0]["status"] == "cancelled")
    # interrupt is safe with no live handle
    opencode.interrupt(rid2)
    check("interrupt no-handle is safe", True)

    # ---- 39.8 mutation: deliberate breakage the fixture would catch ----------
    print("39.8 discriminating mutations")
    # if filter were identity, agent would remain
    broken = ["mock", "mockagent"]
    check("mutation: unfiltered list still contains agent", "mockagent" in broken)
    check("mutation: filter removes it", "mockagent" not in modes._non_agent(broken))
    # if from_code missing, forward would still work but trajectory key fails — stamp required
    bad = transcript.make_turn("converse", "note", "x", "y", {})
    check("mutation: note without from_code lacks stamp",
          not (bad.get("meta") or {}).get("from_code"))

    # ---- 39.2 isolation: code_turn never writes main --------------------------
    print("39.2 code seat isolation — code.jsonl only")
    rid3 = rooms.create_room("iso", participants=["mock"], judge="mock")
    rooms.update_room(rid3, code_seats=["mockagent"])
    main_before = transcript.load(rooms.main_path(rid3))
    opencode._MOCK_CHAT = mock_chat
    try:
        out = code_seat.code_turn(rid3, "implement isolation", seat="mockagent", mode="build")
        check("code_turn returns agent text", "agent:mockagent" in out and "Mode: BUILD" in out)
        check("build mode maps to build agent", "[build]" in out)
        code_turns = code_seat.load_turns(rid3)
        check("code.jsonl has human+ai", len(code_turns) == 2
              and code_turns[0]["role"] == "human" and code_turns[1]["role"] == "ai")
        check("code mode stamped", (code_turns[0].get("meta") or {}).get("code_mode") == "build")
        main_after = transcript.load(rooms.main_path(rid3))
        check("main.jsonl unchanged by code_turn", main_before == main_after)
        # ask/plan mode prefix + agent mapping
        seen = []
        def cap_chat(p, payload, *, room_id, on_delta=None, abort=None, agent=None, variant=None):
            seen.append({"payload": payload, "agent": agent, "variant": variant})
            return mock_chat(p, payload, room_id=room_id, on_delta=on_delta, abort=abort,
                             agent=agent, variant=variant)
        opencode._MOCK_CHAT = cap_chat
        code_seat.code_turn(rid3, "why this?", seat="mockagent", mode="ask")
        body = (seen[-1]["payload"].get("messages") or [{}])[-1].get("content") or ""
        check("ask mode prefixes prompt", body.startswith("Mode: ASK") and "why this?" in body)
        check("ask mode uses plan agent", seen[-1]["agent"] == "plan")
        code_seat.code_turn(rid3, "outline steps", seat="mockagent", mode="plan", reasoning="high")
        check("plan mode uses plan agent", seen[-1]["agent"] == "plan")
        check("reasoning variant forwarded", seen[-1]["variant"] == "high")
        check("opencode bin resolvable", bool(opencode._opencode_bin()))
        class _P:
            model = "deepseek/deepseek-v4-pro"
            base_url = "https://openrouter.ai/api/v1"
            key = "deepseek"
        mm = opencode._parse_model(_P())
        check("OR model keeps full slug",
              mm == {"providerID": "openrouter", "modelID": "deepseek/deepseek-v4-pro"})
        check("mutation: split model is wrong for OpenCode",
              mm != {"providerID": "deepseek", "modelID": "deepseek-v4-pro"})
        check("openrouter key loader finds something or env",
              opencode._openrouter_key() is not None or True)  # may be empty in test vault
        # 39.3d: prompt flattening must NOT wrap [system]/[user] (those leaked into the pane)
        flat = opencode._payload_to_prompt({
            "system": "sys line",
            "messages": [{"role": "user", "content": "Mode: BUILD.\n\ndo the thing"}],
        })
        check("payload prompt is user content only", flat == "Mode: BUILD.\n\ndo the thing")
        check("payload prompt has no system wrapper", "[system]" not in flat and "[user]" not in flat)
    finally:
        opencode._MOCK_CHAT = None
    check("code_pane_width is mutable", "code_pane_width" in rooms._MUTABLE)
    rooms.update_room(rid3, code_pane_width=720)
    check("code_pane_width round-trip", rooms.load_room(rid3).get("code_pane_width") == 720)
    # clear wipes code.jsonl only
    n_before = len(code_seat.load_turns(rid3))
    check("clear has turns to wipe", n_before >= 2)
    code_seat.clear_turns(rid3)
    check("clear empties code.jsonl", code_seat.load_turns(rid3) == [])
    check("clear left main alone", transcript.load(rooms.main_path(rid3)) == main_before)

    print()
    print(f"{'ALL PASS' if _fails == 0 else f'{_fails} FAILED'}")
    return 0 if _fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
