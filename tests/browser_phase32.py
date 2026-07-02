"""browser_phase32.py — per-room artifacts: overlay round-trip + saved chip (Chromium).

  32.1 overlay: the room-settings "artifacts dir" field round-trips (set → save → reopen),
       blank means inherit (placeholder shows the resolved global), and the value reaches
       room.json (verified over the API).
  32.4 chip: a turn carrying meta.artifact_paths renders the saved FILENAME + a "copy path"
       button (clipboard gets the path); a legacy turn (block but no meta) renders unchanged;
       a manual "save" upgrades its chip in place (real endpoint → resolved dir → file).

The mock can't emit a fenced block through the UI, so the saved/legacy turns are seeded
directly into the room's main.jsonl (a plain JSONL file) — the render path is what's tested.

Run:  python tests/browser_phase32.py
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
PORT = 8838
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p32browser")
FENCE = "here is a spec\n\n```markdown\n# Spec\nbody\n```\n"


def _json(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"Content-Type": "application/json"} if body is not None else {}
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        BASE + path, data=data, headers=hdr, method=method), timeout=20).read() or "{}")


def wait_up():
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/rooms", timeout=2); return
        except Exception:
            time.sleep(0.2)
    raise SystemExit("server did not start")


def _turn(mode, role, speaker, text, meta):
    return {"id": f"{role}-{speaker}-{hash(text) & 0xffff}", "ts": "2026-07-02T00:00:00",
            "mode": mode, "role": role, "speaker": speaker, "text": text, "meta": meta}


def main():
    shutil.rmtree(HOME, ignore_errors=True)
    (HOME / "vault").mkdir(parents=True)
    (HOME / "arts").mkdir(parents=True)
    shutil.copy(REPO / "tests" / "config.toml", HOME / "config.toml")
    env = {**os.environ,
           "RESEARCH_ROOM_CONFIG": str(HOME / "config.toml"), "RESEARCH_ROOM_HOME": str(HOME),
           "RESEARCH_ROOM_SECRETS": str(HOME / "secrets.json"), "RESEARCH_ROOM_VAULT": str(HOME / "vault"),
           "RESEARCH_ROOM_UI": str(HOME / "ui.json"), "RESEARCH_ROOM_PORT": str(PORT)}
    srv = subprocess.Popen([sys.executable, "-m", "web.server"], cwd=REPO, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_up()
        art = _json("/rooms", "POST", {"title": "artroom"})["room"]["id"]
        _json(f"/rooms/{art}", "PUT", {"participants": ["mock"], "judge": "mock"})

        # chiproom: seed a SAVED turn (meta.artifact_paths) + a LEGACY turn (block, no meta)
        chip = _json("/rooms", "POST", {"title": "chiproom"})["room"]["id"]
        _json(f"/rooms/{chip}", "PUT", {"participants": ["mock"], "judge": "mock",
                                        "artifacts_dir": str(HOME / "arts")})   # writable → manual save works
        saved_path = str(HOME / "arts" / "chiproom-seeded-1.md")
        lines = [
            _turn("converse", "human", "human", "make a spec", {}),
            _turn("converse", "ai", "mock", FENCE, {"model": "mock-x", "artifact_paths": [saved_path]}),
            _turn("converse", "ai", "mock", FENCE, {"model": "mock-x"}),   # legacy: block, no meta
        ]
        (HOME / "vault" / chip / "main.jsonl").write_text("".join(json.dumps(t) + "\n" for t in lines))

        with sync_playwright() as p:
            br = p.chromium.launch()
            ctx = br.new_context()
            ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE)
            page = ctx.new_page()
            page.goto(BASE + "/", wait_until="networkidle")

            # ================= 32.1 overlay round-trip =================
            page.locator('.room-row:has-text("artroom")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='artroom'")
            page.click("#room-settings-btn")
            page.wait_for_selector("#room-settings-overlay:not(.hidden)")
            assert page.input_value("#room-artifacts-dir") == "", "a fresh room's artifacts field starts blank"
            ph = page.get_attribute("#room-artifacts-dir", "placeholder") or ""
            assert "inherit" in ph.lower(), f"blank must signal inherit: {ph!r}"
            print("32.1 blank OK: field starts empty, placeholder signals inherit-global")

            page.fill("#room-artifacts-dir", "/tmp/rr-proj/specs")
            page.click("#room-settings-save")
            page.wait_for_selector("#room-settings-overlay", state="hidden")
            assert _json(f"/rooms/{art}").get("artifacts_dir") == "/tmp/rr-proj/specs", "value must reach room.json"
            page.click("#room-settings-btn")
            page.wait_for_selector("#room-settings-overlay:not(.hidden)")
            assert page.input_value("#room-artifacts-dir") == "/tmp/rr-proj/specs", "value must round-trip on reopen"
            print("32.1 roundtrip OK: set → save → room.json → reopen shows the value")

            # blank again = inherit (clears the override)
            page.fill("#room-artifacts-dir", "")
            page.click("#room-settings-save")
            page.wait_for_selector("#room-settings-overlay", state="hidden")
            assert _json(f"/rooms/{art}").get("artifacts_dir") == "", "blank must clear the override in room.json"
            print("32.1 clear OK: blanking the field clears the per-room override")

            # placeholder reflects the resolved GLOBAL once one is set (reload to refresh STATE.ui)
            _json("/ui", "PUT", {"artifacts_dir": "/tmp/global-arts"})
            page.reload(wait_until="networkidle")
            page.locator('.room-row:has-text("artroom")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='artroom'")
            page.click("#room-settings-btn")
            page.wait_for_selector("#room-settings-overlay:not(.hidden)")
            ph2 = page.get_attribute("#room-artifacts-dir", "placeholder") or ""
            assert "/tmp/global-arts" in ph2, f"placeholder should show the resolved global: {ph2!r}"
            print("32.1 inherit OK: placeholder shows the resolved global when the field is blank")
            page.keyboard.press("Escape")

            # ================= 32.4 saved chip =================
            page.locator('.room-row:has-text("chiproom")').click()
            page.wait_for_function("document.querySelector('#title').textContent==='chiproom'")
            page.wait_for_selector(".artifact")

            saved = page.locator(".artifact.saved")
            assert saved.count() == 1, f"exactly one turn should render a saved chip: {saved.count()}"
            assert "chiproom-seeded-1.md" in saved.locator(".artifact-label").inner_text(), \
                "the saved chip shows the FILENAME (basename)"
            cp = saved.locator('.artifact-btn:has-text("copy path")')
            assert cp.count() == 1, "the saved chip has a 'copy path' button"
            print("32.4 saved OK: chip shows the saved filename + a copy-path button")

            # the legacy turn (block, no meta) renders detection-only — unchanged
            all_chips = page.locator(".artifact")
            legacy = page.locator(".artifact:not(.saved)")
            assert legacy.count() == 1 and all_chips.count() == 2, "legacy turn renders as a plain (non-saved) chip"
            assert 'markdown artifact' in legacy.locator(".artifact-label").inner_text().lower()
            assert legacy.locator('.artifact-btn:has-text("copy path")').count() == 0, "legacy chip has no copy-path"
            print("32.4 legacy OK: a block without meta renders exactly as before (no fake saved state)")

            # copy path → clipboard gets the saved path
            cp.click()
            got = page.evaluate("navigator.clipboard.readText()")
            assert got == saved_path, f"copy-path must put the saved path on the clipboard: {got!r}"
            print("32.4 clipboard OK: 'copy path' copies the saved .md path")

            # manual save on the legacy turn → real endpoint writes → chip upgrades in place
            legacy.locator('.artifact-btn:has-text("save")').first.click()
            page.wait_for_function("document.querySelectorAll('.artifact.saved').length === 2", timeout=8000)
            up = page.locator(".artifact.saved").nth(1)
            assert up.locator('.artifact-btn:has-text("copy path")').count() == 1, "manual save adds a copy-path button"
            assert ".md" in up.locator(".artifact-label").inner_text(), "manual save shows the saved filename"
            assert list((HOME / "arts").glob("*.md")), "manual save wrote a real .md into the resolved dir"
            print("32.4 manual OK: 'save' hits the resolved dir and upgrades the chip in place")

            br.close()
        print("\nPHASE 32 (per-room artifacts): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
