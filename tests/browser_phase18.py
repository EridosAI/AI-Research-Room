"""browser_phase18.py — truncation badge in the turn footer (headless Chromium).

  - a turn whose finish_reason is "length" (truncated) or "tool_calls" (unfinished
    tool round) shows a ⚠ badge in the footer;
  - a clean "stop" (or absent) shows none, and never forces a footer on its own;
  - a normal mock research round shows NO truncation badge (mock finishes "stop").

The badge render logic is verified directly via the global turnFooterParts() (a
crafted finish_reason is the only way to produce truncation offline), plus a DOM
check that a real, clean round carries no badge.

Run:  python tests/browser_phase18.py   (needs playwright + chromium)
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
PORT = 8823
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p18browser")


def _json(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"Content-Type": "application/json"} if body is not None else {}
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        BASE + path, data=data, headers=hdr, method=method), timeout=10).read() or "{}")


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
           "RESEARCH_ROOM_PORT": str(PORT)}
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        rid = _json("/rooms", "POST", {"title": "trunc room"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mock"], "judge": "mock"})

        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("trunc room")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='trunc room'")

            # --- badge render logic, keyed off finish_reason ---
            def has_badge(meta):
                return page.evaluate(
                    "m => { const p = turnFooterParts({meta:m}); "
                    "return !!(p && p.footer.querySelector('.trunc-badge')); }", meta)

            assert has_badge({"finish_reason": "length"}), "length should show a truncation badge"
            assert "truncated" in page.evaluate(
                "truncBadge({finish_reason:'length'}).textContent"), "length badge should read 'truncated'"
            assert has_badge({"finish_reason": "tool_calls"}), "tool_calls should show a badge"
            assert "incomplete" in page.evaluate(
                "truncBadge({finish_reason:'tool_calls'}).textContent"), "tool_calls badge should read 'incomplete'"
            assert not has_badge({"finish_reason": "stop"}), "a clean stop must NOT show a badge"
            # a plain 'stop' has nothing else → must not force a footer at all
            assert page.evaluate("turnFooterParts({meta:{finish_reason:'stop'}}) === null"), \
                "stop alone should not create a footer"
            assert page.evaluate("turnFooterParts({meta:{}}) === null"), "empty meta → no footer"
            print("badge OK: length→truncated, tool_calls→incomplete, stop/empty→none (no forced footer)")

            # --- a real, clean mock research round shows NO truncation badge ---
            page.select_option("#mode", "fusion", force=True)
            page.fill("#input", "a thorough question")
            page.click("#send-btn")
            page.wait_for_selector(".round .synthesis", timeout=30000)
            assert page.locator(".round .trunc-badge").count() == 0, \
                "a clean mock round should carry no truncation badge"
            print("DOM OK: clean research round renders without any truncation badge")
            b.close()
        print("\nPHASE 18 (research token ceiling + truncation badge): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
