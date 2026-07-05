"""route_phase36.py — the streaming-converse SSE endpoint (real server, mock providers).

Phase 36.3. POST /rooms/{id}/run/stream emits `delta`* → terminal `done` (same payload shape
as /run) or `error`; converse-only (other modes 400); a non-streamable (cli) seat produces no
deltas and goes straight to done.

Run:  python tests/route_phase36.py
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PORT = 8842
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/rr-route36")

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0


def check(label, cond):
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}")
    if not cond:
        _fails += 1


def _json(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"Content-Type": "application/json"} if body is not None else {}
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        BASE + path, data=data, headers=hdr, method=method), timeout=20).read() or "{}")


def _stream(path, body):
    """POST and read the whole SSE body → ordered list of (event, data-dict)."""
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    raw = urllib.request.urlopen(req, timeout=30).read().decode()
    events = []
    for block in raw.split("\n\n"):
        ev = dat = None
        for line in block.splitlines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                dat = line[5:].strip()
        if ev:
            events.append((ev, json.loads(dat) if dat else None))
    return events


def wait_up():
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/rooms", timeout=2); return
        except Exception:
            time.sleep(0.2)
    raise SystemExit("server did not start")


def main() -> int:
    shutil.rmtree(HOME, ignore_errors=True)
    (HOME / "vault").mkdir(parents=True)
    shutil.copy(REPO / "tests" / "config.toml", HOME / "config.toml")
    env = {**os.environ,
           "RESEARCH_ROOM_CONFIG": str(HOME / "config.toml"), "RESEARCH_ROOM_HOME": str(HOME),
           "RESEARCH_ROOM_SECRETS": str(HOME / "secrets.json"), "RESEARCH_ROOM_VAULT": str(HOME / "vault"),
           "RESEARCH_ROOM_UI": str(HOME / "ui.json"), "RESEARCH_ROOM_PORT": str(PORT)}
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        a = _json("/rooms", "POST", {"title": "alpha"})["room"]["id"]
        _json(f"/rooms/{a}", "PUT", {"participants": ["mock"], "judge": "mock"})

        # ---- 1. delta* → done ----
        print("1. streaming converse: delta* then a terminal done (payload shape == /run)")
        evs = _stream(f"/rooms/{a}/run/stream", {"mode": "converse", "prompt": "hello there world", "target": "mock"})
        kinds = [e for e, _ in evs]
        check("at least one delta event", kinds.count("delta") >= 1)
        check("exactly one done event, and it is last", kinds[-1] == "done" and kinds.count("done") == 1)
        check("no error events", "error" not in kinds)
        check("all deltas precede done", all(k == "delta" for k in kinds[:-1]))
        done = evs[-1][1]
        check("done carries result + room_id + transcript", set(done) >= {"result", "mode", "room_id", "transcript"})
        check("transcript has the appended human+ai turns", done["transcript"]["turn_count"] >= 2)
        joined = "".join(d["text"] for e, d in evs if e == "delta")
        check("concatenated deltas == the round result", joined.strip() == done["result"])

        # ---- 2. reject non-converse ----
        print("2. non-converse mode → 400 (stream is converse-only)")
        code = None
        try:
            _stream(f"/rooms/{a}/run/stream", {"mode": "fusion", "prompt": "x", "panel": ["mock"], "judge": "mock"})
        except urllib.error.HTTPError as e:
            code = e.code
        check("fusion on the stream route → 400", code == 400)

        # ---- 3. error event on a failing seat ----
        print("3. a failing seat → error event (turn fails cleanly, no crash)")
        b = _json("/rooms", "POST", {"title": "beta"})["room"]["id"]
        _json(f"/rooms/{b}", "PUT", {"participants": ["mockfail"], "judge": "mockfail"})
        evs = _stream(f"/rooms/{b}/run/stream", {"mode": "converse", "prompt": "answer me", "target": "mockfail"})
        kinds = [e for e, _ in evs]
        check("an error event is emitted", "error" in kinds)
        check("error is terminal (no done)", "done" not in kinds and kinds[-1] == "error")
        check("error carries a message", isinstance(evs[-1][1].get("message"), str) and evs[-1][1]["message"])

        # ---- 4. non-streamable (cli) seat → no deltas, straight to done ----
        print("4. non-streamable cli seat → zero deltas, terminal done")
        c = _json("/rooms", "POST", {"title": "gamma"})["room"]["id"]
        _json(f"/rooms/{c}", "PUT", {"participants": ["mock_cli"], "judge": "mock_cli"})
        evs = _stream(f"/rooms/{c}/run/stream", {"mode": "converse", "prompt": "hi cli", "target": "mock_cli"})
        kinds = [e for e, _ in evs]
        check("no delta events for a cli seat", kinds.count("delta") == 0)
        check("still terminates in done", kinds == ["done"])
        check("done transcript has the ai turn", evs[-1][1]["transcript"]["turn_count"] >= 2)

        # ---- 5. after a stream, the room is not stuck 'running' ----
        print("5. round bookkeeping balances (room not stuck running)")
        time.sleep(0.3)
        check("room a is not running after its stream", _json(f"/rooms/{a}").get("running") is False)

        print()
        if _fails:
            print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
        print("\033[32mall Phase 36.3 (streaming SSE route) checks passed\033[0m"); return 0
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    raise SystemExit(main())
