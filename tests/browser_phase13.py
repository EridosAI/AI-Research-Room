"""browser_phase13.py — Linear reskin gates (real headless Chromium, mock fixture).

  - the token layer resolves (neutral tiers + derived oklch accent);
  - applyAccent recolours every accent var coherently from one hue;
  - the chosen accent persists across a HARD REFRESH — reconstructed from ui.json,
    with localStorage empty (no browser storage);
  - Inter is served locally (woff2) and applied (no CDN);
  - speaker-dot identity colours stay OUTSIDE the accent system.

Run:  python tests/browser_phase13.py   (needs playwright + chromium)
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
PORT = 8818
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p13browser")


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


def cssvar(page, name):
    return page.evaluate(
        f"getComputedStyle(document.documentElement).getPropertyValue('{name}').trim()")


def main():
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
        # local Inter is actually served
        with urllib.request.urlopen(BASE + "/static/fonts/InterVariable.woff2", timeout=10) as r:
            head = r.read(4)
        assert r.status == 200 and head == b"wOF2", "Inter woff2 not served locally"
        print("Inter OK: woff2 served locally (offline-safe, no CDN)")

        rid = _json("/rooms", "POST", {"title": "theme room"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mock"], "judge": "mock"})

        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")

            # --- token layer resolves ---
            assert cssvar(page, "--bg-primary") == "#08090a", "neutral surface token missing"
            assert cssvar(page, "--bg-tertiary"), "elevation tier token missing"
            acc = cssvar(page, "--accent")
            assert "oklch" in acc and "233" in acc, f"default navy accent not applied: {acc!r}"
            print(f"tokens OK: surfaces resolve, accent = {acc!r}")

            # Inter is the applied body font
            fam = page.evaluate("getComputedStyle(document.body).fontFamily")
            assert "Inter" in fam, f"Inter not the body font: {fam!r}"

            # --- accent engine: one hue → all six accent vars coherent ---
            page.click("#providers-btn")
            page.click('.tab[data-tab="theme"]')
            page.wait_for_selector("#accent-swatches .accent-swatch")
            page.click('.accent-swatch[title="hue 330"]')
            page.wait_for_timeout(200)
            for v in ("--accent", "--accent-hover", "--accent-active", "--accent-text",
                      "--accent-subtle", "--accent-border"):
                assert "330" in cssvar(page, v), f"{v} did not follow the hue: {cssvar(page, v)!r}"
            assert _json("/ui")["accent_hue"] == 330, "accent_hue not persisted to ui.json"
            print("accent OK: one hue recoloured all six accent roles + persisted")

            # speaker-dot identity stays OUTSIDE the accent system
            page.select_option("#mode", "converse", force=True)
            page.select_option("#addressee", "mock")
            page.fill("#input", "ping")
            page.press("#input", "Enter")
            page.wait_for_selector("text=[mock:mock/mock-1]", timeout=15000)
            dotbg = page.eval_on_selector(".turn .who .dot", "el => el.style.background")
            assert "oklch" not in dotbg and dotbg, f"speaker dot leaked into the accent system: {dotbg!r}"
            print(f"dot exception OK: speaker dot uses its own colour ({dotbg!r}), not the accent")

            # --- persistence across a HARD REFRESH, no browser storage ---
            assert page.evaluate("window.localStorage.length") == 0, "localStorage used (forbidden)"
            page.reload(wait_until="networkidle")
            acc2 = cssvar(page, "--accent")
            assert "330" in acc2, f"accent not reconstructed from server after reload: {acc2!r}"
            assert page.evaluate("window.localStorage.length") == 0, "localStorage populated after reload"
            print("persistence OK: accent reconstructed from ui.json across hard refresh, localStorage empty")
            b.close()
        print("\nLINEAR RESKIN (tokens + accent engine + persistence + Inter + dots): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
