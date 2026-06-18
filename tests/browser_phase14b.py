"""browser_phase14b.py — Phase 14 C/D/E in a real headless Chromium (mock fixture).

  14C: token-chip checkboxes toggle the estimate + model-% pieces and persist;
       model % reads from stored usage (mock → ~ estimate).
  14D: a ```markdown block in a response shows copy + save; copy puts the raw .md
       on the clipboard; save writes a collision-safe .md to the artifacts dir.
  14E: hovering a sidebar room shows models + both dates + a truncated summary,
       instantly, no model call; dismisses on mouse-leave.

Run:  python tests/browser_phase14b.py   (needs playwright + chromium)
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
PORT = 8820
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p14b")
ARTIFACT_BLOCK = "# Plan\n- step one\n- step two"


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
    adir = HOME / "artifacts"
    env = {**os.environ,
           "RESEARCH_ROOM_CONFIG": str(HOME / "config.toml"), "RESEARCH_ROOM_HOME": str(HOME),
           "RESEARCH_ROOM_SECRETS": str(HOME / "secrets.json"), "RESEARCH_ROOM_VAULT": str(HOME / "vault"),
           "RESEARCH_ROOM_UI": str(HOME / "ui.json"), "RESEARCH_ROOM_PORT": str(PORT)}
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        rid = _json("/rooms", "POST", {"title": "Spec Room"})["room"]["id"]
        _json(f"/rooms/{rid}", "PUT", {"participants": ["mock"], "judge": "mock"})
        _json("/ui", "PUT", {"artifacts_dir": str(adir)})
        _json(f"/rooms/{rid}/converse", "POST", {"prompt": "hi", "addressed_to": "mock"})  # real usage
        # inject an answer carrying a fenced markdown block (mock can't emit one cleanly)
        turn = {"id": "art1", "ts": "2026-06-18T00:00:00Z", "mode": "converse", "role": "ai",
                "speaker": "mock", "text": f"Spec below:\n\n```markdown\n{ARTIFACT_BLOCK}\n```\n",
                "meta": {"model": "mock-1"}}
        (HOME / "vault" / rid / "main.jsonl").open("a", encoding="utf-8").write(json.dumps(turn) + "\n")

        with sync_playwright() as p:
            b = p.chromium.launch()
            ctx = b.new_context()
            ctx.grant_permissions(["clipboard-read", "clipboard-write"])
            page = ctx.new_page()
            page.goto(BASE + "/", wait_until="networkidle")

            # --- 14E: hover preview (before switching in — cheap, instant) ---
            page.locator('.room-row:has-text("Spec Room")').hover()
            page.wait_for_selector("#room-preview:not(.hidden)", timeout=3000)
            pv = page.locator("#room-preview").inner_text()
            assert "mock" in pv and "started" in pv and "Spec below" in pv, f"preview missing pieces: {pv!r}"
            page.mouse.move(0, 0)   # leave
            page.wait_for_timeout(150)
            assert page.locator("#room-preview").is_hidden(), "preview didn't dismiss on leave"
            print(f"14E OK: hover preview shows models + dates + summary, dismisses ({pv.splitlines()[0]!r})")

            page.locator('.room-row:has-text("Spec Room")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='Spec Room'")

            # --- 14D: artifact copy + save ---
            page.wait_for_selector(".artifact")
            assert page.locator(".artifact-label").count() >= 1, "no artifact control on a markdown spec"
            page.locator('.artifact .artifact-btn:has-text("copy")').first.click()
            page.wait_for_timeout(150)
            clip = page.evaluate("navigator.clipboard.readText()")
            assert clip.strip() == ARTIFACT_BLOCK, f"copy didn't put raw .md on clipboard: {clip!r}"
            page.locator('.artifact .artifact-btn:has-text("save")').first.click()
            page.wait_for_timeout(300)
            saved = list(adir.glob("*.md"))
            assert saved and saved[0].read_text().strip() == ARTIFACT_BLOCK, "save didn't write the .md"
            assert all(f.suffix == ".md" for f in adir.iterdir()), "non-.md produced"
            print(f"14D OK: copy → clipboard, save → {saved[0].name}")

            # --- 14C: chip toggles + model % ---
            page.click("#providers-btn")
            page.wait_for_selector('.pcard[data-name="mock"]')
            page.click('.tab[data-tab="theme"]')
            page.check("#chip-pct")
            page.wait_for_timeout(150)
            assert "%" in page.locator("#token-bar").inner_text(), "model % not shown when toggled on"
            assert _json("/ui")["show_model_pct"] is True, "model % toggle not persisted"
            page.uncheck("#chip-tokens")
            page.wait_for_timeout(150)
            bar = page.locator("#token-bar").inner_text()
            assert "/" not in bar.split("session")[0], f"token estimate still shown after toggle off: {bar!r}"
            assert _json("/ui")["show_token_estimate"] is False, "token-estimate toggle not persisted"
            print(f"14C OK: chip pieces toggle + persist ({bar.splitlines()[0]!r})")
            b.close()
        print("\nPHASE 14 C/D/E (chip toggles + artifacts + hover preview): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
