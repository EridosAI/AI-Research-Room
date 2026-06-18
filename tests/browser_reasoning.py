"""browser_reasoning.py — visible reasoning in the UI (real headless Chromium).

  - a research round from a reasoning-emitting provider renders a COLLAPSED
    "thinking" disclosure under the panel card and the synthesis; it's folded by
    default and expands on click (same interaction as the margin's view-full);
  - the providers panel's per-provider "show reasoning" toggle round-trips to the
    registry.

Uses the `mockthink` fixture provider (mock backend, reasoning on) so it runs
offline at zero token cost.

Run:  python tests/browser_reasoning.py   (needs playwright + chromium)
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
PORT = 8816
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p11browser")


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
        rid = _json("/rooms", "POST", {"title": "reasoning room"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mockthink"], "judge": "mockthink"})

        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("reasoning room")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='reasoning room'")

            # --- research round → collapsed reasoning disclosures ---
            page.locator('input[name="mode"][value="research"]').check()
            page.fill("#input", "why is the sky blue?")
            page.click("#send-btn")
            page.wait_for_selector(".round .synthesis", timeout=30000)
            toggles = page.locator(".reasoning-toggle")
            assert toggles.count() >= 2, f"expected reasoning disclosures on panel + synthesis, got {toggles.count()}"
            # folded by default
            assert page.locator(".reasoning-body").first.is_hidden(), "reasoning should start collapsed"
            assert "thinking" in toggles.first.inner_text(), "disclosure not labelled 'thinking'"
            print(f"render OK: {toggles.count()} collapsed 'thinking' disclosures (panel + synthesis)")

            # one click expands it
            toggles.first.click()
            assert page.locator(".reasoning-body").first.is_visible(), "click did not expand reasoning"
            txt = page.locator(".reasoning-body").first.inner_text()
            assert "mock reasoning" in txt, f"reasoning content not rendered: {txt!r}"
            print("expand OK: click reveals the reasoning text")

            # --- providers panel: per-provider 'show reasoning' toggle round-trips ---
            assert _json("/providers")["providers"], "providers missing"
            before = next(p for p in _json("/providers")["providers"] if p["name"] == "mock")["reasoning"]
            assert before is False, "precondition: mock.reasoning should start false"
            page.click("#providers-btn")
            page.wait_for_selector('.pcard[data-name="mock"]')
            card = page.locator('.pcard[data-name="mock"]')
            card.locator('label:has-text("show reasoning") input[type=checkbox]').check()
            card.get_by_text("save", exact=True).click()
            page.wait_for_timeout(400)
            after = next(p for p in _json("/providers")["providers"] if p["name"] == "mock")["reasoning"]
            assert after is True, "reasoning toggle did not persist to the registry"
            print("toggle OK: providers panel 'show reasoning' persisted to the registry")
            b.close()
        print("\nVISIBLE REASONING (render + expand + toggle): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
