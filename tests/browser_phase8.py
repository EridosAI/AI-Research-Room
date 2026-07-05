"""Per-round model picker + judge fallback — real headless Chromium, mock fixture.

  - picker: select only `mock` (exclude mock_cli, which WOULD succeed) → the round
    must contain exactly that one panelist, proving selection limits the panel
    (not just degradation hiding keyless models).
  - judge fallback: point research_judge at keyless `deepseek` → the round still
    completes, synthesized by a working panelist, tagged "fell back from deepseek".
"""
import json, os, shutil, subprocess, sys, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
PORT = 8809; BASE = f"http://127.0.0.1:{PORT}"; HOME = Path("/tmp/p8")


def _json(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"Content-Type": "application/json"} if body is not None else {}
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        BASE + path, data=data, headers=hdr, method=method), timeout=10).read() or "{}")


def seed_room(title):
    """Create + configure a room via the real /rooms path (roster = enabled, judge
    = global) — replaces the retired seeded /transcript shim."""
    rid = _json("/rooms", "POST", {"title": title})["room"]["id"]
    part = _json("/participants")
    enabled = [p["name"] for p in part["participants"] if p["enabled"]]
    _json(f"/rooms/{rid}", "PUT", {"participants": enabled, "judge": part["research_judge"]})
    return rid


def main():
    shutil.rmtree(HOME, ignore_errors=True); (HOME / "vault").mkdir(parents=True)
    shutil.copy(REPO / "tests" / "config.toml", HOME / "config.toml")
    env = {**os.environ, "RESEARCH_ROOM_CONFIG": str(HOME / "config.toml"), "RESEARCH_ROOM_HOME": str(HOME),
           "RESEARCH_ROOM_SECRETS": str(HOME / "secrets.json"), "RESEARCH_ROOM_VAULT": str(HOME / "vault"),
           "RESEARCH_ROOM_PORT": str(PORT)}
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try: urllib.request.urlopen(BASE + "/rooms", timeout=2); break
            except Exception: time.sleep(0.2)
        seed_room("picker test")
        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.select_option("#mode", "fusion", force=True)

            # picker shows a checkbox per enabled provider (fixture has 5)
            boxes = page.locator("#panel-pick input[type=checkbox]")
            assert boxes.count() == 5, f"expected 5 picker checkboxes, got {boxes.count()}"
            # select ONLY mock (uncheck the rest, incl. mock_cli which would succeed)
            for i in range(boxes.count()):
                cb = boxes.nth(i)
                if cb.get_attribute("value") != "mock":
                    cb.uncheck()
            page.fill("#input", "why is the sky blue?")
            page.click("#send-btn")
            page.wait_for_selector(".round .synthesis", timeout=30000)
            assert page.locator(".round .panel").count() == 1, "picker did not limit the panel to 1"
            assert page.locator(".round .panel .pname").first.inner_text().strip() == "mock"
            assert "mock_cli" not in page.locator(".round").inner_text(), "excluded model leaked into the round"
            print("picker OK: only the selected model ran (excluded a model that would have succeeded)")

            # ---- judge fallback: pick keyless deepseek as THIS round's judge ----
            page.select_option("#judge-pick", "deepseek")
            # run another round with only mock selected
            page.select_option("#mode", "fusion", force=True)
            boxes = page.locator("#panel-pick input[type=checkbox]")
            for i in range(boxes.count()):
                cb = boxes.nth(i)
                if cb.get_attribute("value") != "mock":
                    cb.uncheck()
            page.fill("#input", "second round")
            before = page.locator(".synthesis").count()
            page.click("#send-btn")
            page.wait_for_function(f"document.querySelectorAll('.synthesis').length > {before}", timeout=30000)
            page.wait_for_timeout(200)
            syn = page.locator(".synthesis .who").last.inner_text()
            assert "fell back from deepseek" in syn, f"judge fallback not shown: {syn!r}"
            print("judge fallback OK: keyless deepseek judge → fell back to a working panelist:", syn.strip())
            b.close()
        print("\nPER-ROUND PICKER + JUDGE FALLBACK: ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
