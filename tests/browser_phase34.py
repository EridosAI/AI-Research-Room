"""browser_phase34.py — pane coexistence (Chromium), run across viewport widths.

  34.1 DOM order: [main-col | viewer | margin] — viewer adjacent to the transcript.
  34.2 width-aware guard: WIDE viewport → viewer + margin coexist (transcript ≥ MIN_MAIN);
       NARROW viewport → opening one swaps the other (Phase 33 behavior preserved).
  34.3 clamps + resize: a splitter drag can't crush the transcript below MIN_MAIN; shrinking
       the window with both open auto-closes the MARGIN once (no thrash); the sidebar toggle
       respects the rule; Esc still closes the viewer (not the margin).

Run:  python tests/browser_phase34.py
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
PORT = 8840
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p34browser")
MIN_MAIN = 520
DOC = "spec\n\n```markdown\n# Heading\n\nbody\n```\n"


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
           "RESEARCH_ROOM_UI": str(HOME / "ui.json"), "RESEARCH_ROOM_PORT": str(PORT)}
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        r = _json("/rooms", "POST", {"title": "docroom"})["room"]["id"]
        _json(f"/rooms/{r}", "PUT", {"participants": ["mock"], "judge": "mock"})
        (HOME / "vault" / r / "main.jsonl").write_text(json.dumps({
            "id": "a", "ts": "2026-07-02T00:00:00", "mode": "converse", "role": "ai", "speaker": "mock",
            "text": DOC, "meta": {"model": "m", "artifact_paths": [str(HOME / "arts" / "docroom-1.md")]}}) + "\n")

        with sync_playwright() as p:
            br = p.chromium.launch()
            page = br.new_context(viewport={"width": 2000, "height": 900}).new_page()
            hidden = lambda s: page.eval_on_selector(s, "e => e.classList.contains('hidden')")
            openView = lambda: page.locator('.artifact.saved .artifact-btn:has-text("open")').click()
            mainW = lambda: page.locator(".main-col").bounding_box()["width"]
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("docroom")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='docroom'")
            page.wait_for_selector(".artifact")

            # ---- 34.1 DOM order: viewer before margin ----
            order = page.evaluate(
                "(document.querySelector('#viewer').compareDocumentPosition(document.querySelector('#margin'))"
                " & Node.DOCUMENT_POSITION_FOLLOWING) ? 'viewer-first' : 'margin-first'")
            assert order == "viewer-first", "the viewer must precede the margin in the row (Phase 34.1)"
            print("34.1 order OK: DOM order is [transcript | viewer | margin]")

            # ---- 34.2 WIDE (2000px): both panes coexist ----
            openView(); page.wait_for_selector("#viewer:not(.hidden)")
            page.click("#margin-toggle"); page.wait_for_selector("#margin:not(.hidden)")
            assert not hidden("#viewer"), "wide viewport: the viewer stays open when the margin opens"
            assert not hidden("#margin"), "wide viewport: both panes coexist"
            assert mainW() >= MIN_MAIN, f"transcript must keep ≥ {MIN_MAIN}px with both open (got {mainW():.0f})"
            vx = page.locator("#viewer").bounding_box()["x"]
            mx = page.locator("#margin").bounding_box()["x"]
            assert vx < mx, "left-to-right, the viewer sits left of the margin"
            print(f"34.2 wide OK: viewer + margin coexist, transcript {mainW():.0f}px ≥ {MIN_MAIN}")

            # ---- 34.3 splitter clamp under coexistence ----
            box = page.locator("#viewer-splitter").bounding_box()
            page.mouse.move(box["x"] + 2, box["y"] + box["height"] / 2)
            page.mouse.down(); page.mouse.move(150, box["y"] + box["height"] / 2, steps=6); page.mouse.up()
            assert mainW() >= MIN_MAIN - 1, f"a splitter drag must not crush the transcript (got {mainW():.0f})"
            assert not hidden("#margin"), "the margin must not be pushed offscreen by the drag"
            print(f"34.3 clamp OK: dragging the viewer wide still leaves the transcript {mainW():.0f}px")

            # ---- 34.3 resize shrink → closes the MARGIN, once ----
            page.set_viewport_size({"width": 1100, "height": 900})
            page.wait_for_timeout(350)   # debounced enforcePaneFit
            assert hidden("#margin"), "shrinking with both open auto-closes the margin"
            assert not hidden("#viewer"), "the viewer (working material) survives the shrink"
            page.set_viewport_size({"width": 1000, "height": 900})
            page.wait_for_timeout(350)
            assert not hidden("#viewer"), "further shrink must not thrash — only one pane remains"
            print("34.3 resize OK: shrink closes the margin only, once (no thrash)")

            # ---- 34.2 NARROW (1100px): opening one swaps the other ----
            page.set_viewport_size({"width": 1100, "height": 900})
            page.keyboard.press("Escape")   # close the viewer to reset
            page.wait_for_selector("#viewer", state="hidden")
            openView(); page.wait_for_selector("#viewer:not(.hidden)")
            page.click("#margin-toggle"); page.wait_for_selector("#margin:not(.hidden)")
            assert hidden("#viewer"), "narrow viewport: opening the margin swaps out the viewer"
            openView(); page.wait_for_selector("#viewer:not(.hidden)")
            assert hidden("#margin"), "narrow viewport: opening the viewer swaps out the margin"
            print("34.2 narrow OK: panes swap when the transcript can't fit both")

            # ---- 34.3 sidebar-toggle path (a viewport where the fit depends on the sidebar) ----
            # reset viewer_width (the clamp drag above grew + persisted it) for predictable fit
            # math, then reload for a clean pane state.
            _json(f"/rooms/{r}", "PUT", {"viewer_width": 460})
            page.set_viewport_size({"width": 1450, "height": 900})
            page.reload(wait_until="networkidle")
            page.locator('.room-row:has-text("docroom")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='docroom'")
            page.wait_for_selector(".artifact")
            page.click("#sidebar-collapse")
            page.wait_for_function("document.querySelector('#sidebar').classList.contains('collapsed')")
            openView(); page.wait_for_selector("#viewer:not(.hidden)")
            page.click("#margin-toggle"); page.wait_for_selector("#margin:not(.hidden)")
            assert not hidden("#viewer") and not hidden("#margin"), "collapsed sidebar → both fit at 1450px"
            page.click("#sidebar-expand")
            page.wait_for_function("!document.querySelector('#sidebar').classList.contains('collapsed')")
            assert hidden("#margin"), "expanding the sidebar shrinks the workspace → margin yields (Phase 34.3)"
            assert not hidden("#viewer"), "the viewer survives the sidebar expand"
            print("34.3 sidebar OK: expanding the sidebar re-checks the fit and closes the margin")

            # ---- Esc precedence unchanged: closes the viewer, never the margin ----
            page.set_viewport_size({"width": 1100, "height": 900}); page.wait_for_timeout(200)
            page.click("#margin-toggle"); page.wait_for_selector("#margin:not(.hidden)")
            page.keyboard.press("Escape"); page.wait_for_timeout(100)
            assert not hidden("#margin"), "Esc must NOT close the margin (unchanged; DEFERRED)"
            print("34.x esc OK: the margin stays non-Esc-dismissable")

            br.close()
        print("\nPHASE 34 (pane coexistence): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
