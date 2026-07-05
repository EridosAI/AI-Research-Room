"""browser_phase26.py — mapping, yes-and, panel context toggle, judge labels (Chromium).

  - the selector lists Mapping + Yes-and; params reveal contextually (yes-and's ordered
    pair; the panel "sees conversation" toggle on the panel modes);
  - mapping renders a round + a judge turn labelled "map";
  - yes-and renders two stacked answers (A then B) and dispatches through /run;
  - judge turns show a mode-aware label (map / divergence) — not a generic "synthesis".

Offline (mock seats) — zero token cost.

Run:  python tests/browser_phase26.py
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
PORT = 8831
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p26browser")


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
        rid = _json("/rooms", "POST", {"title": "modes2"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mock", "mockthink"], "judge": "mock"})

        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            posts = []
            page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("modes2")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='modes2'")

            # --- selector lists the five modes ---
            opts = page.eval_on_selector_all("#mode option", "els => els.map(e => e.value)")
            assert opts == ["converse", "fusion", "mapping", "side_by_side", "yes_and"], f"mode options: {opts}"
            print("selector OK: lists converse · fusion · mapping · side-by-side · yes-and")

            # --- contextual reveal: mapping shares panel params (+ context toggle); yes-and shows the ordered pair ---
            def vis(s): return page.locator(s).is_visible()
            page.select_option("#mode", "mapping", force=True)
            assert vis("#research-opts") and page.locator("#panel-context").count() == 1, \
                "mapping shows the panel params + the 'panel sees conversation' toggle"
            page.select_option("#mode", "yes_and", force=True)
            assert vis("#yesand-opts") and not vis("#research-opts"), "yes-and shows its own params"
            assert page.locator("#ya-a").count() == 1 and page.locator("#ya-b").count() == 1, \
                "yes-and shows the ordered pair (A → B)"
            print("reveal OK: mapping shares panel params + context toggle; yes-and shows A→B")

            # --- mapping run → judge turn labelled 'map' ---
            page.select_option("#mode", "mapping", force=True)
            page.fill("#input", "Best caching strategy?")
            posts.clear()
            page.click("#send-btn")
            page.wait_for_selector(".round .synthesis", timeout=30000)
            assert any(u.endswith(f"/rooms/{rid}/run") for u in posts), "mapping dispatches through /run"
            who = page.locator(".round .synthesis .who").inner_text()
            assert "map" in who and "synthesis" not in who, f"judge turn should be labelled 'map': {who!r}"
            print("mapping OK: renders a round; judge turn labelled 'map' (not synthesis)")

            # --- yes-and run → two stacked answers (A then B) via /run ---
            page.select_option("#mode", "yes_and", force=True)
            page.select_option("#ya-a", "mock")
            page.select_option("#ya-b", "mockthink")
            page.fill("#input", "Design a cache.")
            posts.clear()
            page.click("#send-btn")
            # yes-and posts two converse-style ai turns; wait until both A and B are on screen
            page.wait_for_function(
                "document.querySelectorAll('#stream .turn:not(.human)').length >= 2", timeout=30000)
            assert any(u.endswith(f"/rooms/{rid}/run") for u in posts), "yes-and dispatches through /run"
            turns = _json(f"/rooms/{rid}")["turns"]
            ya = [t for t in turns if t["role"] == "ai" and t["mode"] == "converse"]
            assert ya[-2]["speaker"] == "mock" and ya[-1]["speaker"] == "mockthink", \
                "yes-and posts A (mock) then B (mockthink), both forward"
            print("yes-and OK: A then B, both forward, via /run")

            b.close()
        print("\nPHASE 26 (mapping + yes-and + context toggle + judge labels): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
