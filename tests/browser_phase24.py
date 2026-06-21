"""browser_phase24.py — context-window accuracy in the UI (real headless Chromium).

  - the ring + Context cell calibrate to the EFFECTIVE routed window (not the headline);
  - a small red dot shows in the popover's Context cell when the window is reduced
    (effective < headline) or changed (headline != seeded), with the numbers in its
    tooltip; absent for a full-window seat.

The effective/headline/flags come from /participants (server-resolved from OR). Resolving
real OR windows needs a key + network, so this test injects the flags into STATE.participants
and re-renders — exercising the UI calibration + dot logic deterministically/offline.

Run:  python tests/browser_phase24.py
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
PORT = 8829
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p24browser")


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
        rid = _json("/rooms", "POST", {"title": "windows"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mockthink", "or_test"], "judge": "mockthink"})

        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("windows")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='windows'")

            # inject a REDUCED window on mockthink; or_test stays full (no flags)
            page.evaluate("""() => {
              const m = STATE.participants.find(x=>x.name==='mockthink');
              m.context_window = 131072; m.effective_window = 64000; m.headline_window = 131072;
              m.window_reduced = true; m.window_changed = false;
              renderModelBar();
            }""")
            # ring + Context calibrate to the EFFECTIVE window (64000), not the headline
            assert page.evaluate("effectiveWindow('mockthink')") == 64000, "ring must calibrate to effective window"

            # --- reduced seat: dot present with the numbers in its tooltip ---
            page.locator('.model-square[data-model="mockthink"]').click()
            page.wait_for_selector("#model-popover:not(.hidden)")
            pop = page.locator("#model-popover")
            assert pop.locator(".win-dot").count() == 1, "reduced seat should show the window dot"
            title = pop.locator(".win-dot").get_attribute("title")
            assert "routed window" in title and "64k" in title and "131k" in title, \
                f"reduced tooltip should carry both numbers: {title!r}"
            assert "/ 64k" in pop.inner_text(), "Context cell should show the effective window (64k)"
            print("reduced OK: ring calibrates to effective; dot + tooltip carry the numbers")

            # --- full-window seat: no dot ---
            page.locator('.model-square[data-model="or_test"]').click()
            page.wait_for_selector("#model-popover:not(.hidden)")
            assert page.locator("#model-popover .win-dot").count() == 0, "full-window seat shows no dot"
            print("full OK: no dot for a non-reduced, unchanged seat")

            # --- changed seat: dot with the 'headline changed' tooltip ---
            page.evaluate("""() => {
              const m = STATE.participants.find(x=>x.name==='mockthink');
              m.context_window = 100000; m.effective_window = 200000; m.headline_window = 200000;
              m.window_reduced = false; m.window_changed = true;
              renderModelBar();
            }""")
            page.locator('.model-square[data-model="mockthink"]').click()
            page.wait_for_selector("#model-popover:not(.hidden)")
            ct = page.locator("#model-popover .win-dot").get_attribute("title")
            assert "headline changed" in ct and "100k" in ct and "200k" in ct, \
                f"changed tooltip should report was/now: {ct!r}"
            print("changed OK: dot reports headline change (was 100k, now 200k)")

            b.close()
        print("\nPHASE 24 (context-window accuracy): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
