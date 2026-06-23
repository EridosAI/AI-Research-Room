"""browser_phase16.py — per-turn 'model' provenance pill (real headless Chromium).

  - a turn with meta.served_model shows a non-interactive "model" pill in the
    .turn-footer, BESIDE the "thinking" toggle;
  - the pill's title attribute equals the served model string;
  - the pill is absent when served_model is absent (and tinted on a config↔served
    mismatch) — verified via the modelPill() guard directly;
  - the reasoning disclosure still expands (now full-width below the pill row) —
    covered by browser_reasoning, which must pass unchanged.

Uses the `mockthink` fixture (mock backend, reasoning on) so it runs offline at
zero token cost — mock echoes its configured model as served_model.

Run:  python tests/browser_phase16.py   (needs playwright + chromium)
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
PORT = 8821
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p16browser")


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
        rid = _json("/rooms", "POST", {"title": "provenance room"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mockthink"], "judge": "mockthink"})

        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("provenance room")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='provenance room'")

            # --- research round → footer with thinking + model pill side by side ---
            page.select_option("#mode", "fusion")
            page.fill("#input", "why is the sky blue?")
            page.click("#send-btn")
            page.wait_for_selector(".round .synthesis", timeout=30000)

            footer = page.locator(".round .turn-footer").first
            assert footer.locator(".reasoning-toggle").count() == 1, "footer missing the thinking toggle"
            assert footer.locator(".model-pill").count() == 1, "footer missing the model pill (beside thinking)"
            print("render OK: model pill sits beside 'thinking' in the turn footer")

            # --- the pill SHOWS the served model id (glanceable), title carries the full string ---
            turns = _json(f"/rooms/{rid}")["turns"]
            served = next(t["meta"]["served_model"] for t in turns
                          if (t.get("meta") or {}).get("served_model"))
            short = served.split("/")[-1]
            pill = page.locator(".round .model-pill").first
            assert pill.inner_text().strip() == short, f"pill should show the served id {short!r}, got {pill.inner_text()!r}"
            assert served in (pill.get_attribute("title") or ""), \
                f"pill title should carry the served model: {pill.get_attribute('title')!r}"
            print(f"label OK: pill shows the served model id ({short!r})")

            # (context-isolation of served_model is an engine concern — covered directly in
            # engine_phase11 via the SERVED_SECRET_X build_context assertion.)

            # --- guard: pill absent without served_model; present (+tint on mismatch) with it ---
            assert page.evaluate("modelPill({meta:{model:'cfg'}}) === null"), \
                "pill should be absent when served_model is absent"
            assert page.evaluate("modelPill({meta:{}}) === null"), "pill should be absent on empty meta"
            assert page.evaluate("modelPill({meta:{served_model:'vendor/srv-x'}}).textContent") == "srv-x", \
                "pill should show the served id with the provider/ prefix stripped"
            assert "vendor/srv-x" in page.evaluate("modelPill({meta:{served_model:'vendor/srv-x'}}).getAttribute('title')"), \
                "pill title should carry the full served model"
            assert page.evaluate(
                "modelPill({meta:{model:'a',served_model:'b'}}).classList.contains('mismatch')"), \
                "mismatch (config != served) should tint the pill"
            assert page.evaluate(
                "!modelPill({meta:{model:'same',served_model:'same'}}).classList.contains('mismatch')"), \
                "matching config == served should NOT tint the pill"
            print("guard OK: absent without served_model; present + mismatch-tinted as specced")

            # --- the thinking disclosure still expands (now below the pill row) ---
            page.locator(".round .reasoning-toggle").first.click()
            assert page.locator(".round .reasoning-body").first.is_visible(), \
                "thinking disclosure no longer expands after the footer refactor"
            print("interop OK: 'thinking' still expands full-width below the footer")
            b.close()
        print("\nPHASE 16 (served-model capture + model pill): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
