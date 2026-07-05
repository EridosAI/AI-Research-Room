"""Phase 6 visual Done-when — drives a real headless Chromium against the live
server (mock fixture). Exercises: composite research render, view-full expand,
converse sanitization (XSS payload neutralized), and DOMPurify fail-closed.
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
PORT = 8806
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p6")


def _json(path, method="GET", body=None):
    import json
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"Content-Type": "application/json"} if body is not None else {}
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        BASE + path, data=data, headers=hdr, method=method), timeout=10).read() or "{}")


def seed_room(title):
    """Create a room and give it the full enabled roster + the global judge — the
    real /rooms path, replacing the retired seeded /transcript shim."""
    rid = _json("/rooms", "POST", {"title": title})["room"]["id"]
    part = _json("/participants")
    enabled = [p["name"] for p in part["participants"] if p["enabled"]]
    _json(f"/rooms/{rid}", "PUT", {"participants": enabled, "judge": part["research_judge"]})
    return rid


def wait_up():
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/rooms", timeout=2); return
        except Exception:
            time.sleep(0.2)
    raise SystemExit("server did not start")


def main():
    import shutil
    shutil.rmtree(HOME, ignore_errors=True)
    (HOME / "vault").mkdir(parents=True)
    shutil.copy(REPO / "tests" / "config.toml", HOME / "config.toml")
    env = {**os.environ,
           "RESEARCH_ROOM_CONFIG": str(HOME / "config.toml"),
           "RESEARCH_ROOM_HOME": str(HOME),
           "RESEARCH_ROOM_SECRETS": str(HOME / "secrets.json"),
           "RESEARCH_ROOM_VAULT": str(HOME / "vault"),
           "RESEARCH_ROOM_PORT": str(PORT)}
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        seed_room("browser test")   # pre-create + configure the active room

        with sync_playwright() as p:
            browser = p.chromium.launch()

            # ---------- main page (CDN allowed) ----------
            page = browser.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            assert page.evaluate("typeof window.DOMPurify") != "undefined", "DOMPurify did not load"
            assert page.evaluate("typeof window.marked") != "undefined", "marked did not load"
            print("libs loaded (marked + DOMPurify)")

            # --- research round → composite block ---
            page.select_option("#mode", "fusion", force=True)
            page.fill("#input", "Pick a vector index for 10M embeddings")
            page.click("#send-btn")
            page.wait_for_selector(".round .synthesis", timeout=30000)
            n_panels = page.locator(".round .panel").count()
            assert n_panels == 2, f"expected 2 panel cards (mock, mock_cli), got {n_panels}"
            assert page.locator(".round .synthesis").count() == 1, "synthesis missing"
            # searched marker present on the cli panelist, absent on the api/mock one
            searched = page.locator(".panel .badge.searched").count()
            assert searched == 1, f"expected 1 'searched' marker (mock_cli), got {searched}"
            print(f"composite render OK: {n_panels} cards + synthesis; 'searched' marker on cli panelist")

            # --- view full expands the stored raw ---
            first_full = page.locator(".panel .full").first
            assert not first_full.is_visible(), "raw should start collapsed"
            page.locator(".panel .viewfull").first.click()
            assert first_full.is_visible(), "view full did not expand the raw answer"
            assert "MOCK ANSWER" in first_full.inner_text() or first_full.inner_text(), "raw text empty"
            print("view full OK: collapsed → expanded stored raw")

            # --- converse with an XSS payload → must be sanitized ---
            page.select_option("#mode", "converse", force=True)
            page.select_option("#addressee", "mock")
            page.fill("#input", '<img src=x onerror="window.__xss=1"> hi')
            page.click("#send-btn")
            page.wait_for_selector("text=[mock:mock/mock-1]", timeout=15000)
            page.wait_for_timeout(300)   # let any (sanitized-away) handler have a chance
            assert page.evaluate("window.__xss") in (None, False), "XSS executed — onerror fired!"
            has_onerror = page.evaluate(
                "[...document.querySelectorAll('#stream *')].some(e=>e.getAttribute && e.getAttribute('onerror'))")
            assert has_onerror is False, "onerror attribute survived sanitization"
            assert page.locator("#stream script").count() == 0, "a <script> survived into the DOM"
            print("sanitization OK: onerror stripped, no script node, window.__xss not set")

            # ---------- fail-closed page (CDN blocked) ----------
            ctx = browser.new_context()
            ctx.route("**/cdn.jsdelivr.net/**", lambda route: route.abort())
            fpage = ctx.new_page()
            fpage.goto(BASE + "/", wait_until="load")
            fpage.wait_for_timeout(500)
            assert fpage.evaluate("typeof window.DOMPurify") == "undefined", "DOMPurify loaded despite CDN block"
            assert not fpage.locator("#banner").is_hidden(), "fail-closed banner not shown"
            fpage.select_option("#mode", "converse", force=True)
            fpage.select_option("#addressee", "mock")
            fpage.fill("#input", '<img src=x onerror="window.__xss3=1"> hello')
            fpage.click("#send-btn")
            fpage.wait_for_selector("text=[mock:mock/mock-1]", timeout=15000)
            fpage.wait_for_timeout(300)
            assert fpage.evaluate("window.__xss3") in (None, False), "XSS executed under fail-closed!"
            assert fpage.locator("#stream img").count() == 0, "img element created — not plain text (fail-open!)"
            body_text = fpage.locator("#stream").inner_text()
            assert "<img" in body_text, "payload not rendered as literal text under fail-closed"
            print("fail-closed OK: libs absent → plain text, no img node, no execution, banner shown")

            browser.close()
        print("\nPHASE 6 BROWSER DONE-WHEN: ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
