"""browser_phase29.py — cached-token row in the turn metadata popover (Chromium).

The pill popover (Phase 28) gains a "Cached" row when a turn's usage carries cached input
tokens (a prompt-cache hit). Resolving real cache hits needs a live OR call across turns, so
this injects usage.cached into the turn and checks the popover surfaces it.

Run:  python tests/browser_phase29.py
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
PORT = 8835
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p29browser")


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
        rid = _json("/rooms", "POST", {"title": "cache"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mockthink"], "judge": "mockthink"})

        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("cache")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='cache'")

            page.select_option("#mode", "converse", force=True)
            page.select_option("#addressee", "mockthink")
            page.fill("#input", "a long conversation turn")
            page.click("#send-btn")
            page.wait_for_selector(".turn:not(.human) .model-pill")

            # no cache hit yet → no Cached row
            page.locator(".turn:not(.human) .model-pill").first.hover()
            page.wait_for_selector("#turn-popover:not(.hidden)")
            assert "Cached" not in page.locator("#turn-popover").inner_text(), "no Cached row without a hit"
            print("baseline OK: no Cached row when the turn had no cache hit")

            # inject a cache hit on the turn → the popover surfaces it
            page.evaluate("""() => {
              const t = STATE.turns.find(x => x.role === 'ai');
              t.meta.usage = Object.assign({}, t.meta.usage, { cached: 48000, exact: true });
              render();
            }""")
            page.locator(".turn:not(.human) .model-pill").first.hover()
            page.wait_for_selector("#turn-popover:not(.hidden)")
            txt = page.locator("#turn-popover").inner_text()
            assert "Cached" in txt and "48k" in txt, f"popover should show the cached row: {txt!r}"
            print("cached OK: a cache hit surfaces as 'Cached 48k in' in the popover")

            b.close()
        print("\nPHASE 29 (prompt-cache token row): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
