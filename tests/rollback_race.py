"""rollback_race.py — rollback can't truncate a round mid-append (HTTP, no browser).

The one nasty edge: if /rollback fired while a round was halfway through appending its
turns, it would truncate a partial round and the still-running round would then append
its remaining turns ORPHANED (a judge turn with no human head). The per-room lock must
prevent this — both /run and /rollback take the SAME lock, and run_mode appends every
turn synchronously inside it.

Proof: start a SLOW fusion round (panel = sleeping `mockslow`) in a thread; the moment its
human turn is on disk (round mid-flight, lock held), fire /rollback from the main thread.
If the lock holds, rollback BLOCKS until the round fully completes, then removes it whole —
so rolledback.jsonl contains the COMPLETE round (human + panel + judge) and main.jsonl is
empty. If the lock were broken, rollback would remove only the human turn and the panel +
judge would land orphaned in main.

Run:  python tests/rollback_race.py
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PORT = 8833
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p27race")
DELAY = 3   # seconds mockslow sleeps — the window we fire rollback into

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0


def check(label, cond):
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}")
    if not cond:
        _fails += 1


def req(path, method="GET", body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"Content-Type": "application/json"} if body is not None else {}
    r = urllib.request.urlopen(urllib.request.Request(BASE + path, data=data, headers=hdr, method=method), timeout=timeout)
    return json.loads(r.read() or "{}")


def wait_up():
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/rooms", timeout=2); return
        except Exception:
            time.sleep(0.2)
    raise SystemExit("server did not start")


def main():
    shutil.rmtree(HOME, ignore_errors=True)
    (HOME / "vault").mkdir(parents=True)
    shutil.copy(REPO / "tests" / "config.toml", HOME / "config.toml")
    env = {**os.environ,
           "RESEARCH_ROOM_CONFIG": str(HOME / "config.toml"), "RESEARCH_ROOM_HOME": str(HOME),
           "RESEARCH_ROOM_SECRETS": str(HOME / "secrets.json"), "RESEARCH_ROOM_VAULT": str(HOME / "vault"),
           "RESEARCH_ROOM_PORT": str(PORT), "RR_MOCK_DELAY": str(DELAY)}
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        rid = req("/rooms", "POST", {"title": "race"})["room"]["id"]
        req(f"/rooms/{rid}", "PUT", {"participants": ["mockslow"], "judge": "mock"})

        # --- start a slow fusion round in a thread (holds the room lock ~DELAY s) ---
        run_result = {}

        def run_round():
            try:
                run_result["ok"] = req(f"/rooms/{rid}/run", "POST",
                                       {"mode": "fusion", "prompt": "slow round to undo"})
            except Exception as e:  # noqa: BLE001
                run_result["err"] = str(e)

        t = threading.Thread(target=run_round); t.start()

        # wait until the round's human turn is on disk → round is mid-flight, lock held
        deadline = time.time() + 10
        while time.time() < deadline:
            if len(req(f"/rooms/{rid}").get("turns", [])) >= 1:
                break
            time.sleep(0.05)
        mid = req(f"/rooms/{rid}")["turns"]
        check("round is mid-flight: human turn written, panel/judge not yet",
              len(mid) == 1 and mid[0]["role"] == "human")

        # --- fire rollback WHILE the panel sleeps; it must block on the lock ---
        t0 = time.time()
        rb = req(f"/rooms/{rid}/rollback", "POST")
        waited = time.time() - t0
        t.join(timeout=20)

        check("run round completed without error", "ok" in run_result and "err" not in run_result)
        check("rollback BLOCKED on the lock until the round finished (did not return instantly)",
              waited > 0.8)

        # --- the decisive check: a COMPLETE round was removed, nothing orphaned ---
        main_turns = req(f"/rooms/{rid}")["turns"]
        rolled = [json.loads(l) for l in (HOME / "vault" / rid / "rolledback.jsonl").read_text().splitlines() if l.strip()]
        check("main.jsonl is empty — the whole round was removed", len(main_turns) == 0)
        check("rollback removed exactly 3 turns (human + panel + judge)", rb.get("removed") == 3)
        check("rolledback.jsonl holds the COMPLETE round (human, ai-raw panel, judge), not a partial",
              [t_["role"] for t_ in rolled] == ["human", "ai", "judge"])
        check("the removed panel turn was the slow one (proves it ran before rollback)",
              any((t_.get("meta") or {}).get("is_panelist_raw") and t_["speaker"] == "mockslow" for t_ in rolled))

        print()
        if _fails:
            print(f"\033[31m{_fails} check(s) failed\033[0m"); sys.exit(1)
        print("\033[32mrollback-race: the room lock serializes round-append vs rollback — no mid-round truncation\033[0m")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
