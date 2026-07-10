"""browser_phase38.py — trajectory interaction layer (Chromium).

  38.1: hovering a round's hit geometry raises that round (fan + dots + vertices) and dims the
        rest, via ONE attribute on the SVG root + draw-time CSS rules — no per-element style
        mutation, no redraw, no element re-creation. Same mechanism for a margin call
        (connector + terminal dot + bracket together).
  38.2: yes-and's A→B hand-off halos — keyed on meta.selection.mode, never topology.
  38.3: fixed-scale rows (ROW_H = clientHeight/12), a 5-row future zone with a live-edge
        hairline, rail scroll-pin mirroring the transcript rule, default-future ghost.
  38.4: paint-to-compose — future dots compile to the composer's selection state.

Run:  python tests/browser_phase38.py   (needs playwright + chromium)
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
PORT = 8848
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p38browser")


def _json(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    hdr = {"Content-Type": "application/json"} if body is not None else {}
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        BASE + path, data=data, headers=hdr, method=method), timeout=30).read() or "{}")


def wait_up():
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/rooms", timeout=2); return
        except Exception:
            time.sleep(0.2)
    raise SystemExit("server did not start")


def open_room(page, title):
    page.locator(f'.room-row:has-text("{title}")').click()
    page.wait_for_function(f"document.querySelector('#title').textContent==={title!r}")


def styleof(page, sel, prop):
    return page.eval_on_selector(sel, f"el => getComputedStyle(el).{prop}")


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
        # fusion round (judge also a panelist) + a converse follow-up + a margin call
        fus = _json("/rooms", "POST", {"title": "p38 fusion"})["room"]["id"]
        _json(f"/rooms/{fus}", "PUT", {"participants": ["mock", "mock_cli"], "judge": "mock",
                                       "margin_model": "mock"})
        _json(f"/rooms/{fus}/run", "POST", {"mode": "fusion", "prompt": "fan out",
                                            "panel": ["mock", "mock_cli"], "judge": "mock"})
        _json(f"/rooms/{fus}/run", "POST", {"mode": "converse", "prompt": "and then", "target": "mock"})
        _json(f"/rooms/{fus}/margin", "POST", {"prompt": "aside", "window": "last_1", "model": "mock"})

        with sync_playwright() as p:
            br = p.chromium.launch(); page = br.new_page(viewport={"width": 1600, "height": 900})
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.goto(BASE + "/", wait_until="networkidle")
            open_room(page, "p38 fusion")
            page.click("#traj-toggle")
            page.wait_for_selector("#traj-svg .traj-fan-out")

            fus_turns = _json(f"/rooms/{fus}")["turns"]
            rid = next((t["meta"] or {}).get("round_id") for t in fus_turns if t["role"] == "judge")
            panel = next(t for t in fus_turns if (t["meta"] or {}).get("is_panelist_raw"))
            conv_ai = fus_turns[-1]                     # the follow-up answer: NOT in the round

            # ---- 38.1A: hover a panel dot raises its whole round --------------------
            # falsifiability: the raise/dim assertions compare against the RESTING computed
            # values, so each must actually change under hover.
            assert styleof(page, ".traj-fan-out", "strokeOpacity") == "0.55"
            assert styleof(page, ".traj-lane", "opacity") == "1"
            page.evaluate("window.__fan = document.querySelector('.traj-fan-out')")

            page.hover(f'.traj-hit-node[data-turn-id="{panel["id"]}"]')
            page.wait_for_timeout(80)
            assert page.get_attribute("#traj-svg", "data-hover-round") == rid, "root attr not set"
            assert styleof(page, ".traj-fan-out", "strokeOpacity") == "1", "fan edge not raised to full"
            assert styleof(page, f'.traj-node[data-turn-id="{panel["id"]}"]', "fillOpacity") == "1", \
                "the hovered round's panel dot should rise to full opacity"
            assert styleof(page, ".traj-lane", "opacity") == "0.6", "everything else should dim to 0.6"
            assert styleof(page, f'.traj-node[data-turn-id="{conv_ai["id"]}"]', "opacity") == "0.6", \
                "a converse vertex outside the round dims too"

            # zero elements re-created: same node object, same child count
            assert page.evaluate("document.querySelector('.traj-fan-out') === window.__fan"), \
                "hover must not re-create elements"

            # leaving for a non-round row clears the highlight
            page.hover(f'.traj-hit-node[data-turn-id="{conv_ai["id"]}"]')
            page.wait_for_timeout(80)
            assert page.get_attribute("#traj-svg", "data-hover-round") is None, "hover did not clear"
            assert styleof(page, ".traj-fan-out", "strokeOpacity") == "0.55", "register not restored"
            assert styleof(page, ".traj-lane", "opacity") == "1"
            print("38.1A OK: hovering a panel dot raises its round, dims the rest, creates nothing")

            # ---- 38.1B: hovering a margin call raises connector + dot + bracket -----
            q = next(t for t in _json(f"/rooms/{fus}")["margin_turns"] if t["role"] == "human")
            assert styleof(page, ".traj-connector", "strokeOpacity") == "0.4"
            page.hover(f'.traj-hit-margin[data-margin-id="{q["id"]}"]')
            page.wait_for_timeout(80)
            assert page.get_attribute("#traj-svg", "data-hover-margin") == q["id"]
            assert styleof(page, ".traj-connector", "strokeOpacity") == "1", "connector not raised"
            assert styleof(page, ".traj-bracket", "strokeOpacity") == "1", "bracket not raised"
            assert styleof(page, ".traj-margin-dot", "fillOpacity") == "1", "terminal dot not raised"
            assert styleof(page, ".traj-lane", "opacity") == "0.6", "the rest should dim"
            page.mouse.move(5, 5)                     # off the svg entirely
            page.wait_for_timeout(80)
            assert page.get_attribute("#traj-svg", "data-hover-margin") is None, "leave did not clear"
            assert styleof(page, ".traj-connector", "strokeOpacity") == "0.4"
            print("38.1B OK: hovering a margin call raises connector + terminal dot + bracket together")

            assert not errs, f"page errors: {errs}"
            br.close()
        print("\nPHASE 38 (trajectory interaction layer): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
