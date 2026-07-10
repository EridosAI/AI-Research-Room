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

        # yes-and: the real thing, selection stamped by the engine
        ya = _json("/rooms", "POST", {"title": "p38 yesand"})["room"]["id"]
        _json(f"/rooms/{ya}", "PUT", {"participants": ["mock", "mock_cli"], "judge": "mock"})
        _json(f"/rooms/{ya}/run", "POST", {"mode": "yes_and", "prompt": "build",
                                           "seats": ["mock", "mock_cli"]})

        # the falsifiability pair: an AI answer followed by a promoted note is ALSO two
        # consecutive non-human forward turns — topology alone must fail this fixture
        nr = _json("/rooms", "POST", {"title": "p38 note"})["room"]["id"]
        _json(f"/rooms/{nr}", "PUT", {"participants": ["mock"], "judge": "mock", "margin_model": "mock"})
        _json(f"/rooms/{nr}/run", "POST", {"mode": "converse", "prompt": "main q", "target": "mock"})
        mt = _json(f"/rooms/{nr}/margin", "POST", {"prompt": "side q", "window": "last_1", "model": "mock"})
        ans = next(t for t in mt["margin_turns"] if t["role"] == "ai")
        _json(f"/rooms/{nr}/margin/{ans['id']}/promote", "POST")

        # a tall room for the fixed-scale + scroll-pin + ghost checks. The LAST ai speaker is
        # mock_cli while participants[0] is mock — so "auto resolves to the last AI speaker"
        # is falsifiable against "auto resolves to the first participant".
        tall = _json("/rooms", "POST", {"title": "p38 tall"})["room"]["id"]
        _json(f"/rooms/{tall}", "PUT", {"participants": ["mock", "mock_cli"], "judge": "mock"})
        with (HOME / "vault" / tall / "main.jsonl").open("w", encoding="utf-8") as f:
            for i in range(24):
                role = "human" if i % 2 == 0 else "ai"
                spk = "human" if role == "human" else ("mock_cli" if i == 23 else "mock")
                f.write(json.dumps({"id": f"tl-{i:03d}", "ts": f"2026-07-10T00:{i:02d}:00Z",
                                    "mode": "converse", "role": role, "speaker": spk,
                                    "text": f"turn {i}", "meta": {}}) + "\n")

        # yes-and SHAPE without selection (a pre-Phase-27 transcript): renders unmarked
        old = _json("/rooms", "POST", {"title": "p38 old"})["room"]["id"]
        _json(f"/rooms/{old}", "PUT", {"participants": ["mock", "mock_cli"], "judge": "mock"})
        with (HOME / "vault" / old / "main.jsonl").open("w", encoding="utf-8") as f:
            for i, (role, spk) in enumerate([("human", "human"), ("ai", "mock"), ("ai", "mock_cli")]):
                f.write(json.dumps({"id": f"old-{i}", "ts": f"2026-07-10T00:00:0{i}Z", "mode": "converse",
                                    "role": role, "speaker": spk, "text": f"t{i}", "meta": {}}) + "\n")

        # paint-to-compose (38.4): a roster of exactly two, so the divergence glyph can compile
        # (side-by-side demands exactly two seats). Room judge = mock_cli, DIFFERENT from every
        # judge the tests paint (mock) — so "the paint set the judge" is falsifiable against
        # "the room default leaked through".
        pr = _json("/rooms", "POST", {"title": "p38 paint"})["room"]["id"]
        _json(f"/rooms/{pr}", "PUT", {"participants": ["mock", "mock_cli"], "judge": "mock_cli"})
        _json(f"/rooms/{pr}/run", "POST", {"mode": "converse", "prompt": "seed", "target": "mock"})

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

            # ---- 38.2A: yes-and's A→B hand-off halos, in A's colour ------------------
            open_room(page, "p38 yesand")
            page.wait_for_selector("#traj-svg .traj-halo")
            ya_turns = _json(f"/rooms/{ya}")["turns"]
            a_t, b_t = [t for t in ya_turns if t["role"] == "ai"]
            halos = page.locator("#traj-svg .traj-halo")
            assert halos.count() == 1, f"exactly the A→B segment halos: {halos.count()}"
            assert page.get_attribute(".traj-halo", "data-from") == a_t["id"]
            assert page.get_attribute(".traj-halo", "data-to") == b_t["id"]
            a_col = page.get_attribute(f'.traj-node[data-turn-id="{a_t["id"]}"]', "fill")
            assert page.get_attribute(".traj-halo", "stroke") == a_col, "halo carries A's colour (origin)"
            assert page.get_attribute(".traj-halo", "stroke-width") == "4"
            assert page.get_attribute(".traj-halo", "d") == page.get_attribute(
                f'.traj-line[data-from="{a_t["id"]}"]', "d"), "halo shares its segment's exact path"
            # beneath the bright segment: the halo precedes it in document order
            assert page.evaluate("""() => {
              const h = document.querySelector('.traj-halo');
              const l = document.querySelector(`.traj-line[data-from="${h.dataset.from}"]`);
              return !!(h.compareDocumentPosition(l) & Node.DOCUMENT_POSITION_FOLLOWING);
            }"""), "the halo must paint beneath (before) its bright segment"
            print("38.2A OK: yes-and halos exactly A→B, A-coloured, beneath the trajectory")

            # ---- 38.2B: the falsifiability pair — topology alone must fail ----------
            open_room(page, "p38 note")
            page.wait_for_selector("#traj-svg .traj-node")
            nr_turns = _json(f"/rooms/{nr}")["turns"]
            assert nr_turns[-2]["role"] == "ai" and nr_turns[-1]["role"] == "note", \
                f"fixture must end ai→note: {[(t['role']) for t in nr_turns]}"
            assert page.locator("#traj-svg .traj-halo").count() == 0, \
                "an AI-then-promoted-note adjacency must NOT halo — the halo keys on selection"

            open_room(page, "p38 old")
            page.wait_for_selector("#traj-svg .traj-node")
            assert page.locator("#traj-svg .traj-halo").count() == 0, \
                "a selection-less yes-and SHAPE renders unmarked (pre-Phase-27 rooms)"
            print("38.2B OK: promoted-note adjacency and selection-less shape both stay unmarked")

            # ================= 38.3 — fixed scale, future zone, ghost ==============
            open_room(page, "p38 tall")
            page.wait_for_selector("#traj-svg .traj-hit")
            rail_h = page.eval_on_selector("#traj-rail", "el => el.clientHeight")
            row_h = rail_h / 12

            # ---- 38.3A: geometry — ROW_H = h/12, +5 future rows, hairline, lanes run on ----
            n_rows = page.locator("#traj-svg .traj-hit").count()
            assert n_rows == 24, f"24 forward turns = 24 logical rows: {n_rows}"
            svg_h = float(page.get_attribute("#traj-svg", "height"))
            assert abs(svg_h - (24 + 5) * row_h) <= 1, f"svg height must be (rows+5)×ROW_H: {svg_h}"
            ys = page.evaluate("""() => ['0','1'].map(r =>
                 +document.querySelector(`.traj-hit[data-row="${r}"]`).getAttribute('y'))""")
            assert abs((ys[1] - ys[0]) - row_h) < 0.6, f"row pitch must be clientHeight/12: {ys}, {row_h}"
            now_y = float(page.get_attribute(".traj-now", "y1"))
            assert abs(now_y - 24 * row_h) < 0.6, f"the hairline sits at the live edge: {now_y}"
            lane_y2 = float(page.get_attribute(".traj-lane", "y2"))
            assert abs(lane_y2 - svg_h) < 1, "lane guides must run through the future zone"
            print("38.3A OK: fixed ROW_H = h/12; 5 future rows; hairline at the live edge")

            # ---- 38.3B: the rail's scroll-pin mirrors the transcript rule ----------
            geom_max = page.eval_on_selector("#traj-rail", "el => el.scrollHeight - el.clientHeight")
            assert geom_max > 200, f"the tall fixture must make the rail scroll: {geom_max}"
            page.eval_on_selector("#traj-rail", "el => el.scrollTop = el.scrollHeight")
            page.evaluate("drawTrajGraph()")
            assert page.eval_on_selector(
                "#traj-rail", "el => el.scrollTop + el.clientHeight >= el.scrollHeight - 40"), \
                "at the live edge, a redraw must keep following it"
            page.eval_on_selector("#traj-rail", "el => el.scrollTop = 150")
            page.evaluate("drawTrajGraph()")
            kept = page.eval_on_selector("#traj-rail", "el => el.scrollTop")
            assert abs(kept - 150) < 5, f"a mid-scroll rail position must be preserved: {kept}"
            page.eval_on_selector("#traj-rail", "el => el.scrollTop = 0")
            open_room(page, "p38 fusion")
            open_room(page, "p38 tall")
            page.wait_for_timeout(150)
            assert page.eval_on_selector(
                "#traj-rail", "el => el.scrollTop + el.clientHeight >= el.scrollHeight - 40"), \
                "a room switch must force-pin the rail to the live edge"
            print("38.3B OK: rail pin — edge follows, mid-scroll preserved, switch force-pins")

            # ---- 38.3C: converse default ghost, auto AND explicit ------------------
            # auto: resolves to the actual last AI speaker (mock_cli), NOT participants[0] (mock)
            assert page.eval_on_selector("#addressee", "el => el.value") == "", "fixture: addressee is auto"
            ghost = page.locator("#traj-svg .traj-ghost-node")
            assert ghost.count() == 1, f"converse ghosts exactly one ring: {ghost.count()}"
            assert page.get_attribute(".traj-ghost-node", "data-lane") == "mock_cli", \
                "auto must resolve to the LAST AI speaker, not the first participant"
            assert page.get_attribute(".traj-ghost-node", "data-frow") == "1"
            assert page.get_attribute(".traj-ghost-node", "fill") == "none", "ghost vertices are hollow rings"
            assert page.get_attribute(".traj-ghost-node", "stroke-opacity") == "0.25"
            cy = float(page.get_attribute(".traj-ghost-node", "cy"))
            assert abs(cy - 24.5 * row_h) < 0.6, f"the ghost lands on the first future row: {cy}"
            assert page.locator("#traj-svg .traj-ghost-edge").count() == 1, "one ghost swerve from the live edge"
            # explicit addressee: the ghost moves with the picker
            page.select_option("#addressee", "mock")
            page.wait_for_timeout(80)
            assert page.get_attribute(".traj-ghost-node", "data-lane") == "mock", \
                "the ghost must follow an explicit addressee"
            page.select_option("#addressee", "")
            print("38.3C OK: converse ghost — auto resolves to the last AI speaker; explicit follows")

            # ---- 38.3D: panel-mode default ghost = the full default fan -------------
            page.click("#mode-toggle")                 # #mode lives inside the disclosure (Phase 35)
            page.wait_for_selector("#composer-advanced:not(.hidden)")
            page.select_option("#mode", "fusion")
            page.wait_for_timeout(100)
            rings = page.eval_on_selector_all(
                "#traj-svg .traj-ghost-node", "els => els.map(e => [e.dataset.lane, e.dataset.frow])")
            assert sorted(rings) == [["mock", "1"], ["mock", "2"], ["mock_cli", "1"]], \
                f"fusion default ghost: both panelists at +1, the room judge at +2: {rings}"
            assert page.locator("#traj-svg .traj-ghost-edge").count() == 4, \
                "2 ghost fan-outs + 2 ghost fan-ins"
            page.select_option("#mode", "converse")
            page.wait_for_timeout(80)
            assert page.locator("#traj-svg .traj-ghost-node").count() == 1, \
                "switching the picker back re-derives the converse ghost (state, not gesture)"
            print("38.3D OK: fusion default ghost fans to the panel and converges on the room judge")

            # ================= 38.4 — paint-to-compose ==============================
            open_room(page, "p38 paint")
            page.wait_for_selector("#traj-svg .traj-hit-future")

            def val(sel):
                return page.eval_on_selector(sel, "el => el.value")

            def gnodes():
                return sorted(page.eval_on_selector_all(
                    "#traj-svg .traj-ghost-node",
                    "els => els.map(e => [e.dataset.lane, e.dataset.frow])"))

            def checked(box):
                return page.evaluate(
                    f"[...document.querySelectorAll('{box} input:checked')].map(i => i.value)")

            def paint(lane, frow):
                page.click(f'.traj-hit-future[data-lane="{lane}"][data-frow="{frow}"]')
                page.wait_for_timeout(50)

            def edges():
                return page.locator("#traj-svg .traj-ghost-edge").count()

            # ---- 38.4A: converse row; a non-compiling pattern is inert --------------
            assert _json(f"/rooms/{pr}")["judge"] == "mock_cli", "fixture: room judge must be mock_cli"
            assert val("#mode") == "converse" and val("#addressee") == ""
            assert gnodes() == [["mock", "1"]], f"auto converse derives one dot on the last AI: {gnodes()}"
            paint("mock_cli", 1)                       # {mock, mock_cli}@+1: two dots, no judge
            assert val("#mode") == "converse", "a non-compiling paint must not change the mode"
            assert val("#addressee") == "", "a non-compiling paint must not change the addressee"
            assert page.text_content("#mode-toggle").startswith("converse"), "chip keeps the last valid state"
            assert gnodes() == [["mock", "1"], ["mock_cli", "1"]], f"the dots still render, bare: {gnodes()}"
            assert edges() == 0, "a non-compiling pattern must draw NO strokes"
            paint("mock", 1)                           # toggle off → {mock_cli}@+1
            assert val("#mode") == "converse" and val("#addressee") == "mock_cli", \
                "one model dot at +1 compiles to converse → that model"
            assert gnodes() == [["mock_cli", "1"]] and edges() == 1, "the ghost re-derives from state"
            print("38.4A OK: one dot @+1 = converse; a non-compiling pattern changes nothing")

            # ---- 38.4B: panel row; the judge dot's glyph cycle walks the modes -------
            paint("mock", 1)                           # two dots @+1 (bare overlay again)
            paint("mock", 2)                           # + a judge dot → fusion, judge = mock
            assert val("#mode") == "fusion", "N dots @+1 + a judge @+2 compiles to a panel round"
            assert page.text_content("#mode-toggle").startswith("fusion"), "painting updates the chip"
            assert not page.eval_on_selector("#composer-advanced", "el => el.classList.contains('hidden')"), \
                "the compile goes through the picker pathway — the disclosure opens"
            assert checked("#panel-pick") == ["mock", "mock_cli"], "panel = the painted dots"
            assert val("#judge-pick") == "mock", "judge = the painted judge, NOT the room default"
            jk = page.get_attribute("#traj-svg .traj-ghost-judge", "data-kind")
            assert jk == "synthesis" and page.get_attribute("#traj-svg .traj-ghost-judge", "fill") != "none", \
                f"a fresh judge dot wears the FILLED synthesis glyph: {jk}"
            assert edges() == 4, "2 ghost fan-outs + 2 fan-ins"
            paint("mock", 2)                           # cycle: synthesis → divergence
            assert val("#mode") == "side_by_side", "the ring glyph IS side-by-side (exactly 2 seats)"
            assert checked("#sxs-pick") == ["mock", "mock_cli"] and val("#sxs-judge") == "mock"
            assert page.get_attribute("#traj-svg .traj-ghost-judge", "data-kind") == "divergence"
            paint("mock", 2)                           # cycle: divergence → map
            assert val("#mode") == "mapping", "the diamond glyph IS mapping"
            assert page.eval_on_selector("#traj-svg .traj-ghost-judge", "el => el.tagName") == "polygon"
            paint("mock", 2)                           # cycle: map → off; two dots, no judge
            assert val("#mode") == "mapping", "cycling the judge OFF leaves the last valid state"
            assert page.locator("#traj-svg .traj-ghost-judge").count() == 0 and edges() == 0
            print("38.4B OK: glyph cycle filled→ring→diamond→off = fusion→side-by-side→mapping→(invalid)")

            # ---- 38.4C: the human dot discriminates yes-and from panel-of-1 ----------
            paint("mock_cli", 1)                       # → {mock}@+1: converse → mock
            assert val("#mode") == "converse" and val("#addressee") == "mock"
            paint("mock_cli", 2)                       # A@+1, B@+2, NO human dot
            assert val("#mode") == "fusion", "A-then-B without the human dot is a 1-panel round judged by B"
            assert checked("#panel-pick") == ["mock"] and val("#judge-pick") == "mock_cli"
            assert page.get_attribute("#traj-svg .traj-ghost-judge", "data-kind") == "synthesis"
            paint("human", 3)                          # the discriminator
            assert val("#mode") == "yes_and", "the human dot flips the reading to yes-and"
            assert val("#ya-a") == "mock" and val("#ya-b") == "mock_cli", "A first, B second"
            assert page.text_content("#mode-toggle").startswith("yes-and")
            assert page.locator("#traj-svg .traj-ghost-judge").count() == 0, \
                "a yes-and second dot is a PLAIN vertex — no glyph"
            b_fill = page.eval_on_selector(
                '#traj-svg .traj-ghost-node[data-lane="mock_cli"][data-frow="2"]',
                "el => el.getAttribute('fill')")
            assert b_fill == "none", f"B stays hollow: {b_fill}"
            assert ["human", "3"] in gnodes() and edges() == 3, "the chain ends on the human ring"
            paint("human", 3)                          # …and the discriminator works in reverse
            assert val("#mode") == "fusion" and checked("#panel-pick") == ["mock"] \
                and val("#judge-pick") == "mock_cli", "removing the human dot restores the judged reading"
            print("38.4C OK: the same A/B dots read panel-of-1 vs yes-and purely by the human dot")

            # ---- 38.4D: state-not-gesture; room-switch isolation ---------------------
            paint("mock", 4)                           # +4 can never compile → bare overlay
            assert ["mock", "4"] in gnodes() and val("#mode") == "fusion"
            page.select_option("#mode", "converse")    # the PICKER moves → dots re-derive
            page.wait_for_timeout(80)
            assert ["mock", "4"] not in gnodes(), "a picker change must drop the overlay (state, not gesture)"
            assert gnodes() == [["mock", "1"]], f"converse ghost re-derived: {gnodes()}"
            paint("mock", 4)
            assert ["mock", "4"] in gnodes()
            open_room(page, "p38 fusion")
            page.wait_for_selector("#traj-svg .traj-fan-out")
            assert ["mock", "4"] not in gnodes(), "paint must not follow you across rooms"
            open_room(page, "p38 paint")
            page.wait_for_selector("#traj-svg .traj-hit-future")
            assert ["mock", "4"] not in gnodes(), "paint resets on room switch — no stale overlay on return"
            print("38.4D OK: picker re-derives the dots; the overlay neither crosses rooms nor survives a return")

            # ---- 38.4E: send consumes the paint --------------------------------------
            paint("mock", 5)
            assert ["mock", "5"] in gnodes()
            page.fill("#input", "consume the paint")
            page.click("#send-btn")
            page.wait_for_function(
                "document.querySelectorAll('#traj-svg .traj-hit').length === 4", timeout=30000)
            assert ["mock", "5"] not in gnodes(), "send must clear the paint (the round consumed it)"
            assert edges() == 1, "back to the derived converse ghost"
            print("38.4E OK: send clears the paint and the future re-derives from state")

            # ---- 38.4F: the margin rail's future column; past clicks still jump ------
            mode_before = val("#mode")
            page.click('.traj-hit-future[data-margin-rail="1"]')
            page.wait_for_selector("#margin:not(.hidden)")
            assert page.evaluate("document.activeElement && document.activeElement.id") == "margin-input", \
                "the margin click must focus the margin input"
            assert val("#mode") == mode_before, "asking sideways touches no sticky state"
            page.click("#margin-close")
            page.click('.traj-hit[data-row="0"]')
            page.wait_for_selector("#stream .jump-flash")
            print("38.4F OK: margin future column opens + focuses the pane; click-to-jump untouched")

            assert not errs, f"page errors: {errs}"
            br.close()
        print("\nPHASE 38 (trajectory interaction layer): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
