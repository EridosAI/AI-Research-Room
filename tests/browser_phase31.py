"""browser_phase31.py — composer micro-polish (Chromium).

Four felt-quality fixes, each gated here:
  31.1 focus     — the caret lands in #input on load, room switch, new-room, margin close;
                   opening an overlay does NOT yank focus.
  31.2 drafts    — per-room, session-only composer drafts (no bleed across a switch);
                   preserved on send failure; margin input behaves identically; no disk key.
  31.3 optimistic— the user's message paints immediately (before the round-trip) as a
                   .turn.pending; the server turn replaces it; a failed send leaves no ghost.
  31.4 palette   — Ctrl/Cmd+K opens a room switcher; type filters; Enter switches + focuses
                   the composer; Esc + backdrop close it; the two existing overlays close on
                   Esc/backdrop too (one dismissal grammar).

Uses `mock` (fast), `mockslow` (RR_MOCK_DELAY — the optimistic window) and `mockfail`
(forces the error path).

Run:  python tests/browser_phase31.py
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
PORT = 8837
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p31browser")
DELAY = 3   # seconds mockslow sleeps — the window to observe the optimistic bubble


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
           "RESEARCH_ROOM_PORT": str(PORT), "RR_MOCK_DELAY": str(DELAY)}
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        # four rooms: two plain (draft/switch/palette), one slow (optimistic), one failing (error path)
        a = _json("/rooms", "POST", {"title": "alpha"})["room"]["id"]
        _json(f"/rooms/{a}", "PUT", {"participants": ["mock"], "judge": "mock"})
        b = _json("/rooms", "POST", {"title": "beta"})["room"]["id"]
        _json(f"/rooms/{b}", "PUT", {"participants": ["mock"], "judge": "mock"})
        s = _json("/rooms", "POST", {"title": "slowroom"})["room"]["id"]
        _json(f"/rooms/{s}", "PUT", {"participants": ["mockslow"], "judge": "mock"})
        f = _json("/rooms", "POST", {"title": "failroom"})["room"]["id"]
        _json(f"/rooms/{f}", "PUT", {"participants": ["mockfail"], "judge": "mock"})

        with sync_playwright() as p:
            br = p.chromium.launch(); page = br.new_page()
            active_id = lambda: page.evaluate("document.activeElement && document.activeElement.id")
            hidden = lambda sel: page.eval_on_selector(sel, "e => e.classList.contains('hidden')")

            # ================= 31.1 focus =================
            page.goto(BASE + "/", wait_until="networkidle")
            page.wait_for_function("document.activeElement && document.activeElement.id === 'input'", timeout=5000)
            print("31.1 load OK: caret lands in #input on app load")

            # room switch → focus
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='alpha'")
            page.wait_for_function("document.activeElement && document.activeElement.id === 'input'", timeout=3000)
            print("31.1 switch OK: caret lands in #input after a room switch")

            # new-room → focus (accept the native title prompt)
            page.once("dialog", lambda d: d.accept("focusnew"))
            page.click("#new-room-btn")
            page.wait_for_function("document.querySelector('#title').textContent==='focusnew'")
            page.wait_for_function("document.activeElement && document.activeElement.id === 'input'", timeout=3000)
            print("31.1 new-room OK: caret lands in #input after creating a room")

            # margin close → focus
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='alpha'")
            page.click("#margin-toggle")                     # open
            page.wait_for_selector("#margin:not(.hidden)")
            page.click("#margin-close")                      # close → focusComposer
            page.wait_for_function("document.activeElement && document.activeElement.id === 'input'", timeout=3000)
            print("31.1 margin-close OK: caret returns to #input when the margin closes")

            # guard: opening an overlay must NOT yank focus into #input
            page.click("#room-settings-btn")
            page.wait_for_selector("#room-settings-overlay:not(.hidden)")
            assert active_id() != "input", "opening room settings should not steal focus to #input"
            page.keyboard.press("Escape")                    # (also exercises the retrofit, asserted below)
            page.wait_for_selector("#room-settings-overlay", state="hidden")
            print("31.1 guard OK: opening an overlay does not yank focus to the composer")

            # ================= 31.2 per-room drafts =================
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='alpha'")
            page.fill("#input", "draft-alpha-123")
            page.locator('.room-row:has-text("beta")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='beta'")
            assert page.input_value("#input") == "", "beta should open with an empty composer (no bleed)"
            page.fill("#input", "draft-beta-xyz")
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='alpha'")
            assert page.input_value("#input") == "draft-alpha-123", "alpha's draft must be restored verbatim"
            page.locator('.room-row:has-text("beta")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='beta'")
            assert page.input_value("#input") == "draft-beta-xyz", "beta's draft must be restored verbatim"
            print("31.2 composer OK: drafts stash/restore per room, no bleed across a switch")

            # margin drafts behave identically
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='alpha'")
            page.click("#margin-toggle"); page.wait_for_selector("#margin:not(.hidden)")
            page.fill("#margin-input", "margin-alpha-draft")
            page.locator('.room-row:has-text("beta")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='beta'")
            assert page.input_value("#margin-input") == "", "beta margin should be empty (no bleed)"
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='alpha'")
            assert page.input_value("#margin-input") == "margin-alpha-draft", "alpha margin draft must restore"
            page.click("#margin-close")
            print("31.2 margin OK: margin input drafts stash/restore per room too")

            # draft preserved on send failure (+ no ghost bubble — 31.3 error path)
            page.locator('.room-row:has-text("failroom")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='failroom'")
            page.select_option("#mode", "converse")
            page.select_option("#addressee", "mockfail")
            page.fill("#input", "keep-me-on-error")
            page.click("#send-btn")
            page.wait_for_function(
                "!document.querySelector('#banner').classList.contains('hidden') && "
                "/failed/i.test(document.querySelector('#banner').textContent)", timeout=10000)
            assert page.input_value("#input") == "keep-me-on-error", "a failed send must preserve the typed draft"
            assert page.locator(".turn.pending").count() == 0, "a failed send must leave no ghost pending bubble"
            print("31.2/31.3 error OK: failed send preserves the draft and leaves no ghost bubble")

            # ================= 31.3 optimistic render =================
            page.locator('.room-row:has-text("slowroom")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='slowroom'")
            page.select_option("#mode", "converse")
            page.select_option("#addressee", "mockslow")
            page.fill("#input", "optimistic-slow-xyz")
            page.click("#send-btn")
            # appears immediately, before the (delayed) server response
            page.wait_for_selector(".turn.pending", timeout=2500)
            assert "optimistic-slow-xyz" in page.locator(".turn.pending").inner_text(), \
                "the optimistic bubble should carry the just-typed text"
            print("31.3 optimistic OK: the user's message paints immediately as .turn.pending")
            # the server turn replaces it: pending clears, a real (non-pending) human turn remains
            page.wait_for_selector(".turn.pending", state="detached", timeout=20000)
            assert page.locator(".turn.human:not(.pending)", has_text="optimistic-slow-xyz").count() >= 1, \
                "the authoritative human turn should remain after the round-trip"
            assert page.locator(".turn.pending").count() == 0, "no pending bubble should survive the response"
            print("31.3 replace OK: the server turn seamlessly replaces the optimistic bubble (no ghost)")

            # ================= 31.4 Ctrl/Cmd+K palette =================
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='alpha'")
            page.click("#input")                             # composer has focus…
            page.keyboard.press("Control+k")                 # …Ctrl+K still opens it
            page.wait_for_selector("#palette-overlay:not(.hidden)", timeout=3000)
            assert active_id() == "palette-input", "the palette input should be autofocused on open"
            print("31.4 open OK: Ctrl+K opens the palette (even from the composer) and focuses its input")

            page.fill("#palette-input", "beta")
            page.wait_for_function(
                "[...document.querySelectorAll('#palette-list .palette-row .palette-title')]"
                ".some(e => e.textContent.includes('beta'))", timeout=3000)
            titles = page.locator("#palette-list .palette-row .palette-title").all_inner_texts()
            assert any("beta" in t for t in titles) and not any("alpha" in t for t in titles), \
                f"filter should narrow to beta: {titles!r}"
            print("31.4 filter OK: typing narrows the room list live")

            page.keyboard.press("Enter")
            page.wait_for_function("document.querySelector('#title').textContent==='beta'", timeout=5000)
            page.wait_for_selector("#palette-overlay", state="hidden")
            page.wait_for_function("document.activeElement && document.activeElement.id === 'input'", timeout=3000)
            print("31.4 enter OK: Enter switches room and the caret lands in the composer")

            # Esc closes the palette
            page.keyboard.press("Control+k"); page.wait_for_selector("#palette-overlay:not(.hidden)")
            page.keyboard.press("Escape"); page.wait_for_selector("#palette-overlay", state="hidden")
            print("31.4 esc OK: Esc closes the palette")

            # backdrop click closes the palette (6,6 = the dimmed corner, above/left of the card)
            page.keyboard.press("Control+k"); page.wait_for_selector("#palette-overlay:not(.hidden)")
            page.mouse.click(6, 6)
            page.wait_for_selector("#palette-overlay", state="hidden")
            print("31.4 backdrop OK: clicking the backdrop closes the palette")

            # retrofit: the two existing overlays now close on Esc AND backdrop
            page.click("#room-settings-btn"); page.wait_for_selector("#room-settings-overlay:not(.hidden)")
            page.keyboard.press("Escape"); page.wait_for_selector("#room-settings-overlay", state="hidden")
            page.click("#providers-btn"); page.wait_for_selector("#providers-overlay:not(.hidden)")
            page.mouse.click(6, 6)
            page.wait_for_selector("#providers-overlay", state="hidden")
            print("31.4 retrofit OK: room-settings closes on Esc, providers closes on backdrop — one grammar")

            # non-interference: with the palette CLOSED, Enter in the composer must not open it
            assert hidden("#palette-overlay"), "palette should be closed here"
            page.fill("#input", "just-a-message")
            page.focus("#input"); page.keyboard.press("Enter")
            assert hidden("#palette-overlay"), "Enter-to-send must not open the palette"
            print("31.4 noconflict OK: Enter-to-send is untouched when the palette is closed")

            br.close()

        # ---- no draft persisted to disk (ui.json) or localStorage ----
        ui = json.loads((HOME / "ui.json").read_text()) if (HOME / "ui.json").exists() else {}
        assert not any("draft" in k for k in ui), f"no draft key belongs in ui.json: {list(ui)!r}"
        appjs = (REPO / "web" / "static" / "app.js").read_text()
        assert "localStorage.setItem" not in appjs and "localStorage.getItem" not in appjs, \
            "drafts must stay in-memory — no localStorage use"
        print("persistence OK: drafts are session-only (no ui.json key, no localStorage)")

        print("\nPHASE 31 (composer micro-polish): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
