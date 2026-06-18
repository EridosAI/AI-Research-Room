"""browser_rooms_sidebar.py — sidebar, forced-decision, and no-localStorage reload.

Real headless Chromium against the live server (mock fixture). Covers the rest of
the Phase 9 Done-when (the race lives in browser_rooms_race.py):

  - first run with NO rooms shows a clear "create your first room" path, not a
    blank rail;
  - a NEW room forces model selection — research is blocked until a judge is set
    (the forced-decision default finally reaching the UI);
  - choosing the room's models + judge lifts the gate and a round runs;
  - sidebar collapse + width persist SERVER-SIDE: a hard refresh reconstructs the
    sidebar state and the active room's roster from ui.json + room.json, with
    localStorage/sessionStorage empty.

Run:  python tests/browser_rooms_sidebar.py   (needs playwright + chromium)
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
PORT = 8814
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p9side")


def req(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=10).read() or "{}")


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
           "RESEARCH_ROOM_PORT": str(PORT), "RESEARCH_ROOM_UI": str(HOME / "ui.json")}
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()

            # --- 1. first run: empty rail has a clear CTA, not a blank space ---
            page.goto(BASE + "/", wait_until="networkidle")
            assert page.locator(".sidebar-empty").count() == 1, "empty sidebar has no 'create your first room' CTA"
            assert "first room" in page.locator(".sidebar-empty").inner_text().lower()
            assert page.locator("#stream .empty").count() == 1, "empty stream state missing"
            print("empty-state OK: clear 'create your first room' path on first run")

            # --- 2. new room → forced decision (research blocked until judge set) ---
            page.on("dialog", lambda d: d.accept("my room"))
            page.click("#new-room-btn")
            page.wait_for_selector('.room-row:has-text("my room")')
            assert page.locator("#title").inner_text() == "my room"
            page.locator('input[name="mode"][value="research"]').check()
            assert page.locator("#judge-pick").input_value() == "", "new room must not preselect a judge"
            page.fill("#input", "should be blocked")
            page.click("#send-btn")
            page.wait_for_timeout(300)
            assert not page.locator("#banner").is_hidden(), "no gate message when research fired without models/judge"
            rid = req("/rooms")["active"]
            assert req(f"/rooms/{rid}")["turn_count"] == 0, "a research round ran despite no judge — gate failed"
            print("forced-decision OK: empty room blocks research until models + judge chosen")

            # --- 3. choose the room's models + judge → gate lifts, a round runs ---
            page.click("#room-settings-btn")
            page.wait_for_selector("#room-roster")
            for name in ("mock", "mock_cli"):
                page.locator(f'#room-roster input[value="{name}"]').check()
            page.select_option("#room-judge", "mock")
            page.click("#room-settings-save")
            page.wait_for_timeout(200)
            assert page.locator("#judge-pick").input_value() == "mock", "room judge not reflected in composer"
            assert page.locator("#panel-pick input[type=checkbox]").count() == 2, "room roster not in the panel picker"
            page.fill("#input", "now it should run")
            page.click("#send-btn")
            page.wait_for_selector(".round .synthesis", timeout=30000)
            assert page.locator(".round .panel").count() == 2, "configured roster did not drive the round"
            print("gate-lift OK: room models + judge set → research runs with that roster")

            # --- 4. sidebar width + collapse persist server-side; reload restores ---
            # drag the resizer to widen the sidebar
            page.mouse.move(260, 300); page.mouse.down(); page.mouse.move(380, 300); page.mouse.up()
            page.wait_for_timeout(250)
            w = req("/ui")["sidebar_width"]
            assert w > 300, f"resize not persisted to ui.json (got {w})"
            page.click("#sidebar-collapse")
            page.wait_for_timeout(200)
            assert req("/ui")["sidebar_collapsed"] is True, "collapse not persisted to ui.json"

            # localStorage must be empty — state lives on the server, not the browser
            assert page.evaluate("window.localStorage.length") == 0, "localStorage was used (forbidden)"
            assert page.evaluate("window.sessionStorage.length") == 0, "sessionStorage was used (forbidden)"

            page.reload(wait_until="networkidle")
            assert not page.locator("#sidebar-expand").is_hidden(), "collapsed state not restored after reload"
            assert page.locator("#sidebar").evaluate("e => e.style.width") == f"{int(w)}px", \
                "sidebar width not restored from server after reload"
            assert page.locator("#title").inner_text() == "my room", "active room not restored after reload"
            # roster reconstructed from room.json (not browser): expand + check picker
            page.click("#sidebar-expand")
            page.locator('input[name="mode"][value="research"]').check()
            assert page.locator("#panel-pick input[type=checkbox]").count() == 2, "room roster not restored after reload"
            assert page.evaluate("window.localStorage.length") == 0, "localStorage populated after reload"
            print("reload OK: sidebar width/collapse + active room roster restored from server, no browser storage")
            b.close()
        print("\nSIDEBAR + FORCED-DECISION + RELOAD: ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
