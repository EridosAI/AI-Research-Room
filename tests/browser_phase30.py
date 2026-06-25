"""browser_phase30.py — round-in-progress signal + absent-panelist rendering (Chromium).

The exact gap from the live report: a backgrounded/long round read as idle when you returned
to the room, and you couldn't tell why a panelist dropped.
  - returning to a room with a round in flight shows an in-room "round is running…" indicator
    (reconstructed from server state), and a sidebar spinner on the running room;
  - it clears when the round finishes and the synthesis appears;
  - a dropped panelist shows in the round as "dropped (not counted): <seat>" with the reason
    on hover.

Uses the sleeping `mockslow` panelist (RR_MOCK_DELAY) to keep a round in flight, and
`mockfail` to force a drop.

Run:  python tests/browser_phase30.py
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
PORT = 8836
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p30browser")
DELAY = 4   # seconds mockslow sleeps — the window to observe "running"


def _json(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"Content-Type": "application/json"} if body is not None else {}
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        BASE + path, data=data, headers=hdr, method=method), timeout=20).read() or "{}")


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
        a = _json("/rooms", "POST", {"title": "alpha"})["room"]["id"]
        _json(f"/rooms/{a}", "PUT", {"participants": ["mockslow", "mockfail"], "judge": "mock"})
        b = _json("/rooms", "POST", {"title": "beta"})["room"]["id"]
        _json(f"/rooms/{b}", "PUT", {"participants": ["mock"], "judge": "mock"})

        with sync_playwright() as p:
            br = p.chromium.launch(); page = br.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='alpha'")

            # fire a slow fusion round, then leave the room while it runs
            page.select_option("#mode", "fusion")
            page.fill("#input", "slow round with a failing panelist")
            page.click("#send-btn")
            page.locator('.room-row:has-text("beta")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='beta'")

            # --- sidebar shows a spinner on the running room (alpha) while we're in beta ---
            page.wait_for_selector('.room-row:has-text("alpha") .room-spin', timeout=8000)
            print("sidebar OK: the running room shows a spinner while you're elsewhere")

            # --- return to alpha → the in-room 'running' indicator appears ---
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='alpha'")
            page.wait_for_function(
                "document.querySelector('#status').textContent.toLowerCase().includes('running')",
                timeout=5000)
            assert page.locator("#status.busy").count() == 1, "the running indicator should show a spinner"
            print("in-room OK: returning to the running room shows 'a round is running…'")

            # --- it resolves: synthesis lands, indicator clears ---
            page.wait_for_selector(".round .synthesis", timeout=30000)
            page.wait_for_function(
                "!document.querySelector('#status').textContent.toLowerCase().includes('running')",
                timeout=10000)
            print("resolve OK: the round finished, the running indicator cleared")

            # --- the dropped panelist is shown with its reason ---
            note = page.locator(".round .absent-note")
            assert note.count() == 1, "a round with a drop should show an absent note"
            assert "mockfail" in note.inner_text(), f"the dropped seat should be named: {note.inner_text()!r}"
            assert (page.locator(".round .absent-seat").first.get_attribute("title") or "").strip(), \
                "the dropped seat should carry its error reason on hover"
            print("absent OK: dropped panelist shown as 'dropped (not counted): mockfail' + reason on hover")

            br.close()
        print("\nPHASE 30 (round-in-progress signal + absent rendering): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
