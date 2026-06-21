"""browser_phase22.py — inline file drop (.md / .txt) in the composer (real Chromium).

  - picking a .md / .txt stages a removable chip in the composer; ✕ removes it;
  - a non-text file is rejected with a friendly note and does NOT stage;
  - sending with a staged file + EMPTY message posts a file-turn (no model call),
    rendered as a collapsed chip that expands to show the content;
  - the expanded .md content goes through the SANITIZED path — an onerror payload in
    the file does not execute (window.__pwned stays undefined).

Offline (no model call on a files-only send) — zero token cost.

Run:  python tests/browser_phase22.py   (needs playwright + chromium)
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
PORT = 8827
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p22browser")


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
    # files to pick from the composer
    md = HOME / "doc.md"
    md.write_text("# Heading\n\n<img src=x onerror=\"window.__pwned=1\">\n\nSAFE_MD_MARKER\n", encoding="utf-8")
    bad = HOME / "evil.exe"
    bad.write_text("nope", encoding="utf-8")

    env = {**os.environ,
           "RESEARCH_ROOM_CONFIG": str(HOME / "config.toml"), "RESEARCH_ROOM_HOME": str(HOME),
           "RESEARCH_ROOM_SECRETS": str(HOME / "secrets.json"), "RESEARCH_ROOM_VAULT": str(HOME / "vault"),
           "RESEARCH_ROOM_PORT": str(PORT)}
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        rid = _json("/rooms", "POST", {"title": "file room"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mockthink"], "judge": "mockthink"})

        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('.room-row:has-text("file room")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='file room'")

            # --- pick a .md → a removable chip stages (not sent) ---
            page.set_input_files("#file-input", str(md))
            page.wait_for_selector("#staged-files .file-chip")
            assert page.locator("#staged-files .file-chip").count() == 1, "the .md should stage one chip"
            assert "doc.md" in page.locator("#staged-files .file-chip-name").inner_text()
            assert page.locator(".round, .turn").count() == 0, "nothing should be in the transcript yet"
            print("stage OK: picking a .md stages a removable chip, nothing sent")

            # --- ✕ removes the chip ---
            page.locator("#staged-files .file-chip-x").click()
            page.wait_for_function("document.querySelectorAll('#staged-files .file-chip').length===0")
            assert "hidden" in (page.locator("#staged-files").get_attribute("class") or ""), \
                "empty staging area should hide"
            print("remove OK: ✕ clears the staged chip")

            # --- a non-text file is rejected (banner) and does NOT stage ---
            page.set_input_files("#file-input", str(bad))
            page.wait_for_function(
                "!document.querySelector('#banner').classList.contains('hidden')")
            assert "text files only" in page.locator("#banner").inner_text().lower(), \
                "non-text file should warn 'text files only'"
            assert page.locator("#staged-files .file-chip").count() == 0, "non-text file must not stage"
            print("reject OK: a non-text file is refused and does not stage")

            # --- send with a staged file + EMPTY message → a file-turn (no model call) ---
            page.set_input_files("#file-input", str(md))
            page.wait_for_selector("#staged-files .file-chip")
            assert page.locator("#input").input_value() == "", "input is empty for this send"
            page.click("#send-btn")
            page.wait_for_selector(".file-turn")
            assert page.locator(".file-turn").count() == 1, "a files-only send posts one file-turn"
            assert page.locator("#staged-files .file-chip").count() == 0, "staging clears after send"
            head = page.locator(".file-turn .file-turn-name").inner_text()
            assert "doc.md" in head, f"the file-turn chip should name the file, got {head!r}"
            # it's a chip, not a sprawled message bubble
            assert page.locator(".file-turn .file-turn-body").first.is_hidden(), "content starts collapsed"
            print("send OK: empty-message + file posts a collapsed file-turn chip")

            # --- expand → content shows via the SAFE path (onerror neutralized) ---
            page.locator(".file-turn .file-turn-head").click()
            page.wait_for_selector(".file-turn .file-turn-body:not(.hidden)")
            assert "SAFE_MD_MARKER" in page.locator(".file-turn .file-turn-body").inner_text(), \
                "expanded body should show the file content"
            assert page.evaluate("window.__pwned") in (None, False), \
                "onerror payload in the file must NOT execute (sanitized render)"
            print("safe-render OK: content expands; embedded onerror does not fire")

            b.close()
        print("\nPHASE 22 (inline file drop): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
