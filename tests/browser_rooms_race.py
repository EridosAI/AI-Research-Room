"""browser_rooms_race.py — the multi-room concurrency gate (real headless Chromium).

The proof the room model holds under the way it's actually used:
  1. fire a SLOW research round in room alpha (panel includes the sleeping
     `mockslow` provider),
  2. switch to room beta WHILE alpha is still running,
  3. do a converse in beta — and confirm it completes while alpha is still in
     flight (true cross-room concurrency, not a blocked queue),
  4. let alpha finish, and assert its synthesis landed in alpha's main.jsonl,
     NEVER rendered into beta, and never leaked a research turn into beta's file,
  5. the background completion surfaces as an unread dot on alpha in the sidebar;
     switching back renders alpha's synthesis and clears the dot.

If only sequential switching were tested, an implicit "current room" in the
server or a render that drops returned turns onto whatever's on screen would
pass silently. This catches it.

Run:  python tests/browser_rooms_race.py   (needs playwright + chromium)
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
PORT = 8813
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p9race")
DELAY = 4   # seconds mockslow sleeps — the concurrency window


def req(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    r = urllib.request.urlopen(
        urllib.request.Request(BASE + path, data=data, headers=headers, method=method), timeout=20)
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
        # Create + configure two rooms via HTTP (empty by default → set rosters).
        alpha = req("/rooms", "POST", {"title": "alpha room"})["room"]["id"]
        req(f"/rooms/{alpha}", "PUT", {"participants": ["mockslow", "mock"], "judge": "mock"})
        beta = req("/rooms", "POST", {"title": "beta room"})["room"]["id"]
        req(f"/rooms/{beta}", "PUT", {"participants": ["mock"], "judge": "mock"})

        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")

            # --- switch to alpha, fire the slow research round ---
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='alpha room'")
            page.select_option("#mode", "fusion", force=True)
            page.fill("#input", "slow round in alpha")
            t0 = time.time()
            page.click("#send-btn")            # fire — do NOT await completion

            # --- switch to beta WHILE alpha runs ---
            page.locator('.room-row:has-text("beta")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='beta room'")
            assert page.locator(".round").count() == 0, "alpha's research round bled into beta's view"
            assert (time.time() - t0) < DELAY, "switch took longer than the slow round — widen DELAY"
            print("switch OK: moved to beta while alpha still running; no alpha turns on screen")

            # --- converse in beta while alpha is still in flight ---
            page.select_option("#mode", "converse", force=True)
            page.select_option("#addressee", "mock")
            page.fill("#input", "quick hello in beta")
            page.click("#send-btn")
            page.wait_for_selector("text=[mock:mock/mock-1]", timeout=15000)
            # at THIS moment alpha must still be running (no judge yet) — proves concurrency
            alpha_mid = req(f"/rooms/{alpha}")["turns"]
            assert not any(t["role"] == "judge" for t in alpha_mid), \
                "alpha already finished — not a real concurrency window (raise DELAY)"
            print("concurrency OK: beta converse completed while alpha's slow round was still in flight")

            # regression: switching BACK INTO a room must not block behind that
            # room's own in-flight round (activate takes the meta lock, not the
            # main lock). This is the reported bug — couldn't return to a room
            # while its model was still thinking.
            t0 = time.time()
            req(f"/rooms/{alpha}/activate", "POST")
            dt = time.time() - t0
            assert not any(t["role"] == "judge" for t in req(f"/rooms/{alpha}")["turns"]), \
                "alpha finished during the activate check — inconclusive (raise DELAY)"
            assert dt < 2.0, f"activate(alpha) blocked behind its own running round ({dt:.1f}s)"
            print(f"switch-back OK: activate(alpha) returned in {dt:.2f}s while its round was still running")

            # --- let alpha finish; verify isolation on disk ---
            deadline = time.time() + 20
            while time.time() < deadline:
                ta = req(f"/rooms/{alpha}")["turns"]
                if any(t["role"] == "judge" for t in ta):
                    break
                time.sleep(0.3)
            ta = req(f"/rooms/{alpha}")["turns"]
            tb = req(f"/rooms/{beta}")["turns"]
            assert any(t["role"] == "judge" for t in ta), "alpha synthesis never landed in alpha"
            assert all(t["mode"] != "research" for t in tb), "a research turn leaked into beta's main.jsonl"
            assert any(t["mode"] == "converse" for t in tb), "beta converse missing from beta"
            print("isolation OK: alpha synthesis in alpha only; beta holds just its converse")

            # --- on screen (beta active): alpha synthesis must NOT be rendered ---
            page.wait_for_timeout(400)
            assert page.locator(".synthesis").count() == 0, "alpha synthesis rendered into beta's view"
            # --- background completion is legible: unread dot on alpha ---
            page.wait_for_selector('.room-row:has-text("alpha") .unread-dot', timeout=6000)
            print("indicator OK: alpha shows an unread dot while beta is on screen")

            # --- switch back to alpha: synthesis renders, dot clears ---
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_selector(".round .synthesis", timeout=10000)
            page.wait_for_timeout(300)
            assert page.locator('.room-row:has-text("alpha") .unread-dot').count() == 0, \
                "unread dot did not clear after viewing alpha"
            print("return OK: switching back to alpha renders its synthesis and clears the dot")
            b.close()
        print("\nMULTI-ROOM CONCURRENCY RACE: ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
