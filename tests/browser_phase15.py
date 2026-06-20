"""browser_phase15.py — dark / light / system mode (headless Chromium).

  15.1: a dark/light/system control exists in the Theme tab and is the single
        repaint entry point; the choice persists in ui.json and survives reload.
  15.2: light flips the CSS-resident surface/shadow tokens (--bg-primary off its
        dark value; --shadow-md `none` in dark, non-`none` in light).
  15.3: the JS ramps fork by mode — light drops --accent-text's L (~0.47) and makes
        --text-primary dark/high-contrast; dark output is unchanged.
  system resolves to a concrete data-theme; everything reconstructs on a hard
  refresh with localStorage empty.

Run:  python tests/browser_phase15.py   (needs playwright + chromium)
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
HOME = Path("/tmp/p15browser")


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


def cssvar(page, n):
    return page.evaluate(f"getComputedStyle(document.documentElement).getPropertyValue('{n}').trim()")


def theme_attr(page):
    return page.evaluate("document.documentElement.dataset.theme || ''")


def open_theme_tab(page):
    page.click("#providers-btn")
    page.wait_for_selector('#thememode-opts button', state="attached")
    page.click('.tab[data-tab="theme"]')
    page.wait_for_function("!document.querySelector('.tab-pane[data-pane=\"theme\"]').classList.contains('hidden')")


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
        with sync_playwright() as p:
            b = p.chromium.launch(); page = b.new_page()
            page.goto(BASE + "/", wait_until="networkidle")
            page.wait_for_function("!!document.documentElement.dataset.theme")   # boot painted

            # default is dark — capture the dark baseline (the values phase 15 must NOT touch)
            assert theme_attr(page) == "dark", f"default theme not dark: {theme_attr(page)!r}"
            dark = {n: cssvar(page, n) for n in
                    ("--bg-primary", "--accent-text", "--text-primary", "--shadow-md")}
            assert dark["--bg-primary"] == "#08090a", f"dark base moved: {dark['--bg-primary']!r}"
            assert dark["--shadow-md"] == "none", f"dark --shadow-md should be none: {dark['--shadow-md']!r}"
            assert "0.72" in dark["--accent-text"], f"dark accent-text L wrong: {dark['--accent-text']!r}"

            # --- 15.1: the control is present in the Theme tab (three options) ---
            open_theme_tab(page)
            assert page.locator('#thememode-opts button').count() == 3, "expected dark/light/system control"
            print("15.1 OK: dark/light/system control present in Theme tab")

            # --- 15.2 + 15.3: switch to LIGHT — surfaces, shadow, accent, text all flip ---
            page.click('#thememode-opts button:has-text("Light")')
            page.wait_for_function("document.documentElement.dataset.theme === 'light'")
            assert cssvar(page, "--bg-primary") != "#08090a", "light didn't flip --bg-primary (CSS surface block)"
            assert cssvar(page, "--shadow-md") != "none", f"light --shadow-md still none: {cssvar(page,'--shadow-md')!r}"
            at = cssvar(page, "--accent-text")
            assert "0.47" in at, f"light --accent-text L not dropped: {at!r}"
            tp = cssvar(page, "--text-primary")
            assert "0.13" in tp, f"light --text-primary not dark/high-contrast: {tp!r}"
            assert _json("/ui")["theme_mode"] == "light", "theme_mode not persisted"
            print(f"15.2/15.3 OK: light flips surfaces + shadow + accent-text({at!r}) + text({tp!r}), persisted")

            # --- 15.1: persistence across a hard refresh, localStorage empty ---
            assert page.evaluate("window.localStorage.length") == 0, "localStorage used (forbidden)"
            page.reload(wait_until="networkidle")
            assert theme_attr(page) == "light", "light not restored after hard refresh"
            assert "0.47" in cssvar(page, "--accent-text"), "light accent-text not restored after reload"
            assert page.evaluate("window.localStorage.length") == 0, "localStorage populated after reload"
            print("15.1 OK: light persists across hard refresh, localStorage empty")

            # --- 15.1: system resolves to a concrete data-theme ---
            open_theme_tab(page)
            page.click('#thememode-opts button:has-text("System")')
            page.wait_for_timeout(150)
            assert theme_attr(page) in ("dark", "light"), f"system didn't resolve concrete: {theme_attr(page)!r}"
            assert _json("/ui")["theme_mode"] == "system", "system not persisted"
            print(f"15.1 OK: system resolves to concrete data-theme ({theme_attr(page)!r})")

            # --- selecting DARK restores every captured token to its pre-phase-15 value ---
            page.click('#thememode-opts button:has-text("Dark")')
            page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
            for n, v in dark.items():
                assert cssvar(page, n) == v, f"dark not byte-identical for {n}: {cssvar(page,n)!r} != {v!r}"
            print("dark OK: returning to dark restores every token to its baseline")
            b.close()
        print("\nPHASE 15 (dark / light / system mode): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
