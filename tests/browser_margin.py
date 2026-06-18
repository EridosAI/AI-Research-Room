"""browser_margin.py — the margin under real use (server + headless Chromium).

Two gates flagged for Phase 10, plus the UI loop:
  - CONCURRENCY (flag 3): a margin question in a room runs WHILE a slow research
    round is in flight in that SAME room — it must not queue behind the main
    lock. Asserted at the server level with real concurrent HTTP.
  - the margin UI: open the panel, ask a side-question, see it render; switching
    rooms shows that room's OWN margin (not the previous room's).
  - COPY-TO-MAIN (flag 4): exactly one attributed turn lands in main; the margin
    file is unchanged (copy, not move). Isolation re-checked on disk.
  - splitter width + margin model persist to room.json.

Run:  python tests/browser_margin.py   (needs playwright + chromium)
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
PORT = 8815
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p10margin")
DELAY = 5   # seconds the slow main round sleeps


def req(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    r = urllib.request.urlopen(
        urllib.request.Request(BASE + path, data=data, headers=headers, method=method), timeout=30)
    return json.loads(r.read() or "{}")


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
        room = req("/rooms", "POST", {"title": "margin room"})["room"]["id"]
        req(f"/rooms/{room}", "PUT",
            {"participants": ["mockslow", "mock"], "judge": "mock", "margin_model": "mock"})

        # --- 1. CONCURRENCY: margin answers while a slow main round runs ------
        timings = {}

        def slow_round():
            t0 = time.time()
            req(f"/rooms/{room}/research", "POST", {"prompt": "slow main round", "effort": "low"})
            timings["research_done"] = time.time() - t0

        th = threading.Thread(target=slow_round); th.start()
        time.sleep(0.6)                     # let the round acquire the main lock + start sleeping
        m0 = time.time()
        mres = req(f"/rooms/{room}/margin", "POST",
                   {"prompt": "what is this round about?", "window": "last_1", "model": "mock"})
        margin_done = time.time() - m0
        research_running = "research_done" not in timings
        assert mres.get("answer"), "margin returned no answer"
        assert research_running, "main round already finished — widen DELAY for a real window"
        assert margin_done < DELAY, f"margin waited on the main round ({margin_done:.1f}s) — it's under the main lock!"
        print(f"concurrency OK: margin answered in {margin_done:.2f}s while the {DELAY}s main round was still running")
        th.join()

        # isolation on disk: the margin Q&A never entered main
        main_turns = req(f"/rooms/{room}")["turns"]
        assert all(t.get("mode") != "margin" for t in main_turns), "margin turn leaked into main.jsonl"
        assert len(req(f"/rooms/{room}")["margin_turns"]) == 2, "margin Q&A not stored"
        print("isolation OK (disk): margin exchange absent from main.jsonl")

        # --- 2. UI: open margin, ask, switch-room shows the right margin ------
        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("margin room")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='margin room'")
            page.click("#margin-toggle")
            page.wait_for_selector("#margin:not(.hidden)")
            assert page.locator(".margin-turn.a").count() == 1, "existing margin answer not rendered"

            # ask a new side-question from the UI
            page.fill("#margin-input", "and who answered it?")
            page.click("#margin-send")
            page.wait_for_function("document.querySelectorAll('.margin-turn.a').length === 2", timeout=20000)
            print("margin UI OK: side-question asked and rendered in the margin panel")

            # switching rooms shows that room's own (empty) margin
            r2 = req("/rooms", "POST", {"title": "second room"})["room"]["id"]
            req(f"/rooms/{r2}", "PUT", {"participants": ["mock"], "judge": "mock", "margin_model": "mock"})
            page.reload(wait_until="networkidle")   # pick up the new room in the sidebar
            page.locator('.room-row:has-text("second room")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='second room'")
            page.click("#margin-toggle")
            page.wait_for_selector("#margin:not(.hidden)")
            assert page.locator(".margin-turn").count() == 0, "second room shows another room's margin"
            page.locator('.room-row:has-text("margin room")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='margin room'")
            assert page.locator(".margin-turn.a").count() == 2, "switching back lost this room's margin"
            print("per-room margin OK: each room shows its own margin")

            # --- 3. COPY-TO-MAIN: exactly one attributed turn -----------------
            main_before = len(req(f"/rooms/{room}")["turns"])
            margin_before = len(req(f"/rooms/{room}")["margin_turns"])
            page.locator(".margin-turn.a .promote-btn").first.click()
            page.wait_for_function(
                f"document.querySelectorAll('#stream .turn').length >= 1", timeout=10000)
            page.wait_for_timeout(300)
            main_after = req(f"/rooms/{room}")["turns"]
            assert len(main_after) == main_before + 1, "promote did not append exactly one main turn"
            note = main_after[-1]
            assert note["role"] == "note" and (note.get("meta") or {}).get("from_margin"), "promoted turn not attributed"
            assert len(req(f"/rooms/{room}")["margin_turns"]) == margin_before, "promote mutated margin.jsonl (should copy)"
            assert page.locator('#stream .turn .who:has-text("from margin")').count() >= 1, "no 'from margin' attribution in the UI"
            print("copy-to-main OK: exactly one attributed turn into main; margin unchanged")

            # --- 4. persistence: splitter width + margin model in room.json ---
            bb = page.locator("#margin-splitter").bounding_box()
            cx, cy = bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2
            page.mouse.move(cx, cy); page.mouse.down()
            page.mouse.move(cx - 160, cy, steps=5); page.mouse.up()   # drag left → widen margin
            page.wait_for_timeout(300)
            rj = req(f"/rooms/{room}")
            assert rj["splitter_width"] and rj["splitter_width"] > 340, "splitter width not persisted to room.json"
            assert rj["margin_model"] == "mock", "margin model not persisted to room.json"
            print("persistence OK: splitter width + margin model saved in room.json")
            b.close()
        print("\nMARGIN (concurrency + UI + copy-to-main + persistence): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
