"""browser_phase20.py — model-square bar + reasoning selector + composer split.

  20.4: a .model-square per active panelist (dot + token count); hover opens an
        extensible popover; the effort selector lists the model's effort_options for
        an OpenRouter row and is ABSENT for a no-effort model (mock); changing effort
        persists to room.json and survives reload.
  20.5: the transcript↔composer divider drags to resize the composer height, and the
        height persists across reload (ui.json), localStorage empty.

Run:  python tests/browser_phase20.py   (needs playwright + chromium)
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
PORT = 8824
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p20browser")


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
           "RESEARCH_ROOM_UI": str(HOME / "ui.json"), "RESEARCH_ROOM_PORT": str(PORT)}
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        rid = _json("/rooms", "POST", {"title": "p20 room"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mock", "or_test"], "judge": "mock"})

        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("p20 room")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='p20 room'")

            # --- 20.4: a square per panelist (dot + token count) ---
            page.wait_for_selector('#token-bar .model-square[data-model="or_test"]')
            assert page.locator("#token-bar .model-square").count() == 2, "expected a square per panelist"
            assert page.locator('#token-bar .model-square[data-model="mock"] .dot').count() == 1, "square missing its dot"
            print("20.4 OK: model-square bar shows a tile (dot + tokens) per panelist")

            # --- popover: effort buttons come from THIS model's metadata (not a fixed trio) ---
            page.hover('#token-bar .model-square[data-model="or_test"]')
            page.wait_for_function("!document.querySelector('#model-popover').classList.contains('hidden')")
            seg = page.locator("#model-popover .mp-seg button")
            labels = [seg.nth(i).inner_text() for i in range(seg.count())]
            assert labels == ["high", "xhigh"], f"effort options must come from supported_efforts (ascending): {labels}"
            pop = page.locator("#model-popover").inner_text()
            assert "via OpenRouter" in pop, "header subtitle (via OpenRouter) missing"
            assert "glm-5.2" in pop and "z-ai/" not in pop, f"header should strip the provider/ prefix: {pop!r}"
            for stat in ("Tokens", "Share of room", "Context"):
                assert stat in pop, f"stat row {stat!r} missing from popover"
            # (Phase 20 shipped no Cost row; Phase 23 added a real one — see browser_phase23.)
            print("20.4 OK: metadata-driven efforts [high, xhigh] + header + one-line stats")

            page.hover('#token-bar .model-square[data-model="mock"]')
            page.wait_for_timeout(150)
            assert page.locator("#model-popover .mp-seg").count() == 0, "mock (no effort) must omit the selector"
            print("20.4 OK: effort selector ABSENT for the no-effort model (mock)")

            # --- changing effort persists to room.json ---
            page.hover('#token-bar .model-square[data-model="or_test"]')
            page.wait_for_function("!document.querySelector('#model-popover').classList.contains('hidden')")
            page.click('#model-popover .mp-seg button:has-text("xhigh")')
            page.wait_for_timeout(250)
            assert _json(f"/rooms/{rid}")["reasoning_effort"].get("or_test") == "xhigh", "effort not persisted to room.json"
            print("20.4 OK: selecting effort persists per-room (or_test → xhigh)")

            # --- 20.5: drag the transcript↔composer divider to resize, persists on reload ---
            h0 = page.eval_on_selector(".composer", "el => el.getBoundingClientRect().height")
            box = page.locator("#composer-resizer").bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.down(); page.mouse.move(box["x"] + box["width"] / 2, box["y"] - 140); page.mouse.up()
            page.wait_for_timeout(150)
            h1 = page.eval_on_selector(".composer", "el => el.getBoundingClientRect().height")
            assert h1 > h0 + 40, f"composer did not grow on drag: {h0} -> {h1}"
            saved = _json("/ui").get("composer_height")
            assert saved and saved > h0, f"composer_height not persisted: {saved!r}"
            assert page.evaluate("window.localStorage.length") == 0, "localStorage used (forbidden)"
            print(f"20.5 OK: divider resized composer {round(h0)}→{round(h1)}px, persisted ({round(saved)})")

            # --- reload: effort + composer height reconstruct from server state ---
            page.reload(wait_until="networkidle")
            page.wait_for_selector('#token-bar .model-square[data-model="or_test"]')
            h2 = page.eval_on_selector(".composer", "el => el.getBoundingClientRect().height")
            assert abs(h2 - h1) < 12, f"composer height not restored after reload: {h1} -> {h2}"
            page.hover('#token-bar .model-square[data-model="or_test"]')
            page.wait_for_function("!document.querySelector('#model-popover').classList.contains('hidden')")
            sel = page.locator("#model-popover .mp-seg button.sel").inner_text()
            assert sel == "xhigh", f"effort 'xhigh' not restored after reload (sel={sel!r})"
            assert page.evaluate("window.localStorage.length") == 0, "localStorage populated after reload"
            print("reload OK: effort + composer height reconstruct from server, localStorage empty")
            b.close()
        print("\nPHASE 20 (model-square bar + reasoning selector + composer split): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
