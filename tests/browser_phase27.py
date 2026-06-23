"""browser_phase27.py — round provenance label + undo-last-round button (Chromium).

  - a round shows its mode on the prompt line, and "· panel saw chat" when the panel
    context toggle was on;
  - the "↶ undo round" button removes the last round from the transcript (and re-enables
    sending), with the removed turns recoverable server-side.

Offline (mock seats) — zero token cost. Auto-accepts the confirm() dialog.

Run:  python tests/browser_phase27.py
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
PORT = 8832
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p27browser")


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
        rid = _json("/rooms", "POST", {"title": "prov"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mock", "mockthink"], "judge": "mock"})

        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.on("dialog", lambda d: d.accept())          # auto-accept the rollback confirm
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("prov")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='prov'")

            # the undo button is disabled in an empty room
            assert page.locator("#rollback-btn").is_disabled(), "undo disabled with no turns"

            # --- run a side-by-side with 'panel sees conversation' on ---
            page.select_option("#mode", "side_by_side")
            page.check('#sxs-pick input[value="mock"]')
            page.check('#sxs-pick input[value="mockthink"]')
            page.check("#sxs-context")                        # panel sees conversation
            page.fill("#input", "Compare caching approaches.")
            page.click("#send-btn")
            page.wait_for_selector(".round .synthesis", timeout=30000)

            # --- 27.1 provenance label on the round's prompt line ---
            who = page.locator(".round .prompt .who").inner_text()
            assert "side-by-side" in who, f"round should show its mode: {who!r}"
            assert "panel saw chat" in who, f"transcript toggle should show on the round: {who!r}"
            print("provenance OK: round labelled 'side-by-side · panel saw chat'")

            # --- 27.2 undo the round ---
            assert not page.locator("#rollback-btn").is_disabled(), "undo enabled with a round present"
            before = len(_json(f"/rooms/{rid}")["turns"])
            page.click("#rollback-btn")
            page.wait_for_function("!document.querySelector('#banner').classList.contains('hidden')")
            assert "Rolled back" in page.locator("#banner").inner_text(), "rollback banner shown"
            page.wait_for_selector(".round", state="detached", timeout=5000)   # the round is gone
            after = _json(f"/rooms/{rid}")["turns"]
            assert len(after) == before - 4, f"side-by-side round (4 turns) removed: {before}->{len(after)}"
            assert page.locator("#rollback-btn").is_disabled(), "undo disabled again (room empty)"
            print(f"undo OK: removed the {before - len(after)}-turn round; button re-disabled")

            # removed turns are recoverable server-side
            rb = HOME / "vault" / rid / "rolledback.jsonl"
            assert rb.is_file() and rb.read_text().strip(), "removed turns preserved in rolledback.jsonl"
            print("recover OK: removed turns preserved in rolledback.jsonl")

            b.close()
        print("\nPHASE 27 (round provenance + undo last round): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
