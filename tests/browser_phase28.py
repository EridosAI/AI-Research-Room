"""browser_phase28.py — model-pill metadata popover + inert effort-dial guard (Chromium).

  - hovering an output turn's model pill opens a popover with the turn's metadata —
    Thinking (requested level), Reasoning (actual tokens), Tokens, Finish — and a
    "view thinking" button that reveals the trace;
  - a model whose reasoning toggle is OFF shows its effort dial greyed + a note
    (the RR Loom 4 trap: the dial was settable but inert).

Offline (mock seats) — zero token cost.

Run:  python tests/browser_phase28.py
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
PORT = 8834
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p28browser")


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
        # or_test has an effort dial (config supported_efforts) — turn its reasoning OFF to
        # exercise the inert-dial guard. mockthink (reasoning on) feeds the pill popover.
        _json("/providers/or_test", "PUT", {"reasoning": False})
        rid = _json("/rooms", "POST", {"title": "meta"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mockthink", "or_test"], "judge": "mockthink",
                                       "reasoning_effort": {"mockthink": "high"}})

        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("meta")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='meta'")

            # --- a converse turn with reasoning (mockthink) ---
            page.select_option("#mode", "converse", force=True)
            page.select_option("#addressee", "mockthink")
            page.fill("#input", "think about caching")
            page.click("#send-btn")
            page.wait_for_selector(".turn:not(.human) .model-pill")

            # --- 28.4 hover the pill → metadata popover ---
            page.locator(".turn:not(.human) .model-pill").first.hover()
            page.wait_for_selector("#turn-popover:not(.hidden)")
            pop = page.locator("#turn-popover").inner_text()
            for token in ("Thinking", "high", "Reasoning", "Tokens"):
                assert token in pop, f"turn popover missing {token!r}: {pop!r}"
            assert "mockthink-1" in pop, f"popover should head with the served model: {pop!r}"
            print("popover OK: shows Thinking=high, Reasoning, Tokens, served model")

            # --- view thinking button reveals the trace ---
            assert page.locator("#turn-popover .tp-view").count() == 1, "popover should offer 'view thinking'"
            page.locator("#turn-popover .tp-view").click()
            assert page.locator(".turn:not(.human) .reasoning-body").first.is_visible(), \
                "'view thinking' should reveal the reasoning trace"
            print("view-thinking OK: button reveals the reasoning trace")

            # --- 28.5 inert effort-dial guard on the reasoning-OFF model (or_test) ---
            page.locator('.model-square[data-model="or_test"]').click()
            page.wait_for_selector("#model-popover:not(.hidden)")
            assert page.locator("#model-popover .mp-effort.off").count() == 1, \
                "reasoning-off model should show the dial greyed (.mp-effort.off)"
            assert "reasoning off" in page.locator("#model-popover .mp-note").inner_text().lower(), \
                "an inert dial should carry the 'reasoning off' note"
            assert page.locator("#model-popover .mp-seg button").first.is_disabled(), \
                "the inert dial's buttons should be disabled"
            print("guard OK: reasoning-off model shows a greyed, disabled effort dial + note")

            # sanity: a reasoning-ON model's dial is still live (not greyed)
            _json("/providers/or_test", "PUT", {"reasoning": True})
            page.reload(); page.wait_for_function("document.querySelector('#title') && document.querySelector('#title').textContent==='meta'")
            page.locator('.model-square[data-model="or_test"]').click()
            page.wait_for_selector("#model-popover:not(.hidden)")
            assert page.locator("#model-popover .mp-effort.off").count() == 0, "reasoning-on dial must not be greyed"
            assert not page.locator("#model-popover .mp-seg button").first.is_disabled(), "reasoning-on dial is live"
            print("live OK: re-enabling reasoning restores a working dial")

            b.close()
        print("\nPHASE 28 (turn metadata popover + inert effort-dial guard): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
