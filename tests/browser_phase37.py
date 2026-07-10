"""browser_phase37.py — the trajectory graph rail (Chromium).

  37.2: the rail is a body-level sibling outside .workspace; the `graph` button toggles it;
        `trajectory_open` round-trips ui.json and survives a hard reload (no localStorage).
  37.3: lanes = participants ∪ observed speakers (a departed seat still gets a lane);
        bright vertices for exactly the forward turns, dim nodes for exactly the
        is_panelist_raw turns — incl. the judge-as-panelist dual-node lane; yes-and renders
        as two ordinary bright converse vertices; data-turn-id on prompt/panel/synthesis/
        converse nodes; clicking a graph row brings its turn into view; a scrolled-up
        transcript survives a render() (no yank) while a room switch still lands at bottom.
  37.4: margin connectors + brackets from window_ids; a legacy margin turn (policy string
        only) gets a best-effort connector and NO bracket; rollback past windowed rows
        clamps or drops the bracket without crashing.

Run:  python tests/browser_phase37.py   (needs playwright + chromium)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
PORT = 8847
BASE = f"http://127.0.0.1:{PORT}"
HOME = Path("/tmp/p37browser")


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


# First document index of each graph layer. SVG has no z-index — document order is depth.
PAINT_ORDER_JS = """() => {
  const ch = [...document.querySelector('#traj-svg').children];
  const first = (c) => ch.findIndex((e) => e.classList.contains(c));
  return { conn: first('traj-connector'), lane: first('traj-lane'), fan: first('traj-fan-out'),
           line: first('traj-line'), panel: first('traj-panel'), vertex: first('traj-vertex'),
           hit: first('traj-hit') };
}"""


def endpoints(d):
    """Start and end point of a swervePath `d` string, curved or straight."""
    m = re.match(r"^M ([\d.]+) ([\d.]+) [LC] .*?([\d.]+) ([\d.]+)$", d)
    assert m, f"unparseable path: {d}"
    return (float(m.group(1)), float(m.group(2))), (float(m.group(3)), float(m.group(4)))


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
        # All rooms are seeded BEFORE page.goto so the sidebar lists them. Every fixture is
        # synthesized through the real API + mock providers — the vault has no yes-and,
        # mapping or promoted-note example to lean on.
        conv = _json("/rooms", "POST", {"title": "p37 conv"})["room"]["id"]
        _json(f"/rooms/{conv}", "PUT", {"participants": ["mock"], "judge": "mock"})
        for q in ("first question", "second question"):
            _json(f"/rooms/{conv}/run", "POST", {"mode": "converse", "prompt": q, "target": "mock"})
        # a departed speaker: a turn whose seat is in no roster and no registry (the deleted-provider
        # case — 7 real rooms have one). Hand-appended: by construction it cannot be produced by the API.
        ghost = {"id": "ghost-turn-0001", "ts": "2026-07-10T00:00:00Z", "mode": "converse",
                 "role": "ai", "speaker": "ghost", "text": "a departed seat", "meta": {}}
        with (HOME / "vault" / conv / "main.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(ghost) + "\n")

        # fusion: judge is ALSO a panelist → the same lane carries a dim node and a bright vertex
        fus = _json("/rooms", "POST", {"title": "p37 fusion"})["room"]["id"]
        _json(f"/rooms/{fus}", "PUT", {"participants": ["mock", "mock_cli"], "judge": "mock"})
        _json(f"/rooms/{fus}/run", "POST", {"mode": "fusion", "prompt": "fuse this",
                                            "panel": ["mock", "mock_cli"], "judge": "mock"})
        # a converse follow-up, so a bright segment LEAVES the judge (the 37.7 origin-colour
        # check needs one, and the next forward speaker — you — differs from it in colour)
        _json(f"/rooms/{fus}/run", "POST", {"mode": "converse", "prompt": "follow-up", "target": "mock"})

        # yes-and: two sequential forward answers, stamped as ordinary converse turns
        ya = _json("/rooms", "POST", {"title": "p37 yesand"})["room"]["id"]
        _json(f"/rooms/{ya}", "PUT", {"participants": ["mock", "mock_cli"], "judge": "mock"})
        _json(f"/rooms/{ya}/run", "POST", {"mode": "yes_and", "prompt": "build on this",
                                           "seats": ["mock", "mock_cli"]})

        # THREE panelists — enough lanes that "human strictly between" and "all dots share a row"
        # are falsifiable, and enough that a per-turn row model would show a visible staircase.
        f3 = _json("/rooms", "POST", {"title": "p37 fan3"})["room"]["id"]
        _json(f"/rooms/{f3}", "PUT", {"participants": ["mock", "mock_cli", "mockthink"], "judge": "mock"})
        _json(f"/rooms/{f3}/run", "POST", {"mode": "fusion", "prompt": "three ways",
                                          "panel": ["mock", "mock_cli", "mockthink"], "judge": "mock"})

        # the other two panel modes, for the judge glyph (37.5B)
        sxs = _json("/rooms", "POST", {"title": "p37 sxs"})["room"]["id"]
        _json(f"/rooms/{sxs}", "PUT", {"participants": ["mock", "mock_cli"], "judge": "mock"})
        _json(f"/rooms/{sxs}/run", "POST", {"mode": "side_by_side", "prompt": "compare",
                                            "seats": ["mock", "mock_cli"], "judge": "mock"})
        mp = _json("/rooms", "POST", {"title": "p37 map"})["room"]["id"]
        _json(f"/rooms/{mp}", "PUT", {"participants": ["mock", "mock_cli"], "judge": "mock"})
        _json(f"/rooms/{mp}/run", "POST", {"mode": "mapping", "prompt": "map this",
                                           "panel": ["mock", "mock_cli"], "judge": "mock"})

        # A round whose panel turns are all gone (absent, or rolled away) — the chord-suppression
        # exception. Also carries a judge with NO judge_kind (a pre-Phase-26 turn), which must
        # still render as synthesis. Hand-seeded: run_mode cannot produce a panel-less round.
        bare = _json("/rooms", "POST", {"title": "p37 bare"})["room"]["id"]
        _json(f"/rooms/{bare}", "PUT", {"participants": ["mock"], "judge": "mock"})
        with (HOME / "vault" / bare / "main.jsonl").open("w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "bare-h", "ts": "2026-07-10T00:00:00Z", "mode": "research",
                                "role": "human", "speaker": "human", "text": "ask",
                                "meta": {"round_id": "r1"}}) + "\n")
            f.write(json.dumps({"id": "bare-j", "ts": "2026-07-10T00:00:01Z", "mode": "research",
                                "role": "judge", "speaker": "mock", "text": "verdict",
                                "meta": {"round_id": "r1"}}) + "\n")

        # A genuinely TALL room. The scroll assertions below are only meaningful in a
        # transcript that actually overflows #stream — a short one makes every scroll check
        # vacuously true (scrollTop is pinned at 0 because maxScroll is 0).
        # TWO of them: proving the room-switch force-pin needs the room you switch AWAY from to be
        # scrolled up. Switching away from a SHORT room is trivially "at bottom", so it would pin
        # anyway and the assertion could not tell the force-pin from its absence.
        blob = "\n\n".join("lorem ipsum dolor sit amet " * 12 for _ in range(6))

        def seed_tall(title, prefix):
            rid = _json("/rooms", "POST", {"title": title})["room"]["id"]
            _json(f"/rooms/{rid}", "PUT", {"participants": ["mock"], "judge": "mock"})
            with (HOME / "vault" / rid / "main.jsonl").open("w", encoding="utf-8") as f:
                for i in range(24):
                    role, spk = ("human", "human") if i % 2 == 0 else ("ai", "mock")
                    f.write(json.dumps({"id": f"{prefix}-{i:03d}", "ts": "2026-07-10T00:00:00Z",
                                        "mode": "converse", "role": role, "speaker": spk,
                                        "text": f"TURN{i}\n\n{blob}", "meta": {}}) + "\n")
            return rid

        tall = seed_tall("p37 tall", "tall")     # titles must not be substrings of one another:
        seed_tall("p37 deep", "deep")            # the sidebar row locator matches on text
        del tall

        with sync_playwright() as p:
            br = p.chromium.launch(); page = br.new_page(viewport={"width": 1600, "height": 900})
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))   # a dangling id must never throw
            page.goto(BASE + "/", wait_until="networkidle")
            open_room(page, "p37 conv")

            # ---- 37.2A: placement — outside .workspace, sibling of #app -------------
            assert page.locator("#traj-rail").count() == 1, "rail missing"
            placement = page.evaluate("""() => {
              const r = document.querySelector('#traj-rail');
              return { parent: r.parentElement.tagName.toLowerCase(),
                       inWorkspace: !!r.closest('.workspace'),
                       inStream: !!r.closest('#stream'),
                       nextIsApp: r.nextElementSibling && r.nextElementSibling.id === 'app' };
            }""")
            assert placement["parent"] == "body", f"rail must be body-level: {placement}"
            assert not placement["inWorkspace"], "rail must be OUTSIDE .workspace (Phase-34 clamp budget)"
            assert not placement["inStream"], "rail must not be a #stream descendant"
            assert placement["nextIsApp"], f"rail must sit between #sidebar and #app: {placement}"
            print("37.2A OK: rail is a body-level sibling between #sidebar and #app")

            # ---- 37.2B: toggle shows/hides + persists -------------------------------
            assert page.locator("#traj-rail").is_hidden(), "rail should start hidden (default false)"
            assert _json("/ui")["trajectory_open"] is False, "GET /ui must backfill trajectory_open=False"
            page.click("#traj-toggle")
            page.wait_for_selector("#traj-rail:not(.hidden)")
            assert not page.locator("#traj-rail").is_hidden(), "toggle didn't show the rail"
            page.wait_for_timeout(150)
            assert _json("/ui")["trajectory_open"] is True, "trajectory_open not persisted to ui.json"
            page.click("#traj-toggle")
            page.wait_for_timeout(150)
            assert page.locator("#traj-rail").is_hidden(), "toggle didn't hide the rail"
            assert _json("/ui")["trajectory_open"] is False, "close not persisted"
            print("37.2B OK: graph button toggles the rail; state round-trips ui.json")

            # ---- 37.2C: survives a hard reload, no localStorage ---------------------
            page.click("#traj-toggle")
            page.wait_for_selector("#traj-rail:not(.hidden)")
            page.wait_for_timeout(150)
            assert page.evaluate("window.localStorage.length") == 0, "localStorage used (forbidden)"
            page.reload(wait_until="networkidle")
            assert not page.locator("#traj-rail").is_hidden(), "rail did not survive a hard reload"
            assert page.evaluate("window.localStorage.length") == 0, "localStorage populated after reload"
            # the silent-revert trap: _UI_DEFAULT must carry the key, not just UIBody
            raw = json.loads((HOME / "ui.json").read_text())
            assert raw.get("trajectory_open") is True, f"ui.json did not store the key: {raw}"
            print("37.2C OK: trajectory_open reconstructs from ui.json after a hard reload")

            # ================= 37.3 — the graph ==================================
            open_room(page, "p37 conv")
            page.wait_for_selector("#traj-svg .traj-node")

            # ---- 37.3A: lanes = participants ∪ observed speakers ------------------
            lanes = page.evaluate("trajLanes()")
            assert lanes == ["mock", "human", "ghost"], f"lane order/union wrong: {lanes}"
            ghost_fill = page.get_attribute('.traj-node[data-turn-id="ghost-turn-0001"]', "fill")
            assert ghost_fill.lower() == "#9aa3b2", f"departed speaker should be DOT_DEFAULT grey: {ghost_fill}"
            n_nodes = page.locator("#traj-svg .traj-node").count()
            n_turns = len(_json(f"/rooms/{conv}")["turns"])
            assert n_nodes == n_turns, f"one node per turn: {n_nodes} vs {n_turns}"
            assert page.locator("#traj-svg .traj-lane").count() == 3, "one lane guide per speaker"
            assert page.locator("#traj-svg .traj-line").count() == n_turns - 1, \
                "the bright line joins every forward turn"
            print(f"37.3A OK: lanes {lanes} (departed seat kept, grey); one node per turn")

            # ---- 37.3B: bright = forward, dim = is_panelist_raw -------------------
            open_room(page, "p37 fusion")
            page.wait_for_selector("#traj-svg .traj-node")
            fus_turns = _json(f"/rooms/{fus}")["turns"]
            fwd_ids = {t["id"] for t in fus_turns if not (t["meta"] or {}).get("is_panelist_raw")}
            raw_ids = {t["id"] for t in fus_turns if (t["meta"] or {}).get("is_panelist_raw")}
            assert raw_ids, "fixture produced no raw panelist turns"
            got_fwd = set(page.eval_on_selector_all(
                '.traj-node[data-forward="1"]', "els => els.map(e => e.dataset.turnId)"))
            got_dim = set(page.eval_on_selector_all(
                '.traj-node[data-forward="0"]', "els => els.map(e => e.dataset.turnId)"))
            assert got_fwd == fwd_ids, f"bright vertices != forward turns\n{got_fwd}\n{fwd_ids}"
            assert got_dim == raw_ids, f"dim nodes != is_panelist_raw turns\n{got_dim}\n{raw_ids}"
            dim_op = float(page.get_attribute('.traj-node[data-forward="0"]', "fill-opacity"))
            bright_op = float(page.get_attribute('.traj-node[data-forward="1"]', "fill-opacity"))
            lane_op = float(page.get_attribute(".traj-lane", "stroke-opacity"))
            assert lane_op < dim_op < bright_op, \
                f"three registers, in order: lane {lane_op} < panel {dim_op} < forward {bright_op}"
            assert dim_op == 0.55 and bright_op == 1 and lane_op == 0.3, \
                f"registers should be the named OP_* constants: {lane_op}/{dim_op}/{bright_op}"

            # the judge is also a panelist → its lane carries BOTH a dim node and a bright vertex
            judge = next(t for t in fus_turns if t["role"] == "judge")
            raw_same_lane = [t for t in fus_turns
                             if (t["meta"] or {}).get("is_panelist_raw") and t["speaker"] == judge["speaker"]]
            assert raw_same_lane, "fixture must have the judge also sit on the panel"
            xs = page.evaluate(
                """([a, b]) => [a, b].map(id =>
                     document.querySelector(`.traj-node[data-turn-id="${id}"]`).getAttribute('cx'))""",
                [judge["id"], raw_same_lane[0]["id"]])
            assert xs[0] == xs[1], f"judge + its own raw answer must share a lane: {xs}"
            print("37.3B OK: bright == forward, dim == raw panel; judge-as-panelist shares one lane")

            # ---- 37.3C: yes-and = two ordinary bright converse vertices -----------
            open_room(page, "p37 yesand")
            page.wait_for_selector("#traj-svg .traj-node")
            ya_turns = _json(f"/rooms/{ya}")["turns"]
            ai = [t for t in ya_turns if t["role"] == "ai"]
            assert len(ai) == 2 and {t["speaker"] for t in ai} == {"mock", "mock_cli"}, \
                f"yes-and fixture wrong: {[(t['role'], t['speaker']) for t in ya_turns]}"
            assert all(t["mode"] == "converse" and "round_id" not in (t["meta"] or {}) for t in ai), \
                "yes-and answers should be converse-shaped (no round_id)"
            assert page.locator('.traj-node[data-forward="0"]').count() == 0, "yes-and has no dim nodes"
            assert page.locator('.traj-node[data-forward="1"]').count() == len(ya_turns), \
                "every yes-and turn is a bright vertex"
            print("37.3C OK: yes-and draws as two ordinary bright converse vertices")

            # ---- 37.3D: data-turn-id on prompt / panel / synthesis / converse -----
            open_room(page, "p37 fusion")
            page.wait_for_selector(".round .prompt")
            assert page.locator(".round").count() == 1
            assert page.locator(".round[data-turn-id]").count() == 0, "the .round container must NOT be anchored"
            assert page.locator(".round .prompt[data-turn-id]").count() == 1, "prompt not anchored"
            assert page.locator(".round .panel[data-turn-id]").count() == len(raw_ids), "panels not anchored"
            assert page.locator(".round .synthesis[data-turn-id]").count() == 1, "synthesis not anchored"
            open_room(page, "p37 conv")
            page.wait_for_selector("#stream .turn")
            assert page.locator("#stream .turn[data-turn-id]").count() == n_turns, "converse turns not anchored"
            print("37.3D OK: data-turn-id on prompt/panel/synthesis/converse, never on .round")

            # ================= 37.5 — fan, glyph, curves =========================
            # ---- 37.5A: a round is a fan-out/fan-in event, not a chord -------------
            open_room(page, "p37 fusion")
            page.wait_for_selector("#traj-svg .traj-node")
            head = next(t for t in fus_turns if t["role"] == "human")
            judge = next(t for t in fus_turns if t["role"] == "judge")
            panels = [t for t in fus_turns if (t["meta"] or {}).get("is_panelist_raw")]
            assert page.locator(f'.traj-line[data-from="{head["id"]}"][data-to="{judge["id"]}"]').count() == 0, \
                "a fanned round must NOT also draw a direct bright human→judge chord"
            assert page.locator("#traj-svg .traj-line").count() == 2, \
                "chord suppressed; only the follow-up's two segments (judge→human→ai) remain"
            assert page.locator("#traj-svg .traj-fan-out").count() == len(panels), "one fan-out edge per panelist"
            assert page.locator("#traj-svg .traj-fan-in").count() == len(panels), "one fan-in edge per panelist"
            for p in panels:      # edges are anchored to real turns, not just counted
                assert page.locator(f'.traj-fan-out[data-from="{head["id"]}"][data-to="{p["id"]}"]').count() == 1
                assert page.locator(f'.traj-fan-in[data-from="{p["id"]}"][data-to="{judge["id"]}"]').count() == 1
            fan_op = float(page.get_attribute(".traj-fan-out", "stroke-opacity"))
            assert fan_op == 0.55, f"fan edges sit at the mid register: {fan_op}"

            # ORIGIN colour (37.7): a stroke carries the voice of whoever just spoke; the dot is
            # where the colour changes hands. Falsifiability first — every colour compared below
            # must differ in the fixture, or an assertion couldn't fail. The fan-in is asserted on
            # the panelist whose colour differs from the judge's: for the judge's own panel turn
            # origin- and destination-colouring coincide and nothing would be tested (the mirror
            # of the 37.5 vacuity fix, which had the same blind spot the other way round).
            node_fill = lambda tid: page.get_attribute(f'.traj-node[data-turn-id="{tid}"]', "fill")
            other = next(p for p in panels if p["speaker"] != judge["speaker"])
            human_col, judge_col, other_col = node_fill(head["id"]), node_fill(judge["id"]), node_fill(other["id"])
            assert judge_col != other_col, "fixture must give the judge and this panelist different colours"
            assert human_col not in (judge_col, other_col), \
                "fixture must give the human a colour no panelist shares"
            out_strokes = set(page.eval_on_selector_all(
                "#traj-svg .traj-fan-out", "els => els.map(e => e.getAttribute('stroke'))"))
            assert out_strokes == {human_col}, \
                f"every fan-out edge carries its ORIGIN's (the round-head's) colour: {out_strokes}"
            assert page.get_attribute(f'.traj-fan-in[data-from="{other["id"]}"]', "stroke") == other_col, \
                "a fan-in edge carries its ORIGIN panelist's own colour into the judge"

            # …and the bright segment LEAVING the judge is judge-coloured, not next-speaker-coloured
            j_at = next(i for i, t in enumerate(fus_turns) if t["id"] == judge["id"])
            follow = next(t for t in fus_turns[j_at + 1:] if not (t["meta"] or {}).get("is_panelist_raw"))
            assert node_fill(follow["id"]) != judge_col, \
                "fixture: the speaker after the judge must differ from it in colour"
            seg = page.get_attribute(f'.traj-line[data-from="{judge["id"]}"][data-to="{follow["id"]}"]', "stroke")
            assert seg == judge_col, f"the segment leaving the judge carries the judge's voice: {seg}"

            # judge-as-panelist: its own fan-in runs straight DOWN its lane to the bright vertex
            same_lane = next(p for p in panels if p["speaker"] == judge["speaker"])
            d_same = page.get_attribute(f'.traj-fan-in[data-from="{same_lane["id"]}"]', "d")
            assert " C " not in d_same and " L " in d_same, \
                f"a same-lane fan-in is a straight vertical, not a curve: {d_same}"
            print(f"37.5A OK: fusion round draws {len(panels)} fan-out + {len(panels)} fan-in, no chord")

            # ---- 37.5A: a round with NO surviving panel turns keeps its chord ------
            open_room(page, "p37 bare")
            page.wait_for_selector("#traj-svg .traj-node")
            assert page.locator('.traj-line[data-from="bare-h"][data-to="bare-j"]').count() == 1, \
                "a panel-less round must keep its direct segment — the line may never break"
            assert page.locator("#traj-svg .traj-fan-out").count() == 0
            assert page.locator("#traj-svg .traj-fan-in").count() == 0
            # the exception chord obeys the same origin rule: human-coloured, no special case
            assert node_fill("bare-h") != node_fill("bare-j"), \
                "fixture: human and judge colours must differ for the chord check to bite"
            assert page.get_attribute('.traj-line[data-from="bare-h"][data-to="bare-j"]', "stroke") \
                == node_fill("bare-h"), "the exception chord is ORIGIN (human) coloured"
            print("37.5A OK: panel-less round keeps an unbroken, human-coloured bright segment")

            # ---- 37.5B: the judge glyph carries the round's kind -------------------
            glyph_of = lambda: page.eval_on_selector(
                "#traj-svg .traj-node[data-judge-kind]",
                "el => [el.tagName.toLowerCase(), el.getAttribute('data-judge-kind'), el.getAttribute('fill')]")
            tag, kind, fill = glyph_of()
            assert (tag, kind) == ("circle", "synthesis") and fill != "none", \
                f"a judge turn with NO judge_kind must read as synthesis: {tag}/{kind}/{fill}"
            assert "judge_kind" not in (_json(f"/rooms/{bare}")["turns"][1]["meta"] or {}), \
                "the bare fixture must genuinely lack judge_kind, or the check is vacuous"
            open_room(page, "p37 fusion"); page.wait_for_selector("#traj-svg .traj-node[data-judge-kind]")
            tag, kind, fill = glyph_of()
            assert (tag, kind) == ("circle", "synthesis") and fill != "none", f"fusion → filled circle: {tag}/{kind}/{fill}"
            open_room(page, "p37 sxs"); page.wait_for_selector("#traj-svg .traj-node[data-judge-kind]")
            tag, kind, fill = glyph_of()
            assert (tag, kind, fill) == ("circle", "divergence", "none"), f"side-by-side → ring: {tag}/{kind}/{fill}"
            assert page.get_attribute(".traj-node[data-judge-kind]", "stroke-width") == "1.5"
            open_room(page, "p37 map"); page.wait_for_selector("#traj-svg .traj-node[data-judge-kind]")
            tag, kind, _ = glyph_of()
            assert (tag, kind) == ("polygon", "map"), f"mapping → diamond: {tag}/{kind}"
            print("37.5B OK: judge glyph = circle / ring / diamond by judge_kind (absent → synthesis)")

            # ---- 37.5D: lane changes swerve; vertical tangency at both ends --------
            open_room(page, "p37 conv")
            page.wait_for_selector("#traj-svg .traj-line")
            ds = page.eval_on_selector_all("#traj-svg .traj-line", "els => els.map(e => [e.tagName.toLowerCase(), e.getAttribute('d')])")
            curved = [d for tag, d in ds if " C " in d]
            assert all(tag == "path" for tag, _ in ds), f"trajectory segments must be <path>: {ds}"
            assert curved, "a human→model lane change must curve"
            for d in curved:
                m = re.match(r"^M ([\d.]+) ([\d.]+) C ([\d.]+) [\d.]+, ([\d.]+) [\d.]+, ([\d.]+) ([\d.]+)$", d)
                assert m, f"unexpected path shape: {d}"
                x0, _y0, c1x, c2x, x1, _y1 = m.groups()
                assert c1x == x0 and c2x == x1, \
                    f"control points must share their endpoint's x (vertical tangency): {d}"
                assert x0 != x1, "a curved segment must actually change lane"
            caps = page.eval_on_selector_all(
                "#traj-svg .traj-lane, #traj-svg .traj-line, #traj-svg .traj-node",
                "els => [...new Set(els.map(e => getComputedStyle(e).strokeLinecap))]")
            assert caps == ["round"], f"all graph strokes carry round linecaps: {caps}"
            # hit geometry stays separate from the drawn paths (the deferred drag-to-direct layer)
            assert page.locator("#traj-svg path[data-turn-id]").count() == 0, \
                "no path may be a hit target — hit rects and vertex circles own that"
            assert page.eval_on_selector(".traj-hit", "el => el.tagName.toLowerCase()") == "rect"
            print("37.5D OK: lane changes are vertically-tangent Béziers; hit geometry stays separate")

            # ================= 37.6 — logical rows + centred human lane ===========
            open_room(page, "p37 fan3")
            page.wait_for_selector("#traj-svg .traj-panel")
            f3_turns = _json(f"/rooms/{f3}")["turns"]
            f3_head = next(t for t in f3_turns if t["role"] == "human")
            f3_judge = next(t for t in f3_turns if t["role"] == "judge")
            f3_panels = [t for t in f3_turns if (t["meta"] or {}).get("is_panelist_raw")]
            assert len(f3_panels) >= 2, f"the row-sharing check needs ≥2 panelists: {len(f3_panels)}"

            # ---- 37.6A: the panel is one row, not a staircase ---------------------
            cys = page.eval_on_selector_all("#traj-svg .traj-panel", "els => els.map(e => +e.getAttribute('cy'))")
            assert len(cys) == len(f3_panels) and len(set(cys)) == 1, \
                f"all {len(f3_panels)} panel dots must share one row: {cys}"
            panel_y = cys[0]
            assert page.locator("#traj-svg .traj-hit").count() == 3 < len(f3_turns), \
                "a fusion round is three logical rows (prompt / panel band / judge), not one per turn"

            # fan-out edges all arrive at that row; fan-in edges all leave it
            outs = page.eval_on_selector_all("#traj-svg .traj-fan-out", "els => els.map(e => e.getAttribute('d'))")
            ins = page.eval_on_selector_all("#traj-svg .traj-fan-in", "els => els.map(e => e.getAttribute('d'))")
            assert len(outs) == len(ins) == len(f3_panels)
            assert {endpoints(d)[1][1] for d in outs} == {panel_y}, "fan-out edges must all land on the panel row"
            assert {endpoints(d)[0][1] for d in ins} == {panel_y}, "fan-in edges must all leave the panel row"
            head_pts = {endpoints(d)[0] for d in outs}
            assert len(head_pts) == 1, f"every fan-out leaves the one human vertex: {head_pts}"
            print(f"37.6A OK: {len(f3_panels)} panelists share one row; the fan is simultaneous")

            # ---- 37.6A: per-row hit geometry; dots stay per-turn targets ----------
            row1 = page.get_attribute('.traj-hit[data-row="1"]', "data-turn-id")
            assert row1 == f3_head["id"], f"a panel row's hit-rect jumps to the round's prompt: {row1}"
            flashed = lambda: page.eval_on_selector_all(
                "#stream .jump-flash", "els => els.map(e => e.dataset.turnId)")
            for p in f3_panels[:2]:                       # two different dots, one row, two targets
                page.click(f'.traj-hit-node[data-turn-id="{p["id"]}"]')
                page.wait_for_timeout(120)
                assert flashed() == [p["id"]], f"a panel dot must jump to its own turn: {flashed()} != {p['id']}"
                page.wait_for_timeout(1150)               # let the flash expire before the next click
            page.click('.traj-hit[data-row="1"]', position={"x": 4, "y": 6})   # off every lane
            page.wait_for_timeout(120)
            assert flashed() == [f3_head["id"]], f"the panel row-rect jumps to the prompt: {flashed()}"
            print("37.6A OK: panel dots are distinct per-turn targets; the row-rect targets the prompt")

            # ---- 37.6B: the human lane sits in the middle -------------------------
            lanes3 = page.evaluate("trajLanes()")
            models3 = [k for k in lanes3 if k != "human"]
            assert len(models3) == 3, f"fixture needs 3 model lanes for 'between' to be falsifiable: {lanes3}"
            assert lanes3.index("human") == len(models3) // 2 == 1, f"human at floor(n/2): {lanes3}"
            xs = page.evaluate("""(keys) => Object.fromEntries(keys.map(k =>
                 [k, +document.querySelector(`.traj-lane[data-lane="${k}"]`).getAttribute('x1')]))""", lanes3)
            model_xs = [xs[k] for k in models3]
            assert min(model_xs) < xs["human"] < max(model_xs), \
                f"the human lane must sit strictly between the model lanes: {xs}"

            # even model count → index floor(n/2) too
            open_room(page, "p37 fusion")
            page.wait_for_selector("#traj-svg .traj-node")
            lanes2 = page.evaluate("trajLanes()")
            models2 = [k for k in lanes2 if k != "human"]
            assert len(models2) == 2 and lanes2.index("human") == len(models2) // 2 == 1, \
                f"even model count: human at floor(n/2): {lanes2}"

            # full paint order, back to front, on a room that has every layer
            open_room(page, "p37 fan3")
            page.wait_for_selector("#traj-svg .traj-panel")
            o = page.evaluate(PAINT_ORDER_JS)
            assert o["lane"] < o["fan"] < o["panel"] < o["vertex"] < o["hit"], f"paint order: {o}"
            print(f"37.6B OK: human lane centred at index {lanes3.index('human')}; paint order back-to-front")

            # ---- 37.3E/F run in the TALL room: #stream must genuinely overflow, or every
            #      scroll assertion below is vacuously true (scrollTop clamps to 0 at maxScroll=0).
            open_room(page, "p37 tall")
            page.wait_for_selector("#traj-svg .traj-node")
            geom = page.eval_on_selector("#stream", "el => ({max: el.scrollHeight - el.clientHeight})")
            assert geom["max"] > 500, f"the scroll fixture must overflow #stream, else the test proves nothing: {geom}"
            bottom_of = lambda: page.eval_on_selector("#stream", "el => el.scrollTop")
            at_bottom = lambda: page.eval_on_selector(
                "#stream", "el => el.scrollTop + el.clientHeight >= el.scrollHeight - 40")

            # ---- 37.3E: click a graph row → the transcript actually MOVES there ----
            page.eval_on_selector("#stream", "el => el.scrollTop = el.scrollHeight")
            page.wait_for_timeout(80)
            assert bottom_of() > 500, "precondition: start genuinely at the bottom"
            page.click('.traj-hit[data-turn-id="tall-000"]')
            page.wait_for_timeout(250)
            moved = bottom_of()
            assert moved < 200, f"clicking the first row must scroll back up, not sit at the bottom: {moved}"
            visible = page.evaluate("""(id) => {
              const el = document.querySelector(`#stream [data-turn-id="${id}"]`);
              const s = document.querySelector('#stream');
              const a = el.getBoundingClientRect(), b = s.getBoundingClientRect();
              return a.bottom > b.top && a.top < b.bottom;
            }""", "tall-000")
            assert visible, "clicking a graph row did not bring its turn into view"
            # …and a middle row lands in the middle, not at either end
            page.click('.traj-hit[data-turn-id="tall-012"]')
            page.wait_for_timeout(250)
            mid = bottom_of()
            assert 200 < mid < geom["max"] - 200, f"a middle row should land mid-transcript: {mid}"
            print("37.3E OK: clicking a graph row scrolls the transcript to that turn")

            # ---- 37.3F: the pin is conditional AND position-preserving -------------
            # This must fail for BOTH the old unconditional pin (→ bottom) and a naive
            # rebuild that drops scrollTop (→ 0). Only "leave it exactly where it was" passes.
            page.eval_on_selector("#stream", "el => el.scrollTop = 800")
            page.wait_for_timeout(60)
            page.evaluate("render()")
            page.wait_for_timeout(60)
            kept = bottom_of()
            assert abs(kept - 800) < 5, \
                f"render() must preserve a mid-scroll reading position exactly (800), got {kept}"
            assert not at_bottom(), "render() pinned a scrolled-up reader to the bottom"

            # at the bottom, render() still follows (this is what a streaming frame relies on)
            page.eval_on_selector("#stream", "el => el.scrollTop = el.scrollHeight")
            page.wait_for_timeout(60)
            page.evaluate("render()")
            page.wait_for_timeout(60)
            assert at_bottom(), "render() must keep following the bottom for a reader who is at it"

            # A room SWITCH force-pins, even when leaving a scrolled-up view. render() decides the
            # pin from the OUTGOING transcript's scroll state, so the room we leave must itself be
            # tall and scrolled up — otherwise "at bottom" is trivially true and pins regardless.
            page.eval_on_selector("#stream", "el => el.scrollTop = 0")
            page.wait_for_timeout(60)
            open_room(page, "p37 deep")
            page.wait_for_timeout(150)
            assert page.eval_on_selector("#stream", "el => el.scrollHeight - el.clientHeight") > 500, \
                "the room switched INTO must also overflow, else at_bottom is vacuous"
            assert at_bottom() and bottom_of() > 500, \
                f"a room switch must force-pin to the bottom, got scrollTop={bottom_of()}"
            open_room(page, "p37 tall")
            page.wait_for_timeout(150)

            # …and sending from scrollback still shows you your own message. Without send()'s
            # force-pin, scrollTop would stay at 0 through the optimistic paint, every streaming
            # frame and the final adopt — so the end state discriminates.
            page.eval_on_selector("#stream", "el => el.scrollTop = 0")
            page.wait_for_timeout(60)
            page.fill("#input", "sent from scrollback")
            page.press("#input", "Enter")
            page.wait_for_selector('#stream .turn.human:has-text("sent from scrollback")', timeout=20000)
            page.wait_for_selector(".turn.pending", state="detached", timeout=20000)
            page.wait_for_selector(".turn.streaming", state="detached", timeout=20000)
            page.wait_for_timeout(150)
            assert at_bottom() and bottom_of() > 500, \
                f"sending while scrolled up must pin to your own new message, got {bottom_of()}"
            print("37.3F OK: render() preserves scrollback exactly; bottom follows; switch + send force-pin")

            # ================= 37.4 — margin rail ================================
            # ---- 37.4A: ask the margin (last_1) → connector + bracket on the last forward row,
            #             WITHOUT leaving the room (proves the marginSend redraw hook) ----
            open_room(page, "p37 conv")
            page.wait_for_selector("#traj-svg .traj-node")
            assert page.locator("#traj-svg .traj-margin-rail").count() == 0, "no margin yet → no rail"
            page.click("#margin-toggle")
            page.wait_for_selector("#margin:not(.hidden)")
            page.select_option("#margin-model", "mock")
            page.select_option("#margin-window", "last_1")
            page.fill("#margin-input", "a side question")
            page.click("#margin-send")
            # attached, not visible: an SVG <line> has a zero-width bounding box by definition
            page.wait_for_selector("#traj-svg .traj-bracket", state="attached", timeout=15000)
            assert page.locator("#traj-svg .traj-margin-rail").count() == 1, "margin rail missing"
            assert page.locator("#traj-svg .traj-connector").count() == 1, "one connector per question"
            assert page.locator("#traj-svg .traj-approx").count() == 0, "window_ids present → not approximate"

            turns = _json(f"/rooms/{conv}")["turns"]
            mturns = _json(f"/rooms/{conv}")["margin_turns"]
            q = next(t for t in mturns if t["role"] == "human")
            assert q["meta"]["window_ids"] == [turns[-1]["id"]], \
                f"last_1 should window exactly the last forward turn: {q['meta']}"
            # last_1 → a one-row bracket straddling the last row; the connector lands on it
            geo = page.evaluate("""() => {
              const b = document.querySelector('.traj-bracket');
              const c = document.querySelector('.traj-connector');
              const n = document.querySelectorAll('.traj-node');
              const last = n[n.length - 1];
              return { y1: +b.getAttribute('y1'), y2: +b.getAttribute('y2'),
                       cy: +c.getAttribute('y1'), lastRow: +last.getAttribute('cy') };
            }""")
            assert geo["cy"] == geo["lastRow"], f"connector must land on the last forward row: {geo}"
            assert geo["y1"] < geo["lastRow"] < geo["y2"], f"bracket must straddle its row: {geo}"
            assert geo["y2"] - geo["y1"] == 6, f"a last_1 bracket is a 6px tick, not a zero-length line: {geo}"
            print("37.4A OK: margin connector + bracket appear live, anchored by window_ids")

            # ---- 37.5C: the connector spans human lane → rail, with a terminal dot ----
            span = page.evaluate("""() => {
              const c = document.querySelector('.traj-connector');
              const d = document.querySelector('.traj-margin-dot');
              const rail = document.querySelector('.traj-margin-rail');
              const humanLane = document.querySelector('.traj-lane[data-lane="human"]');
              return { tag: c.tagName.toLowerCase(),
                       y1: +c.getAttribute('y1'), y2: +c.getAttribute('y2'),
                       cx1: +c.getAttribute('x1'), cx2: +c.getAttribute('x2'),
                       railX: +rail.getAttribute('x1'), humanX: +humanLane.getAttribute('x1'),
                       dotX: +d.getAttribute('cx'), dotY: +d.getAttribute('cy'),
                       dotFill: d.getAttribute('fill'), stroke: c.getAttribute('stroke') };
            }""")
            assert span["tag"] == "line" and span["y1"] == span["y2"], \
                f"the connector is a straight horizontal indicator, never a curve: {span}"
            assert {span["cx1"], span["cx2"]} == {span["railX"], span["humanX"]}, \
                f"the connector must span human lane → margin rail: {span}"
            assert span["dotX"] == span["humanX"] and span["dotY"] == span["y1"], \
                f"the terminal dot sits on the human lane at the anchor row: {span}"
            assert span["dotFill"] == span["stroke"], \
                f"the terminal dot takes the CONNECTOR's colour, not the human lane's: {span}"
            # With the human lane centred the connector crosses the right-half model lanes, so it
            # must paint BEHIND them. SVG has no z-index: document order is depth.
            order = page.evaluate(PAINT_ORDER_JS)
            assert 0 <= order["conn"] < order["lane"], f"connectors must paint behind lane guides: {order}"
            assert order["conn"] < order["vertex"] < order["hit"], f"paint order wrong: {order}"
            print("37.5C OK: connector spans human lane → rail, terminal dot in connector grey, behind the lanes")

            # ---- 37.4B: rollback past the windowed rows → clamp or vanish, no crash ----
            before = len(_json(f"/rooms/{conv}")["turns"])
            page.on("dialog", lambda d: d.accept())     # the rollback confirm()
            page.click("#rollback-btn")
            page.wait_for_function("!document.querySelector('#banner').classList.contains('hidden')")
            after = _json(f"/rooms/{conv}")["turns"]
            assert len(after) < before, "rollback removed nothing"
            # the windowed turn is gone, but the margin turn survives (margin.jsonl is never truncated)
            assert q["meta"]["window_ids"][0] not in {t["id"] for t in after}, "windowed row should be gone"
            assert len(_json(f"/rooms/{conv}")["margin_turns"]) == len(mturns), "rollback must not touch the margin"
            assert page.locator("#traj-svg .traj-margin-rail").count() == 1, "the margin rail still stands"
            assert page.locator("#traj-svg .traj-bracket").count() == 0, \
                "every windowed id dangles → the bracket must vanish, not point off the end"
            assert page.locator("#traj-svg .traj-connector").count() == 0, "a dangling connector must not be drawn"
            assert page.locator("#traj-svg .traj-node").count() == len(after), "graph didn't re-derive after rollback"
            assert not errs, f"a dangling window_id threw: {errs}"
            print("37.4B OK: rollback past the window drops the bracket, no crash, graph re-derives")

            br.close()

        # ---- 37.4C: a LEGACY margin turn (policy string, no window_ids) ------------
        # Hand-written: by construction the engine can no longer produce one.
        legacy = _json("/rooms", "POST", {"title": "p37 legacy"})["room"]["id"]
        _json(f"/rooms/{legacy}", "PUT", {"participants": ["mock"], "judge": "mock"})
        _json(f"/rooms/{legacy}/run", "POST", {"mode": "converse", "prompt": "hello", "target": "mock"})
        lturns = _json(f"/rooms/{legacy}")["turns"]
        late = max(t["ts"] for t in lturns)
        with (HOME / "vault" / legacy / "margin.jsonl").open("w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "legacy-q", "ts": late, "mode": "margin", "role": "human",
                                "speaker": "human", "text": "old style", "meta": {"window": "last_3"}}) + "\n")
            f.write(json.dumps({"id": "legacy-a", "ts": late, "mode": "margin", "role": "ai",
                                "speaker": "mock", "text": "old answer", "meta": {"model": "mock-1"}}) + "\n")
        with sync_playwright() as p:
            br = p.chromium.launch(); page = br.new_page(viewport={"width": 1600, "height": 900})
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.goto(BASE + "/", wait_until="networkidle")
            open_room(page, "p37 legacy")
            page.wait_for_selector("#traj-svg .traj-node")
            assert page.locator("#traj-svg .traj-margin-rail").count() == 1, "legacy margin still gets a rail"
            assert page.locator("#traj-svg .traj-connector.traj-approx").count() == 1, \
                "legacy margin should get one best-effort connector"
            assert page.locator("#traj-svg .traj-bracket").count() == 0, \
                "a legacy (policy-string) margin must NOT be bracketed — the ts rule can over-include"
            title = page.eval_on_selector(".traj-approx title", "el => el.textContent")
            assert "approximate" in title, f"the approximation should be admitted in the title: {title!r}"
            assert not errs, f"page errors on the legacy path: {errs}"
            print("37.4C OK: legacy margin → best-effort connector, no bracket, no crash")
            br.close()
        print("\nPHASE 37 (trajectory graph): ALL CHECKS PASS")
    finally:
        srv.terminate()
        try: srv.wait(timeout=5)
        except Exception: srv.kill()


if __name__ == "__main__":
    main()
