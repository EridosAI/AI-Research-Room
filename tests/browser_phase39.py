"""browser_phase39.py — code pane + outbox UI smoke (Playwright, system python3).

  39B.1 code toggle enables with a room; pane opens/closes
  39B.2 outbox list renders pending crossings + approve
  39B.3 from_code note label in transcript

Run:  python3 tests/browser_phase39.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_TMP = tempfile.mkdtemp(prefix="rr-b39-")
_CFG = Path(_TMP) / "config.toml"
shutil.copy(REPO / "tests" / "config.toml", _CFG)
with _CFG.open("a", encoding="utf-8") as f:
    f.write("""
[providers.mockagent]
auth_mode = "api"
backend   = "agent"
model     = "openrouter/deepseek/deepseek-v4-flash"
enabled   = true
color     = "#67e8f9"
""")

PORT = 8799
env = os.environ.copy()
env["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
env["RESEARCH_ROOM_CONFIG"] = str(_CFG)
env["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
env["RESEARCH_ROOM_SECRETS"] = str(Path(_TMP) / "secrets.json")
env["RESEARCH_ROOM_UI"] = str(Path(_TMP) / "ui.json")
env["RESEARCH_ROOM_PORT"] = str(PORT)
BASE = f"http://127.0.0.1:{PORT}"

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0


def check(label, cond):
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}")
    if not cond:
        _fails += 1


def _json(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main() -> int:
    from playwright.sync_api import sync_playwright

    py = str(REPO / ".venv" / "bin" / "python")
    if not Path(py).is_file():
        py = sys.executable
    proc = subprocess.Popen(
        [py, "-m", "web.server"], cwd=str(REPO), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(BASE + "/rooms", timeout=1)
                break
            except Exception:
                time.sleep(0.2)
        else:
            print("server failed to start")
            return 1

        room = _json("/rooms", "POST", {"title": "phase39 browser"})
        rid = room["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {
            "participants": ["mock"], "code_seats": ["mockagent"],
            "channel_mode": "control", "judge": "mock",
        })
        # seed pending outbox via control-mode comment (server process sees same vault)
        # Use a small helper route-equivalent: import engine in-process against same env
        # by writing outbox through rooms.update on disk after channel module path —
        # instead hit approve after placing via channel in a one-shot using same env.
        seed = subprocess.run(
            [py, "-c",
             "import os,sys;"
             f"sys.path.insert(0,{str(REPO)!r});"
             + "".join(f"os.environ[{k!r}]={v!r};" for k, v in env.items()
                       if k.startswith("RESEARCH_ROOM_"))
             + f"from engine import channel;"
             f"channel.comment_to_main({rid!r},'pending note from code',wait=False);"
             "print('ok')"],
            capture_output=True, text=True, cwd=str(REPO), env=env)
        check("seeded outbox item", "ok" in (seed.stdout or "") + (seed.stderr or ""))

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("phase39")').click()
            page.wait_for_function("document.querySelector('#title').textContent.includes('phase39')")

            btn = page.locator("#code-toggle")
            check("code toggle exists", btn.count() == 1)
            check("code toggle enabled with room", not btn.is_disabled())
            btn.click()
            page.wait_for_timeout(400)
            pane = page.locator("#code-pane")
            check("code pane opens", not pane.evaluate("e => e.classList.contains('hidden')"))
            # 39.1 — seat dropdown lists ALL registry providers (not only assigned code_seats)
            opts = page.locator("#code-seat option").all_text_contents()
            real = [o for o in opts if o.strip() and o.strip() != "seat…"]
            check("seat dropdown has real seat option(s)", len(real) >= 1)
            check("seat dropdown includes mockagent", any("mockagent" in o for o in real))
            check("seat dropdown includes mock (full registry)", any(o.strip().startswith("mock") for o in real))
            # more than one real option when registry has several providers
            check("seat dropdown offers multiple seats", len(real) >= 2)
            # no broken "(undefined)" labels from a missing backend field
            check("no undefined backend labels", not any("undefined" in o for o in real))
            selected = page.locator("#code-seat").input_value()
            check("seat dropdown has a selection", bool(selected))
            page.select_option("#code-seat", "mockagent")
            page.wait_for_timeout(200)
            check("seat selection sticks on mockagent", page.locator("#code-seat").input_value() == "mockagent")
            meta = page.locator("#code-meta").inner_text()
            check("meta shows chosen seat", "mockagent" in meta)
            # can switch to another seat (any model)
            page.select_option("#code-seat", "mock")
            page.wait_for_timeout(200)
            check("can switch seat to mock", page.locator("#code-seat").input_value() == "mock")
            body = page.locator("#outbox-list").inner_text()
            check("outbox shows pending crossing", "pending note" in body or "comment_to_main" in body)
            check("channel-mode select present", page.locator("#channel-mode").count() == 1)
            page.click("#code-close")
            page.wait_for_timeout(200)
            check("code pane closes", page.locator("#code-pane").evaluate(
                "e => e.classList.contains('hidden')"))

            ob = _json(f"/rooms/{rid}/outbox")
            pending = [i for i in ob.get("outbox", []) if i.get("status") == "pending"]
            check("API lists pending outbox", len(pending) >= 1)
            if pending:
                ap = _json(f"/rooms/{rid}/outbox/{pending[0]['id']}/approve", "POST", {})
                check("approve via API returns item", "item" in ap)
                turns = (ap.get("transcript") or {}).get("turns") or []
                check("approved note has from_code",
                      any((t.get("meta") or {}).get("from_code") for t in turns))
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    print()
    print(f"{'ALL PASS' if _fails == 0 else f'{_fails} FAILED'}")
    return 0 if _fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
