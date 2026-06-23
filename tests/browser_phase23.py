"""browser_phase23.py — Cluster-1 surface wins in the UI (real headless Chromium).

  - 23.2 copy button: every output turn's footer has a copy button that copies the
    turn text (verified via the clipboard) with a "copied ✓" state;
  - 23.1 cost: the model-square popover has a Cost cell — "$0.00" for an OR seat,
    "free" for an off-OR (mock/proxy) seat;
  - 23.3 effort in converse: in converse mode the popover's effort selector is present
    for a seat that has options and a click persists to the room;
  - 23.4 context ring: each tile with a known window renders a coloured fill ring; the
    ramp (ringClass) shifts ok→warn→crit;
  - 23.5 OR dropdown: the add-model datalist populates from /or-models and picking a
    model seeds the new row's context window (route-stubbed so it runs offline).

Offline (mock converse, routed /or-models) — zero token cost.

Run:  python tests/browser_phase23.py
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
PORT = 8828
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p23browser")


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
        # mockthink gets a known window (for the ring); both seats join the room.
        _json("/providers/mockthink", "PUT", {"context_window": 200000})
        rid = _json("/rooms", "POST", {"title": "cluster1"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mockthink", "or_test"], "judge": "mockthink"})

        with sync_playwright() as p:
            b = p.chromium.launch()
            ctx = b.new_context(permissions=["clipboard-read", "clipboard-write"])
            page = ctx.new_page()
            # stub OpenRouter's catalog so the dropdown + seeding run offline
            page.route("**/or-models", lambda route: route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"models": [
                    {"id": "vendor/seed-model", "context_length": 123456, "reasoning": True,
                     "supported_efforts": ["low", "high"]}]})))
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("cluster1")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='cluster1'")

            # converse (mock, offline) → an output turn we can copy
            page.fill("#input", "hello there")
            page.click("#send-btn")
            page.wait_for_selector(".turn:not(.human) .turn-footer .copy-btn")
            print("render OK: output turn has a copy button")

            # --- 23.2 copy button copies the turn text ---
            turns = _json(f"/rooms/{rid}")["turns"]
            ai = next(t for t in turns if t["role"] == "ai")
            page.locator(".turn:not(.human) .copy-btn").first.click()
            page.wait_for_function(
                "document.querySelector('.turn:not(.human) .copy-btn').textContent.includes('copied')")
            clip = page.evaluate("navigator.clipboard.readText()")
            assert clip.strip() == ai["text"].strip(), "copy button should copy the turn text"
            print("copy OK: button copies the turn text and shows a copied state")

            # --- 23.4 context ring on the tile + ramp classes ---
            assert page.locator('.model-square[data-model="mockthink"] .ctx-ring').count() == 1, \
                "a tile with a known window should render a context ring"
            ramp = page.evaluate("[ringClass(0.5), ringClass(0.7), ringClass(0.95)]")
            assert ramp == ["ok", "warn", "crit"], f"ring colour ramp wrong: {ramp}"
            print("ring OK: tile shows a context ring; ramp shifts ok→warn→crit")

            # --- 23.1 cost cell + 23.3 effort selector in CONVERSE mode ---
            assert page.eval_on_selector("#mode", "el => el.value") == "converse", "default mode is converse"
            page.locator('.model-square[data-model="or_test"]').click()           # OR seat popover
            page.wait_for_selector("#model-popover:not(.hidden)")
            pop = page.locator("#model-popover")
            assert "Cost" in pop.inner_text(), "popover should have a Cost cell"
            assert "$0.00" in pop.inner_text(), "OR seat with no spend shows $0.00"
            seg = pop.locator(".mp-effort .mp-seg button")
            assert seg.count() >= 2, "effort selector should be present in converse mode (OR seat)"
            print("cost+effort OK: popover shows Cost ($0.00 OR) + effort selector in converse")

            # clicking an effort persists to the room (affects the next converse turn)
            seg.filter(has_text="high").first.click()
            page.wait_for_timeout(150)
            eff = _json(f"/rooms/{rid}").get("reasoning_effort", {})
            assert eff.get("or_test") == "high", f"effort click should persist to room.json, got {eff}"
            print("effort-persist OK: converse-mode effort click writes room.json")

            # an off-OR seat shows "free"
            page.locator('.model-square[data-model="mockthink"]').click()
            page.wait_for_selector("#model-popover:not(.hidden)")
            assert "free" in page.locator("#model-popover").inner_text(), "off-OR seat shows free cost"
            print("free OK: off-OR (mock) seat shows free in the cost cell")

            # --- 23.5 OR model dropdown + metadata-seeded add ---
            page.click("#providers-btn")
            page.wait_for_selector("#providers-overlay:not(.hidden)")
            page.wait_for_function(
                "document.querySelectorAll('#add-model-list option').length > 0")
            assert page.locator('#add-model-list option[value="vendor/seed-model"]').count() == 1, \
                "the add-model datalist should populate from /or-models"
            page.fill("#add-name", "seeded")
            page.fill("#add-base", "https://openrouter.ai/api/v1")
            page.fill("#add-model", "vendor/seed-model")
            page.click("#add-btn")
            page.wait_for_selector('.pcard[data-name="seeded"]')
            # the seeded row carries the catalog's context window
            win = _json("/providers")
            row = next(p for p in win["providers"] if p["name"] == "seeded")
            assert row["context_window"] == 123456, f"add should seed context_window, got {row}"
            assert row["reasoning"] is True, "add should seed reasoning from the catalog"
            print("dropdown OK: datalist from /or-models; picking a model seeds window + reasoning")

            ctx.close(); b.close()
        print("\nPHASE 23 (Cluster-1 surface wins): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
