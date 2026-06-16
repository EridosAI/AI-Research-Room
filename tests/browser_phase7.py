"""Phase 7 visual Done-when — model-management UI in a real headless Chromium.

Exercises the key boundary under human use:
  - write-only masked field: set a key, then change the model & save with a BLANK
    key field → the stored key is untouched (the round-trip trap).
  - Grok-analog cli row: structurally keyless; toggle cli↔api reveals/hides key;
    cli save never writes secrets.
  - /test + /models pending → ok/error lifecycle, with model-list fallback.
  - add provider; research-judge selector.
Then a "fresh terminal" check: keys live in secrets.json (outside repo+vault),
config.toml holds the rest, no key string in config.toml.
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
PORT = 8808
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p7")
SECRETS = HOME / "secrets.json"
CONFIG = HOME / "config.toml"


def post(path, body):
    urllib.request.urlopen(urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST"), timeout=10).read()


def wait_up():
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/transcript", timeout=2); return
        except Exception:
            time.sleep(0.2)
    raise SystemExit("server did not start")


def read_secrets():
    return json.loads(SECRETS.read_text()) if SECRETS.is_file() else {}


def card(page, name):
    return page.locator(f'.pcard[data-name="{name}"]')


def main():
    shutil.rmtree(HOME, ignore_errors=True)
    (HOME / "vault").mkdir(parents=True)
    shutil.copy(REPO / "tests" / "config.toml", CONFIG)
    env = {**os.environ, "RESEARCH_ROOM_CONFIG": str(CONFIG), "RESEARCH_ROOM_HOME": str(HOME),
           "RESEARCH_ROOM_SECRETS": str(SECRETS), "RESEARCH_ROOM_VAULT": str(HOME / "vault"),
           "RESEARCH_ROOM_PORT": str(PORT)}
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.click("#providers-btn")
            page.wait_for_selector('.pcard[data-name="mock"]')

            # ---- write-only: set a key via the masked field, save ----
            mock = card(page, "mock")
            mock.locator('input[type=password]').fill("sk-DUMMY-uitest-7777")
            mock.get_by_text("save", exact=True).click()
            page.wait_for_timeout(400)
            assert read_secrets().get("mock") == "sk-DUMMY-uitest-7777", "key not stored via UI"
            print("write-only set OK: key entered via masked field → secrets.json")

            # ---- the round-trip trap: change model, save with BLANK key ----
            mock = card(page, "mock")
            assert mock.locator('input[type=password]').input_value() == "", "key field must render EMPTY, not prefilled"
            mock.locator('input[type=text]').nth(1).fill("mock-changed")   # [0]=base_url, [1]=model
            mock.get_by_text("save", exact=True).click()
            page.wait_for_timeout(400)
            assert read_secrets().get("mock") == "sk-DUMMY-uitest-7777", "BLANK key field overwrote the stored key!"
            assert 'model = "mock-changed"' in CONFIG.read_text(), "model change not written to config.toml"
            print("round-trip OK: model saved, blank key field left the stored key untouched")

            # ---- Grok-analog cli row: structurally keyless + toggle ----
            mc = card(page, "mock_cli")
            assert mc.locator('input[type=password]').count() == 0, "cli row must have NO key field"
            assert "Grok Build" in mc.inner_text() or "no key" in mc.inner_text(), "cli note missing"
            mc.locator('input[type=checkbox]').first.uncheck()   # cli → api
            assert mc.locator('input[type=password]').count() == 1, "toggling cli→api should reveal a key field"
            mc.locator('input[type=checkbox]').first.check()     # api → cli
            assert mc.locator('input[type=password]').count() == 0, "toggling api→cli should hide the key field"
            mc.get_by_text("save", exact=True).click(); page.wait_for_timeout(400)
            assert "mock_cli" not in read_secrets(), "cli save must NOT write a key to secrets.json"
            print("grok-analog OK: cli keyless, toggle reveals/hides key, cli save writes no secret")

            # ---- test + models lifecycle ----
            card(page, "mock").get_by_text("test", exact=True).click()
            page.wait_for_selector('.pcard[data-name="mock"] .pstatus.ok', timeout=10000)
            print("test lifecycle OK: mock → connected (green)")
            card(page, "deepseek").get_by_text("test", exact=True).click()
            page.wait_for_selector('.pcard[data-name="deepseek"] .pstatus.error', timeout=10000)
            assert "no API key" in page.locator("#banner").inner_text()
            print("test error OK: keyless deepseek → error surfaced (redacted)")
            card(page, "mock").get_by_text("refresh models", exact=True).click()
            page.wait_for_timeout(400)
            assert card(page, "mock").locator("datalist option").count() >= 1, "model dropdown not populated"
            card(page, "deepseek").get_by_text("refresh models", exact=True).click()
            page.wait_for_timeout(400)
            assert "type the id manually" in page.locator("#banner").inner_text(), "no typed-id fallback on /models failure"
            print("models lifecycle OK: populated for mock; typed-id fallback for failing deepseek")

            # ---- add provider via UI ----
            page.fill("#add-name", "myvllm"); page.fill("#add-base", "http://localhost:9999/v1")
            page.fill("#add-model", "qwen3"); page.fill("#add-key", "sk-ADD-3333")
            page.get_by_text("add", exact=True).click()
            page.wait_for_selector('.pcard[data-name="myvllm"]', timeout=5000)
            assert read_secrets().get("myvllm") == "sk-ADD-3333"
            print("add-provider OK: new OpenAI-compatible provider added, key stored")

            # ---- research judge selector ----
            page.select_option("#judge-select", "mock_cli"); page.wait_for_timeout(300)
            assert 'research_judge = "mock_cli"' in CONFIG.read_text(), "judge change not persisted"
            print("judge selector OK: research_judge → mock_cli persisted")

            page.screenshot(path=str(HOME / "panel.png"), full_page=True)
            b.close()

        # ---- "fresh terminal" loop: keys outside repo+vault; config has the rest ----
        sec = read_secrets()
        cfg = CONFIG.read_text()
        assert sec.get("mock") == "sk-DUMMY-uitest-7777" and sec.get("myvllm") == "sk-ADD-3333"
        assert "mock_cli" not in sec
        assert "sk-DUMMY-uitest-7777" not in cfg and "sk-ADD-3333" not in cfg, "KEY LEAKED INTO config.toml"
        assert str(REPO) not in str(SECRETS.resolve()) and "vault" not in str(SECRETS)
        assert "myvllm" in cfg and 'research_judge = "mock_cli"' in cfg
        print("\nfresh-terminal loop OK: keys in secrets.json (outside repo+vault); config.toml has the rest; no key in config.toml")
        print("PHASE 7 BROWSER DONE-WHEN: ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
