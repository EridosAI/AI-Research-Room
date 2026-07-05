"""browser_phase35.py — composer fast path (Chromium).

  35.1 disclosure: collapsed default (mode chip + addressee); expanding reveals the mode
       select + its opts; expand/collapse never changes the mode.
  35.2 stickiness: mode + addressee are session-scoped per-room (stash on switch, restore
       after adopt); a stored addressee that left the roster falls back to auto; reload resets.
  35.3 legibility: the collapsed chip names the active mode; non-converse auto-expands on
       restore; the effort label reads "round effort".
  + regressions: a full fusion round and a converse round send through the new layout;
    Phase-31 drafts/optimistic/palette unaffected.

Run:  python tests/browser_phase35.py
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
PORT = 8841
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p35browser")


def _json(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"Content-Type": "application/json"} if body is not None else {}
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        BASE + path, data=data, headers=hdr, method=method), timeout=20).read() or "{}")


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
           "RESEARCH_ROOM_UI": str(HOME / "ui.json"), "RESEARCH_ROOM_PORT": str(PORT),
           "RR_MOCK_DELAY": "3"}   # mockslow sleeps → the optimistic bubble is observable
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        a = _json("/rooms", "POST", {"title": "alpha"})["room"]["id"]
        _json(f"/rooms/{a}", "PUT", {"participants": ["mock", "mockthink"], "judge": "mock"})
        b = _json("/rooms", "POST", {"title": "beta"})["room"]["id"]
        _json(f"/rooms/{b}", "PUT", {"participants": ["mock"], "judge": "mock"})
        s = _json("/rooms", "POST", {"title": "slowroom"})["room"]["id"]     # converse + optimistic regression
        _json(f"/rooms/{s}", "PUT", {"participants": ["mockslow"], "judge": "mock"})
        f = _json("/rooms", "POST", {"title": "fusionroom"})["room"]["id"]   # fusion regression
        _json(f"/rooms/{f}", "PUT", {"participants": ["mock", "mockthink"], "judge": "mock"})

        with sync_playwright() as p:
            br = p.chromium.launch(); page = br.new_page()
            hidden = lambda s: page.eval_on_selector(s, "e => e.classList.contains('hidden')")
            chip = lambda: page.locator("#mode-toggle").inner_text()
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='alpha'")

            # ---- 35.1 collapsed default ----
            assert hidden("#composer-advanced"), "the mode machinery is collapsed by default"
            assert not hidden("#converse-opts"), "the addressee (converse fast path) shows by default"
            assert "converse" in chip() and "▸" in chip(), f"chip names converse, collapsed: {chip()!r}"
            assert "round effort" in page.locator("#research-opts").inner_text(), "effort label renamed to 'round effort'"
            print("35.1 default OK: collapsed row = mode chip + addressee; 'round effort' label")

            # ---- 35.1 expand/collapse idempotent, mode untouched ----
            page.click("#mode-toggle")
            assert not hidden("#composer-advanced") and "▾" in chip(), "toggle expands + chevron flips"
            assert page.eval_on_selector("#mode", "e => e.value") == "converse", "expanding does not change mode"
            page.click("#mode-toggle")
            assert hidden("#composer-advanced") and "▸" in chip(), "toggle collapses again"
            assert page.eval_on_selector("#mode", "e => e.value") == "converse", "collapsing does not change mode"
            print("35.1 toggle OK: expand/collapse idempotent, mode untouched")

            # ---- 35.3 pick converse addressee, then set fusion (in room A) ----
            page.click("#mode-toggle")                                   # expand
            page.select_option("#addressee", "mock")                     # named addressee (converse-opts visible)
            page.select_option("#mode", "fusion")
            page.evaluate("document.querySelector('#mode').dispatchEvent(new Event('change'))")
            assert "fusion" in chip(), f"chip updates to fusion: {chip()!r}"
            assert page.eval_on_selector("#mode-toggle", "e => e.classList.contains('active')"), "chip is 'active' for non-converse"
            assert hidden("#converse-opts"), "fusion hides the addressee (chip is the summary)"
            print("35.3 chip OK: chip names fusion + active class; addressee hidden in non-converse")

            # ---- 35.2 stickiness: switch to B (unaffected), return to A (restored) ----
            page.locator('.room-row:has-text("beta")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='beta'")
            assert page.eval_on_selector("#mode", "e => e.value") == "converse", "beta is converse (unaffected)"
            assert hidden("#composer-advanced"), "beta collapsed (converse)"
            assert page.input_value("#addressee") == "", "beta addressee is auto"
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='alpha'")
            assert page.eval_on_selector("#mode", "e => e.value") == "fusion", "alpha's mode restored to fusion"
            assert not hidden("#composer-advanced"), "non-converse restore auto-expands the disclosure"
            assert page.input_value("#addressee") == "mock", "alpha's addressee restored to mock"
            print("35.2 restore OK: per-room mode + addressee restored; non-converse auto-expands; B unaffected")

            # ---- 35.2 removed participant → addressee falls back to auto ----
            _json(f"/rooms/{a}", "PUT", {"participants": ["mockthink"], "judge": "mockthink"})   # drop 'mock'
            page.locator('.room-row:has-text("beta")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='beta'")
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='alpha'")
            assert page.input_value("#addressee") == "", "a stored addressee that left the roster falls back to auto"
            print("35.2 fallback OK: removed participant → addressee silently falls back to auto")

            # ---- 35.2 reload resets to converse + auto + collapsed ----
            page.reload(wait_until="networkidle")
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='alpha'")
            assert page.eval_on_selector("#mode", "e => e.value") == "converse", "reload resets mode to converse"
            assert hidden("#composer-advanced") and "converse" in chip(), "reload resets to collapsed converse"
            print("35.2 reload OK: session maps empty on reload → converse + collapsed")

            # ---- 35.2 sticky addressee survives a SEND + a send-then-switch (review-caught gap) ----
            # renderAddressee rebuilds the dropdown on every in-room re-adopt; a named addressee must
            # not silently revert to auto after a send (which would also poison the sticky map on switch).
            page.locator('.room-row:has-text("fusionroom")').click()   # 2 AIs, converse by default
            page.wait_for_function("document.querySelector('#title').textContent==='fusionroom'")
            page.select_option("#addressee", "mockthink")
            page.fill("#input", "addressed to mockthink")
            page.click("#send-btn")
            page.wait_for_selector(".turn:has-text('addressed to mockthink')", timeout=20000)
            assert page.input_value("#addressee") == "mockthink", "a named addressee must survive a send (not revert to auto)"
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='alpha'")
            page.locator('.room-row:has-text("fusionroom")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='fusionroom'")
            assert page.input_value("#addressee") == "mockthink", "sticky addressee survives send-then-switch-away-and-back"
            print("35.2 sticky-send OK: a named addressee survives a send and a send-then-switch")

            # ---- regression: converse send through the new layout (optimistic bubble, mockslow) ----
            page.locator('.room-row:has-text("slowroom")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='slowroom'")
            page.select_option("#addressee", "mockslow")
            page.fill("#input", "hello via fast path")
            page.click("#send-btn")
            page.wait_for_selector(".turn.pending", timeout=2500)   # optimistic render still works
            page.wait_for_selector(".turn.pending", state="detached", timeout=20000)
            assert page.locator(".turn.human:not(.pending)", has_text="hello via fast path").count() >= 1, \
                "converse round lands through the new layout"
            print("regression OK: converse send + optimistic bubble unaffected")

            # ---- regression: fusion round through the new layout ----
            page.locator('.room-row:has-text("fusionroom")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='fusionroom'")
            page.click("#mode-toggle")                                  # expand
            page.select_option("#mode", "fusion")
            page.evaluate("document.querySelector('#mode').dispatchEvent(new Event('change'))")
            page.fill("#input", "fusion via fast path")
            page.click("#send-btn")
            page.wait_for_selector(".round .synthesis", timeout=30000)
            print("regression OK: a full fusion round sends through the new layout")

            # ---- regression: Phase-31 palette still opens ----
            page.keyboard.press("Control+k")
            page.wait_for_selector("#palette-overlay:not(.hidden)", timeout=3000)
            page.keyboard.press("Escape")
            print("regression OK: ⌘K/Ctrl-K palette unaffected")

            br.close()
        print("\nPHASE 35 (composer fast path): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
