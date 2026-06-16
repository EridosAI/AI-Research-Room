"""Per-round judge selector — real headless Chromium, mock fixture.

The fixture's global research_judge is `mock`. We override it in the composer to
`mock_cli` for one round and confirm THAT model synthesizes (not the global
default) — proving the per-round judge override is wired end to end.
"""
import json, os, shutil, subprocess, sys, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
PORT = 8812; BASE = f"http://127.0.0.1:{PORT}"; HOME = Path("/tmp/p9")


def post(path, body):
    urllib.request.urlopen(urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST"), timeout=10).read()


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
            try: urllib.request.urlopen(BASE + "/transcript", timeout=2); break
            except Exception: time.sleep(0.2)
        post("/transcript", {"title": "judge picker"})
        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.locator('input[name="mode"][value="research"]').check()

            # judge dropdown defaults to the global research_judge (mock)
            assert page.locator("#judge-pick").input_value() == "mock", \
                f"judge-pick should default to global judge, got {page.locator('#judge-pick').input_value()}"
            print("judge selector OK: defaults to global research_judge (mock)")

            # override the judge to mock_cli; panel = mock only
            page.select_option("#judge-pick", "mock_cli")
            boxes = page.locator("#panel-pick input[type=checkbox]")
            for i in range(boxes.count()):
                cb = boxes.nth(i)
                if cb.get_attribute("value") != "mock":
                    cb.uncheck()
            page.fill("#input", "override the judge this round")
            page.click("#send-btn")
            page.wait_for_selector(".round .synthesis", timeout=30000)
            page.wait_for_timeout(200)

            tr = json.loads(urllib.request.urlopen(BASE + "/transcript", timeout=5).read())
            jt = [t for t in tr["turns"] if t["role"] == "judge"][-1]
            assert jt["speaker"] == "mock_cli", f"per-round judge override ignored — judge was {jt['speaker']}"
            assert "judge_fallback_from" not in jt["meta"], "should not have fallen back (mock_cli works)"
            who = page.locator(".synthesis .who").last.inner_text()
            assert who.startswith("mock_cli"), f"synthesis not attributed to chosen judge: {who!r}"
            print(f"override OK: chose mock_cli (≠ global mock) → it synthesized: {who.strip()!r}")
            b.close()
        print("\nPER-ROUND JUDGE SELECTOR: ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
