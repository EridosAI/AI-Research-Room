"""browser_phase14.py — settings home + theme controls + scrollbar (headless Chromium).

  14A: "settings" opens a tabbed panel (Providers / Theme / Data); switching shows
       the right pane; Providers is the default and behaves as before.
  14B: text brightness derives the grey ramp from one input + persists; font size
       scales via --font-scale + persists; display name replaces the human label in
       the UI AND in what the model is shown (build_context); all reconstruct on a
       hard refresh with localStorage empty.
  14C: the transcript pane has a themed thin scrollbar.

Run:  python tests/browser_phase14.py   (needs playwright + chromium)
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
PORT = 8819
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p14browser")


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


def cssvar(page, n):
    return page.evaluate(f"getComputedStyle(document.documentElement).getPropertyValue('{n}').trim()")


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
        rid = _json("/rooms", "POST", {"title": "p14 room"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mock"], "judge": "mock"})

        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("p14 room")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='p14 room'")

            # --- 14A: settings opens, three tabs, Providers default, switching works ---
            page.click("#providers-btn")
            page.wait_for_selector('.pcard[data-name="mock"]')   # settings populated + shown
            assert page.locator(".tab").count() == 3, "expected 3 settings tabs"
            assert not page.locator('.tab-pane[data-pane="providers"]').is_hidden(), "Providers should be default tab"
            assert page.locator('.tab-pane[data-pane="theme"]').is_hidden()
            assert page.locator('.pcard[data-name="mock"]').count() == 1, "Providers panel moved intact"
            page.click('.tab[data-tab="theme"]')
            assert not page.locator('.tab-pane[data-pane="theme"]').is_hidden(), "Theme tab didn't show"
            assert page.locator('.tab-pane[data-pane="providers"]').is_hidden()
            print("14A OK: settings tabbed (Providers default), switching swaps panes")

            # --- 14B: text brightness (derived ramp) ---
            page.click('#brightness-opts button:has-text("Soft")')
            page.wait_for_timeout(150)
            tp = cssvar(page, "--text-primary")
            assert "oklch" in tp and "0.82" in tp, f"soft brightness didn't lower the ramp: {tp!r}"
            assert _json("/ui")["text_brightness"] == "soft", "brightness not persisted"
            print(f"14B brightness OK: ramp derived from one input ({tp!r}), persisted")

            # --- 14B: font size scale (incl. the wider XL/XXL steps) ---
            page.click('#fontsize-opts button:has-text("Large")')
            page.wait_for_timeout(150)
            assert cssvar(page, "--font-scale") == "1.12", f"font scale not applied: {cssvar(page,'--font-scale')!r}"
            assert _json("/ui")["font_scale"] == "large", "font scale not persisted"
            page.click('#fontsize-opts button:has-text("XXL")')          # the widened range (huge = 1.5)
            page.wait_for_timeout(150)
            assert cssvar(page, "--font-scale") == "1.5", f"XXL font scale not applied: {cssvar(page,'--font-scale')!r}"
            assert _json("/ui")["font_scale"] == "huge", "XXL font scale not persisted"
            print("14B font OK: --font-scale applied + persisted (incl. XXL/huge = 1.5)")

            # --- 14B: display name replaces 'human' in UI and in build_context ---
            page.fill("#display-name", "Jason")
            page.click("#display-name-save")
            page.wait_for_timeout(200)
            page.click("#providers-close")
            page.fill("#input", "hello there")
            page.press("#input", "Enter")
            page.wait_for_selector("text=[mock:mock/mock-1]", timeout=15000)
            who = page.locator(".turn.human .who").last.inner_text()
            assert "Jason" in who and "human" not in who, f"display name not shown in UI: {who!r}"
            ai = [t for t in _json(f"/rooms/{rid}")["turns"] if t["role"] == "ai"][-1]
            assert "Jason" in ai["text"], "display name didn't reach build_context (model saw 'human')"
            print("14B name OK: 'Jason' replaces human in the UI and in what the model is shown")

            # --- 14C: themed thin scrollbar on the transcript pane ---
            sw = page.eval_on_selector("#stream", "el => getComputedStyle(el).scrollbarWidth")
            assert sw == "thin", f"transcript scrollbar not styled thin: {sw!r}"
            print("14C OK: transcript pane has a themed thin scrollbar")

            # --- persistence across hard refresh, no browser storage ---
            assert page.evaluate("window.localStorage.length") == 0, "localStorage used (forbidden)"
            page.reload(wait_until="networkidle")
            assert "0.82" in cssvar(page, "--text-primary"), "brightness not restored after reload"
            assert cssvar(page, "--font-scale") == "1.5", "font scale (huge) not restored after reload"
            page.locator('.room-row:has-text("p14 room")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='p14 room'")
            assert "Jason" in page.locator(".turn.human .who").last.inner_text(), "display name not restored after reload"
            assert page.evaluate("window.localStorage.length") == 0, "localStorage populated after reload"
            print("persistence OK: brightness + font + name reconstruct from ui.json, localStorage empty")
            b.close()
        print("\nPHASE 14 (settings home + theme controls + scrollbar): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
