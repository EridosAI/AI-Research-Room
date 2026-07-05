"""browser_phase33.py — artifact viewer pane + bubble realignment (Chromium).

  33.1 human bubbles join the left column flow (accent kept); the pending bubble too.
  33.2 viewer pane: opens/closes, mutually exclusive with the margin, per-room width
       round-trip, Esc precedence (overlays before the pane), room-switch closes it,
       close refocuses the composer.
  33.3 document-grade markdown: a heading renders at h1-scale (not a code fence), tables
       render; chat-bubble .md stays chat-grade (unchanged).
  33.4 chip wiring: "open" on saved + legacy chips (converse turns) renders the block.

Turns with fenced blocks are seeded into main.jsonl (the mock can't emit a fence via the
UI); the render + interaction paths are what's tested.

Run:  python tests/browser_phase33.py
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
PORT = 8839
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p33browser")
DELAY = 3
DOC = "here is the spec\n\n```markdown\n# Big Heading\n\n## Section\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nbody text\n```\n"


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


def _turn(role, speaker, text, meta):
    return {"id": f"{role}-{speaker}-{abs(hash(text)) & 0xffff}", "ts": "2026-07-02T00:00:00",
            "mode": "converse", "role": role, "speaker": speaker, "text": text, "meta": meta}


def _seed(room_id, turns):
    (HOME / "vault" / room_id / "main.jsonl").write_text("".join(json.dumps(t) + "\n" for t in turns))


def main():
    shutil.rmtree(HOME, ignore_errors=True)
    (HOME / "vault").mkdir(parents=True)
    (HOME / "arts").mkdir(parents=True)
    shutil.copy(REPO / "tests" / "config.toml", HOME / "config.toml")
    env = {**os.environ,
           "RESEARCH_ROOM_CONFIG": str(HOME / "config.toml"), "RESEARCH_ROOM_HOME": str(HOME),
           "RESEARCH_ROOM_SECRETS": str(HOME / "secrets.json"), "RESEARCH_ROOM_VAULT": str(HOME / "vault"),
           "RESEARCH_ROOM_UI": str(HOME / "ui.json"), "RESEARCH_ROOM_PORT": str(PORT), "RR_MOCK_DELAY": str(DELAY)}
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        doc = _json("/rooms", "POST", {"title": "docroom"})["room"]["id"]
        _json(f"/rooms/{doc}", "PUT", {"participants": ["mock"], "judge": "mock", "artifacts_dir": str(HOME / "arts")})
        saved_path = str(HOME / "arts" / "docroom-spec.md")
        _seed(doc, [
            _turn("human", "human", "make a spec", {}),
            _turn("ai", "mock", DOC, {"model": "m", "artifact_paths": [saved_path]}),   # saved
            _turn("ai", "mock", DOC, {"model": "m"}),                                    # legacy
            _turn("ai", "mock", "# Chat Heading\n\nplain body", {"model": "m"}),         # chat-grade .md h1
        ])
        other = _json("/rooms", "POST", {"title": "otherroom"})["room"]["id"]
        _json(f"/rooms/{other}", "PUT", {"participants": ["mock"], "judge": "mock"})
        slow = _json("/rooms", "POST", {"title": "slowroom"})["room"]["id"]
        _json(f"/rooms/{slow}", "PUT", {"participants": ["mockslow"], "judge": "mock"})
        _seed(slow, [_turn("ai", "mockslow", "prior answer", {"model": "m"})])

        with sync_playwright() as p:
            br = p.chromium.launch()
            # narrow viewport on purpose: Phase 34 lets the panes coexist on WIDE screens, so
            # the mutual-exclusion (swap) behavior only holds when the transcript can't fit both.
            ctx = br.new_context(viewport={"width": 1200, "height": 800})
            ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE)
            page = ctx.new_page()
            hidden = lambda s: page.eval_on_selector(s, "e => e.classList.contains('hidden')")
            page.goto(BASE + "/", wait_until="networkidle")

            # ================= 33.1 bubble realignment =================
            page.locator('.room-row:has-text("docroom")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='docroom'")
            page.wait_for_selector(".turn.human")
            hx = page.locator(".turn.human").first.bounding_box()["x"]
            ax = page.locator(".turn:not(.human)").first.bounding_box()["x"]
            assert abs(hx - ax) < 2, f"human turn must share the left column flow (h={hx}, ai={ax})"
            ta = page.eval_on_selector(".turn.human .who", "e => getComputedStyle(e).textAlign")
            assert ta != "right", f"human label must not be right-aligned: {ta}"
            # accent tint kept
            bg = page.eval_on_selector(".turn.human .body", "e => getComputedStyle(e).backgroundColor")
            assert bg and bg != "rgba(0, 0, 0, 0)", "human bubble keeps its accent tint"
            print("33.1 human OK: human turns left-aligned, label left, accent kept")

            # ================= 33.4 open from a chip + 33.3 document render =================
            page.locator('.artifact.saved .artifact-btn:has-text("open")').click()
            page.wait_for_selector("#viewer:not(.hidden)")
            assert page.locator("#viewer-title").inner_text() == "docroom-spec.md", "viewer titled with the filename"
            assert page.locator("#viewer-body h1").count() == 1, "the ```markdown block renders as a document (h1)"
            vh1 = page.eval_on_selector("#viewer-body h1", "e => parseFloat(getComputedStyle(e).fontSize)")
            assert vh1 > 20, f"viewer h1 should be document-scale, not code: {vh1}px"
            assert page.locator("#viewer-body table").count() == 1, "GFM table renders in the viewer"
            assert not hidden("#viewer-copypath"), "saved artifact → copy-path button in the viewer header"
            print(f"33.3/33.4 OK: chip opens a rendered document (h1 {vh1:.0f}px, table present)")

            # copy-path from the viewer header
            page.locator("#viewer-copypath").click()
            assert page.evaluate("navigator.clipboard.readText()") == saved_path, "viewer copy-path copies the saved path"
            print("33.4 copypath OK: viewer header copy-path copies the saved .md path")

            # chat-bubble .md stays chat-grade (smaller than the viewer's document h1)
            ch1 = page.eval_on_selector(".turn .body h1", "e => parseFloat(getComputedStyle(e).fontSize)")
            assert ch1 < vh1, f"chat .md h1 ({ch1}px) must stay chat-grade, below viewer h1 ({vh1}px)"
            print(f"33.3 unchanged OK: chat .md h1 stays {ch1:.0f}px (< viewer {vh1:.0f}px)")

            # legacy chip opens too — title falls back, no copy-path
            page.locator('.artifact:not(.saved) .artifact-btn:has-text("open")').click()
            page.wait_for_function("document.querySelector('#viewer-title').textContent==='markdown artifact'")
            assert hidden("#viewer-copypath"), "legacy artifact (no meta) → no copy-path in the viewer"
            print("33.4 legacy OK: a block without meta opens with a fallback title, no copy-path")

            # ================= 33.2 mutual exclusion + Esc + width + switch + focus =================
            # width-aware rule (Phase 34): at THIS narrow viewport the transcript can't fit both,
            # so opening one swaps the other — exactly the Phase 33 behavior (coexistence is
            # tested at a wide viewport in browser_phase34).
            page.click("#margin-toggle")                                 # open the margin
            page.wait_for_selector("#margin:not(.hidden)")
            assert hidden("#viewer"), "narrow viewport: opening the margin swaps out the viewer (Phase 34)"
            page.locator('.artifact.saved .artifact-btn:has-text("open")').click()   # open viewer
            page.wait_for_selector("#viewer:not(.hidden)")
            assert hidden("#margin"), "narrow viewport: opening the viewer swaps out the margin (Phase 34)"
            print("33.2/34 swap OK: at a narrow viewport the panes swap (coexistence → phase 34)")

            # Esc precedence: palette first, then the viewer
            page.keyboard.press("Control+k"); page.wait_for_selector("#palette-overlay:not(.hidden)")
            page.keyboard.press("Escape")
            page.wait_for_selector("#palette-overlay", state="hidden")
            assert not hidden("#viewer"), "first Esc closes the palette, NOT the viewer"
            page.keyboard.press("Escape")
            page.wait_for_selector("#viewer", state="hidden")
            print("33.2 esc OK: Esc closes palette first, then the viewer")

            # per-room width round-trip
            _json(f"/rooms/{doc}", "PUT", {"viewer_width": 620})
            assert _json(f"/rooms/{doc}").get("viewer_width") == 620, "viewer_width must round-trip through room.json"
            page.reload(wait_until="networkidle")
            page.locator('.room-row:has-text("docroom")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='docroom'")
            page.locator('.artifact.saved .artifact-btn:has-text("open")').click()
            page.wait_for_selector("#viewer:not(.hidden)")
            w = page.eval_on_selector("#viewer", "e => e.style.width")
            assert w == "620px", f"per-room viewer_width should apply on open: {w!r}"
            print("33.2 width OK: viewer_width persists per room and applies on open")

            # room switch closes the viewer; close refocuses the composer
            page.locator('.room-row:has-text("otherroom")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='otherroom'")
            assert hidden("#viewer"), "switching rooms closes the viewer"
            print("33.2 switch OK: changing rooms closes the viewer")

            page.locator('.room-row:has-text("docroom")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='docroom'")
            page.locator('.artifact.saved .artifact-btn:has-text("open")').click()
            page.wait_for_selector("#viewer:not(.hidden)")
            page.click("#viewer-close")
            page.wait_for_selector("#viewer", state="hidden")
            page.wait_for_function("document.activeElement && document.activeElement.id === 'input'", timeout=3000)
            print("33.2 close OK: closing the viewer refocuses the composer")

            # ================= 33.1 pending bubble alignment =================
            page.locator('.room-row:has-text("slowroom")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='slowroom'")
            page.select_option("#mode", "converse", force=True); page.select_option("#addressee", "mockslow")
            page.fill("#input", "pending-align-check"); page.click("#send-btn")
            page.wait_for_selector(".turn.pending", timeout=2500)
            px = page.locator(".turn.pending").bounding_box()["x"]
            rx = page.locator(".turn:not(.pending)").first.bounding_box()["x"]
            assert abs(px - rx) < 2, f"the pending bubble must be left-aligned like other turns (p={px}, r={rx})"
            print("33.1 pending OK: the optimistic bubble is left-aligned too")
            page.wait_for_selector(".turn.pending", state="detached", timeout=20000)

            br.close()
        print("\nPHASE 33 (artifact viewer pane): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
