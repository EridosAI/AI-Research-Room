"""browser_phase25.py — unified mode selector + side-by-side (real headless Chromium).

  - one mode selector lists Converse · Fusion · Side-by-side;
  - params reveal contextually (converse → addressee; fusion → judge+panel; side-by-side
    → two-seat picker + judge);
  - side-by-side dispatches through the unified /run endpoint and renders two panel
    answers + a divergence-note (judge) turn.

Offline (mock seats) — zero token cost.

Run:  python tests/browser_phase25.py
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
PORT = 8830
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p25browser")


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
        rid = _json("/rooms", "POST", {"title": "modes"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mock", "mockthink"], "judge": "mock"})

        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            posts = []
            page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("modes")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='modes'")

            # --- selector lists the three modes ---
            opts = page.eval_on_selector_all("#mode option", "els => els.map(e => e.value)")
            assert opts == ["converse", "fusion", "side_by_side"], f"mode options: {opts}"
            print("selector OK: lists converse · fusion · side-by-side")

            # --- params reveal contextually ---
            def visible(sel): return page.locator(sel).is_visible()
            assert visible("#converse-opts") and not visible("#research-opts") and not visible("#sxs-opts"), \
                "converse default: only the addressee param shows"
            page.select_option("#mode", "fusion")
            assert visible("#research-opts") and not visible("#converse-opts") and not visible("#sxs-opts"), \
                "fusion: judge + panel params show"
            page.select_option("#mode", "side_by_side")
            assert visible("#sxs-opts") and not visible("#research-opts") and not visible("#converse-opts"), \
                "side-by-side: the two-seat picker shows"
            assert page.locator("#sxs-pick input[type=checkbox]").count() == 2, \
                "two-seat picker lists the room roster"
            print("reveal OK: params reveal per mode; side-by-side shows the two-seat picker")

            # --- side-by-side runs through /run → two answers + a divergence note ---
            page.check('#sxs-pick input[value="mock"]')
            page.check('#sxs-pick input[value="mockthink"]')
            # judge defaults to the room judge (mock); confirm it's set
            assert page.eval_on_selector("#sxs-judge", "el => el.value") == "mock", "sxs judge defaults to room judge"
            page.fill("#input", "Compare approaches to caching.")
            posts.clear()
            page.click("#send-btn")
            page.wait_for_selector(".round .synthesis", timeout=30000)
            panels = page.locator(".round .panel").count()
            assert panels == 2, f"side-by-side should render two panel answers, got {panels}"
            assert page.locator(".round .synthesis").count() == 1, "a divergence-note (judge) turn renders"
            assert any(u.endswith(f"/rooms/{rid}/run") for u in posts), \
                f"dispatch must go through the unified /run endpoint: {posts}"
            print("side-by-side OK: two answers + divergence note via the unified /run endpoint")

            # the two panel answers are ai-raw (excluded from forward context) — engine-asserted;
            # here we confirm the transcript shape the round rendered from.
            turns = _json(f"/rooms/{rid}")["turns"]
            raw = [t for t in turns if (t.get("meta") or {}).get("is_panelist_raw")]
            assert len(raw) == 2, "two ai-raw panel turns recorded"
            print("shape OK: two ai-raw panel turns + a judge turn recorded")

            b.close()
        print("\nPHASE 25 (mode framework + side-by-side): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
