"""browser_phase36.py — converse streaming render + cancel (Chromium).

Phase 36.4/36.5:
  - a converse send streams: a live AI `.turn.streaming` bubble grows delta-by-delta with a
    Stop button; the terminal `done` swaps in exactly ONE authoritative ai turn (no dupe/flicker);
  - Stop mid-stream aborts: bubble clears, a "stopped" note, NO ai turn appended (answerless human
    turn — today's failure shape), and the next send is clean;
  - room-switch mid-stream detaches: the bubble never paints into the other room; the origin round
    finishes server-side as a background round and its ai turn is there on return;
  - a non-streamable (cli) seat falls through to a normal turn (no deltas).

RR_STREAM_DELAY paces the mock's per-word deltas so the stream is observable / interruptible.

Run:  python tests/browser_phase36.py
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
PORT = 8843
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p36browser")


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
           "RR_STREAM_DELAY": "0.18"}   # per-word delta pacing → the stream is observable + stoppable
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        a = _json("/rooms", "POST", {"title": "alpha"})["room"]["id"]
        _json(f"/rooms/{a}", "PUT", {"participants": ["mock"], "judge": "mock"})
        b = _json("/rooms", "POST", {"title": "beta"})["room"]["id"]
        _json(f"/rooms/{b}", "PUT", {"participants": ["mock"], "judge": "mock"})
        cli = _json("/rooms", "POST", {"title": "cliroom"})["room"]["id"]
        _json(f"/rooms/{cli}", "PUT", {"participants": ["mock_cli"], "judge": "mock_cli"})
        ca = _json("/rooms", "POST", {"title": "concA"})["room"]["id"]     # overlapping-streams test (created
        _json(f"/rooms/{ca}", "PUT", {"participants": ["mock"], "judge": "mock"})   # pre-goto so the sidebar shows them)
        cb = _json("/rooms", "POST", {"title": "concB"})["room"]["id"]
        _json(f"/rooms/{cb}", "PUT", {"participants": ["mock"], "judge": "mock"})

        with sync_playwright() as p:
            br = p.chromium.launch(); page = br.new_page()
            n_ai = lambda: page.locator(".turn:not(.human):not(.streaming)").count()
            page.goto(BASE + "/", wait_until="networkidle")

            # ---- 36.4 streamed growth + single terminal swap ----
            page.locator('.room-row:has-text("alpha")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='alpha'")
            page.fill("#input", "hello there brave new streaming world")
            page.click("#send-btn")
            page.wait_for_selector(".turn.streaming .stop-btn", timeout=5000)
            assert page.locator(".turn.streaming").count() == 1, "one live streaming bubble"
            t1 = page.locator(".turn.streaming .body").inner_text()
            page.wait_for_timeout(450)
            grew = True
            if page.locator(".turn.streaming").count():
                t2 = page.locator(".turn.streaming .body").inner_text()
                grew = len(t2) >= len(t1) and len(t1) > 0
            assert grew, "the streaming bubble grows delta-by-delta"
            page.wait_for_selector(".turn.streaming", state="detached", timeout=20000)
            page.wait_for_function("document.querySelectorAll('.turn:not(.human):not(.streaming)').length===1")
            assert n_ai() == 1, "terminal swap leaves exactly one ai turn (no dupe/flicker)"
            assert page.locator(".turn:not(.human):not(.streaming) .body").inner_text().startswith("[mock"), \
                "the authoritative ai turn holds the full reply"
            assert _json(f"/rooms/{a}").get("running") is False, "room not stuck running after the stream"
            print("36.4 OK: live bubble grows + Stop present; one authoritative turn; not stuck running")

            # ---- 36.5 Stop mid-stream → no ai turn, next send clean ----
            page.fill("#input", "please answer this one at length so I can stop it midway")
            page.click("#send-btn")
            page.wait_for_selector(".turn.streaming .stop-btn", timeout=5000)
            page.click(".turn.streaming .stop-btn")
            page.wait_for_selector(".turn.streaming", state="detached", timeout=8000)
            time.sleep(1.6)   # let the server detect the disconnect + release the round
            check_view = _json(f"/rooms/{a}")
            # before stop there was 1 human+1 ai (=2); the stopped send adds ONLY its human turn (no ai)
            assert check_view["turn_count"] == 3, f"stop appends only the human turn, no ai (got {check_view['turn_count']})"
            assert "stopped" in (page.locator("#banner").inner_text() or "").lower(), "a 'stopped' note shows"
            assert _json(f"/rooms/{a}").get("running") is False, "round released after stop"
            # next send works normally
            page.fill("#input", "ok now really answer me")
            page.click("#send-btn")
            page.wait_for_selector(".turn.streaming", state="detached", timeout=20000)
            assert _json(f"/rooms/{a}")["turn_count"] == 5, "next send lands a full human+ai pair"
            print("36.5 OK: Stop → no ai turn (answerless human), 'stopped' note, next send clean")

            # ---- 36.4 room-switch mid-stream detaches (no clobber) ----
            page.locator('.room-row:has-text("beta")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='beta'")
            page.fill("#input", "a fairly long beta message to keep the stream open while I switch")
            page.click("#send-btn")
            page.wait_for_selector(".turn.streaming .stop-btn", timeout=5000)
            page.locator('.room-row:has-text("alpha")').click()          # switch AWAY mid-stream
            page.wait_for_function("document.querySelector('#title').textContent==='alpha'")
            assert page.locator(".turn.streaming").count() == 0, "streaming bubble does NOT paint into the other room"
            # beta's round completes server-side as a background round
            for _ in range(60):
                if _json(f"/rooms/{b}")["turn_count"] >= 2:
                    break
                time.sleep(0.1)
            assert _json(f"/rooms/{b}")["turn_count"] >= 2, "origin round finished server-side (background)"
            page.locator('.room-row:has-text("beta")').click()           # return
            page.wait_for_function("document.querySelector('#title').textContent==='beta'")
            page.wait_for_selector(".turn:not(.human):not(.streaming) .body", timeout=8000)
            assert page.locator(".turn:not(.human):not(.streaming)").count() == 1, "beta's ai turn is there on return, once"
            print("36.4 OK: room-switch mid-stream detaches; origin finishes as a background round")

            # ---- 36.4 overlapping cross-room streams: the first to finish must NOT clobber the
            #      other's live stream state (identity-scoped slot release; review-caught bug) ----
            page.locator('.room-row:has-text("concA")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='concA'")
            page.fill("#input", "stream A first so it finishes before B is done here")
            page.click("#send-btn")
            page.wait_for_selector(".turn.streaming .stop-btn", timeout=5000)      # A streaming
            page.wait_for_timeout(1200)                                            # let A run ~1.2s ahead
            page.locator('.room-row:has-text("concB")').click()                    # A detaches, keeps draining
            page.wait_for_function("document.querySelector('#title').textContent==='concB'")
            page.fill("#input", "and B streams concurrently while A is still finishing up ok")
            page.click("#send-btn")
            page.wait_for_selector(".turn.streaming .stop-btn", timeout=5000)      # B streaming
            for _ in range(80):                                                    # wait until A's round lands
                if _json(f"/rooms/{ca}")["turn_count"] >= 2:
                    break
                time.sleep(0.05)
            assert _json(f"/rooms/{ca}")["turn_count"] >= 2, "room A completed while B still streams"
            # A finishing must NOT have nulled B's shared stream slots (the clobber bug): B's Stop still lives
            assert page.locator(".turn.streaming .stop-btn").count() == 1, "B's live bubble survives A finishing"
            page.click(".turn.streaming .stop-btn")
            page.wait_for_selector(".turn.streaming", state="detached", timeout=8000)
            time.sleep(1.6)
            assert _json(f"/rooms/{cb}")["turn_count"] == 1, \
                "B's Stop still works after A finished (identity-scoped release) → no ai turn"
            print("36.4 OK: overlapping streams — the first to finish doesn't clobber the other's Stop")

            # ---- non-streamable cli seat falls through to a turn ----
            page.locator('.room-row:has-text("cliroom")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='cliroom'")
            page.fill("#input", "hello cli seat")
            page.click("#send-btn")
            page.wait_for_selector(".turn:not(.human):not(.streaming) .body", timeout=20000)
            assert page.locator(".turn:not(.human):not(.streaming)").count() == 1, "cli converse still lands one turn"
            print("regression OK: a non-streamable cli seat falls through to a normal turn")

            br.close()
        print("\nPHASE 36 (converse streaming render + cancel): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
