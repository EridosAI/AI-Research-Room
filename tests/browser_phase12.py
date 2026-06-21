"""browser_phase12.py — Phase 12 UI gates (real headless Chromium, mock fixture).

  Feature C (Enter-to-send): Enter sends; Shift+Enter inserts a newline (no send).
  Feature B (token chip): each participant shows ~X / Y fill; a session total
    accrues; estimates are ~-prefixed.
  Feature A (UI round-trips): export folder persists to ui.json; room tags persist
    to room.json.

Run:  python tests/browser_phase12.py   (needs playwright + chromium)
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
PORT = 8817
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p12browser")


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
           "RESEARCH_ROOM_UI": str(HOME / "ui.json"), "RESEARCH_ROOM_PORT": str(PORT)}
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        # mock gets a context window so the chip can show ~X / Y
        _json("/providers/mock", "PUT", {"context_window": 128000})
        rid = _json("/rooms", "POST", {"title": "phase12 room"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mock"], "judge": "mock"})

        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("phase12 room")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='phase12 room'")

            # --- Feature C: Shift+Enter newlines (no send), Enter sends ---
            page.click("#input")
            page.fill("#input", "first line")
            page.press("#input", "Shift+Enter")
            page.wait_for_timeout(150)
            val = page.eval_on_selector("#input", "el => el.value")
            assert "\n" in val, f"Shift+Enter should insert a newline; value={val!r}"
            assert page.locator("#stream .turn").count() == 0, "Shift+Enter must NOT send"
            print("Shift+Enter OK: newline inserted, nothing sent")

            page.fill("#input", "hello via enter")
            page.press("#input", "Enter")
            page.wait_for_selector("text=[mock:mock/mock-1]", timeout=15000)
            assert page.eval_on_selector("#input", "el => el.value") == "", "input should clear after send"
            print("Enter OK: Enter sent the message")

            # --- Feature B: model-square bar + session total (Phase 20 replaced the chip line) ---
            page.wait_for_selector("#token-bar .model-square")
            assert page.locator('#token-bar .model-square[data-model="mock"]').count() == 1, "mock square missing"
            bar = page.locator("#token-bar").inner_text()
            assert "session" in bar, f"session total missing: {bar!r}"
            assert "~" in bar, f"mock estimate not ~-prefixed: {bar!r}"
            print(f"model bar OK: {bar!r}")

            # --- Feature A UI: export folder + room tags round-trip ---
            page.click("#providers-btn")
            page.click('.tab[data-tab="data"]')
            page.wait_for_selector("#export-dir")
            page.fill("#export-dir", "/tmp/p12-vault")
            page.get_by_text("save", exact=False)  # ensure overlay live
            page.click("#export-save")
            page.wait_for_timeout(300)
            assert _json("/ui")["export_dir"] == "/tmp/p12-vault", "export_dir not persisted to ui.json"
            cur = page.locator("#export-current").inner_text()
            assert "/tmp/p12-vault" in cur, f"current path not displayed under the box: {cur!r}"
            page.click("#providers-close")
            # reopen → the saved path is still shown
            page.click("#providers-btn")
            page.click('.tab[data-tab="data"]')
            page.wait_for_selector("#export-dir")
            assert "/tmp/p12-vault" in page.locator("#export-current").inner_text(), "current path not shown on reopen"
            page.click("#providers-close")
            print("export setting OK: persisted to ui.json + shown under the box")

            page.click("#room-settings-btn")
            page.wait_for_selector("#room-tags")
            page.fill("#room-tags", "alpha, beta")
            page.click("#room-settings-save")
            page.wait_for_timeout(300)
            assert _json(f"/rooms/{rid}")["tags"] == ["alpha", "beta"], "room tags not persisted to room.json"
            print("room tags OK: persisted to room.json")
            b.close()
        print("\nPHASE 12 UI (Enter-key + token chip + export/tags): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
