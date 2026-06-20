"""browser_phase17.py — web-search sources disclosure (real headless Chromium).

  - a search-enabled panelist's turn shows a collapsed "sources (N)" disclosure in
    the .turn-footer (beside thinking/model), expanding to the sources;
  - links are scheme-allowlisted: http(s) sources get a real href (target/rel set);
    a javascript: source is rendered blocked, with NO href (the safeLink guard);
  - absent when there are no sources.

Uses the `mocksearch` fixture (mock backend, web_search on) so it runs offline —
mock emits one https source + one javascript: source to exercise the allowlist.

Run:  python tests/browser_phase17.py   (needs playwright + chromium)
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
PORT = 8822
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p17browser")


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
        rid = _json("/rooms", "POST", {"title": "sources room"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mocksearch"], "judge": "mocksearch"})

        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("sources room")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='sources room'")

            # --- guards on the helpers (allowlist + absence) ---
            assert page.evaluate("sourcesOf({}).length === 0"), "sourcesOf should be empty on bare meta"
            assert page.evaluate("safeLink('https://x.com','t').getAttribute('href') === 'https://x.com'"), \
                "http(s) link should get an href"
            assert page.evaluate("!safeLink('javascript:alert(1)','t').hasAttribute('href')"), \
                "javascript: link must NOT get an href"
            print("guard OK: scheme allowlist (http(s) href, javascript: blocked) + empty-meta absence")

            # --- research round → 'sources (N)' disclosure in the footer ---
            page.locator('input[name="mode"][value="research"]').check()
            page.fill("#input", "state of optical computing?")
            page.click("#send-btn")
            page.wait_for_selector(".round .synthesis", timeout=30000)

            footer = page.locator(".round .turn-footer").first
            toggle = footer.locator(".sources-toggle")
            assert toggle.count() == 1, "footer missing the sources disclosure"
            assert "sources (2)" in toggle.inner_text(), f"unexpected sources label: {toggle.inner_text()!r}"
            print("render OK: 'sources (2)' disclosure sits in the turn footer")

            # --- expand → safe links only ---
            assert page.locator(".round .sources-body").first.is_hidden(), "sources should start collapsed"
            toggle.click()
            body = page.locator(".round .sources-body").first
            assert body.is_visible(), "click did not expand the sources"
            hrefed = body.locator("a.source-link[href]")
            assert hrefed.count() == 1, f"expected exactly 1 clickable (http) link, got {hrefed.count()}"
            assert hrefed.first.get_attribute("href") == "https://example.com/a", "wrong source href"
            assert hrefed.first.get_attribute("target") == "_blank", "external link should open in a new tab"
            assert "noopener" in (hrefed.first.get_attribute("rel") or ""), "external link missing rel=noopener"
            assert body.locator("a.source-link.blocked").count() == 1, "javascript: source should render blocked"
            assert body.locator('a[href^="javascript"]').count() == 0, "javascript: must never become an href"
            print("expand OK: http(s) link clickable (target/rel set); javascript: blocked, no href")
            b.close()
        print("\nPHASE 17 (web-search sources disclosure): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
