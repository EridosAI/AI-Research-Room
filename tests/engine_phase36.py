"""engine_phase36.py — converse streaming: adapter deltas + engine threading (offline).

Phase 36.1/36.2. Streaming is a DISPLAY channel; the JSONL append is unchanged (one final
line, full text+meta). Covered here:
  - openai_style.chat(on_delta): parses SSE `data:` deltas, calls on_delta per content
    chunk, returns the SAME 6-tuple (usage/served/finish from the final events);
  - a cached request that 400s at stream-open retries plain (streaming, no delta lost);
  - anthropic_style.chat(on_delta): message_start/content_block_delta/message_delta parse;
  - the mock streaming double (per-word deltas) via call_model; final tuple == non-stream;
  - run_mode/converse thread on_delta ONLY on the converse single-seat branch — panel/judge
    and yes-and never see it;
  - abort mid-stream (on_delta raises) appends NO ai turn (human turn already committed).

Run:  python tests/engine_phase36.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_TMP = tempfile.mkdtemp(prefix="rr-phase36-")
_CFG = Path(_TMP) / "config.toml"
shutil.copy(REPO / "tests" / "config.toml", _CFG)
os.environ["RESEARCH_ROOM_VAULT"] = str(Path(_TMP) / "vault")
os.environ["RESEARCH_ROOM_CONFIG"] = str(_CFG)
os.environ["RESEARCH_ROOM_HOME"] = str(Path(_TMP) / "config")
os.environ["RESEARCH_ROOM_SECRETS"] = str(Path(_TMP) / "secrets.json")
sys.path.insert(0, str(REPO))

import httpx as _httpx                                       # noqa: E402
from engine import modes, providers, rooms, transcript      # noqa: E402
from engine.adapters import openai_style, anthropic_style    # noqa: E402

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
_fails = 0


def check(label, cond):
    global _fails
    print(f"  [{PASS if cond else FAIL}] {label}")
    if not cond:
        _fails += 1


class _StreamResp:
    """A fake streamed httpx response: yields the given SSE lines from iter_lines()."""
    def __init__(self, lines, status=200):
        self._lines = lines
        self.status_code = status
        self.request = _httpx.Request("POST", "http://x")
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def iter_lines(self):
        for ln in self._lines:
            yield ln
    def read(self): return b""
    @property
    def text(self): return "error body"
    def raise_for_status(self):
        if self.status_code >= 400:
            raise _httpx.HTTPStatusError("err", request=self.request, response=self)


class _FakeHttpx:
    """Stands in for the module-level httpx: .stream() returns queued responses in order."""
    HTTPStatusError = _httpx.HTTPStatusError
    HTTPError = _httpx.HTTPError

    def __init__(self, *resps):
        self._resps = list(resps)
        self.sent = []            # each call's json body
    def stream(self, method, url, headers=None, json=None, timeout=None):
        self.sent.append(json)
        return self._resps.pop(0)


P = providers.Provider


def main() -> int:  # noqa: C901
    # ---- 1. openai_style streaming parse -------------------------------------
    print("1. openai_style.chat(on_delta) — SSE deltas → text + final tuple")
    direct = P("ds", "api", "openai", "deepseek-x", True, "#fff", base_url="https://api.deepseek.com")
    lines = [
        'data: {"model":"served-x","choices":[{"delta":{"content":"Hello"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{"content":" world"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5,"cost":0.002}}',
        'data: [DONE]',
    ]
    fake = _FakeHttpx(_StreamResp(lines)); openai_style.httpx = fake
    got = []
    payload = {"system": "s", "messages": [{"role": "user", "content": "hi"}]}
    text, rc, usage, served, search, finish = openai_style.chat(direct, "k", payload, on_delta=got.append)
    openai_style.httpx = _httpx
    check("on_delta fired per content chunk (incremental)", got == ["Hello", " world"])
    check("chunks concatenate to the final text", "".join(got).strip() == text == "Hello world")
    check("served_model from the stream", served == "served-x")
    check("finish_reason captured", finish == "stop")
    check("usage input/output/cost from the final event", usage == {"input": 10, "output": 5, "cost": 0.002})
    check("no search on a converse stream", search is None)
    check("request asked to stream", fake.sent[0].get("stream") is True)

    # ---- 2. cached 400 at stream-open → plain re-stream (no delta lost) -------
    print("2. openai_style — a cached 400 retries plain (streaming); no delta before the retry")
    orp = P("or", "api", "openai", "anthropic/claude-opus-4.8", True, "#fff",
            base_url="https://openrouter.ai/api/v1")
    ok_lines = ['data: {"choices":[{"delta":{"content":"A"},"finish_reason":"stop"}]}', 'data: [DONE]']
    fake = _FakeHttpx(_StreamResp([], status=400), _StreamResp(ok_lines)); openai_style.httpx = fake
    convo = "[human]: hi\n\nRespond as [claude]."
    got2 = []
    text2, *_ = openai_style.chat(orp, "k", {"system": "s", "messages": [{"role": "user", "content": convo}]},
                                  cache=True, on_delta=got2.append)
    openai_style.httpx = _httpx
    check("two stream attempts (cached 400 → plain)", len(fake.sent) == 2)
    check("attempt 1 sent cache_control (list content)", isinstance(fake.sent[0]["messages"][-1]["content"], list))
    check("attempt 2 sent plain string content", isinstance(fake.sent[1]["messages"][-1]["content"], str))
    check("only the successful attempt's delta surfaced", got2 == ["A"] and text2 == "A")

    # ---- 3. openai_style non-stream error maps to RuntimeError ---------------
    print("3. openai_style — a 500 at stream-open → RuntimeError (turn fails cleanly)")
    fake = _FakeHttpx(_StreamResp([], status=500)); openai_style.httpx = fake
    try:
        openai_style.chat(direct, "k", payload, on_delta=lambda c: None)
        raised = False
    except RuntimeError:
        raised = True
    openai_style.httpx = _httpx
    check("stream open 500 → RuntimeError", raised)

    # ---- 3b. mid-stream error event (200 then error) → RuntimeError, not a fake success ----
    print("3b. openai_style — a mid-stream {\"error\"} event raises (no truncated 'success')")
    err_lines = ['data: {"choices":[{"delta":{"content":"partial"}}]}',
                 'data: {"error":{"message":"provider overloaded","code":529}}']
    fake = _FakeHttpx(_StreamResp(err_lines)); openai_style.httpx = fake
    egot = []
    try:
        openai_style.chat(direct, "k", payload, on_delta=egot.append)
        raised2 = False
    except RuntimeError:
        raised2 = True
    openai_style.httpx = _httpx
    check("mid-stream error → RuntimeError (not returned as a truncated answer)", raised2)
    check("only the pre-error delta surfaced", egot == ["partial"])

    # ---- 4. anthropic_style streaming parse (the divergent adapter) ----------
    print("4. anthropic_style.chat(on_delta) — message_start/content_block_delta/message_delta")
    cl = P("claude", "api", "anthropic", "claude-x", True, "#fff", base_url="https://api.anthropic.com")
    a_lines = [
        'event: message_start',
        'data: {"type":"message_start","message":{"model":"claude-served","usage":{"input_tokens":12,"output_tokens":1}}}',
        'event: content_block_delta',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":" there"}}',
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":7}}',
        'event: message_stop',
        'data: {"type":"message_stop"}',
    ]
    fake = _FakeHttpx(_StreamResp(a_lines)); anthropic_style.httpx = fake
    got4 = []
    at, arc, ausage, aserved, asearch, afinish = anthropic_style.chat(cl, "k", payload, on_delta=got4.append)
    anthropic_style.httpx = _httpx
    check("text deltas fired (skips event: lines)", got4 == ["Hi", " there"])
    check("assembled text", at == "Hi there")
    check("served_model from message_start", aserved == "claude-served")
    check("input from message_start, output from message_delta", ausage == {"input": 12, "output": 7})
    check("stop_reason normalized end_turn→stop", afinish == "stop")

    # ---- 4b. anthropic mid-stream error event → RuntimeError ----------------
    print("4b. anthropic_style — a mid-stream `error` event raises (no truncated 'success')")
    ae_lines = [
        'data: {"type":"message_start","message":{"model":"c","usage":{"input_tokens":1}}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}',
        'event: error',
        'data: {"type":"error","error":{"type":"overloaded_error","message":"overloaded"}}',
    ]
    fake = _FakeHttpx(_StreamResp(ae_lines)); anthropic_style.httpx = fake
    aeg = []
    try:
        anthropic_style.chat(cl, "k", payload, on_delta=aeg.append)
        raised_a = False
    except RuntimeError:
        raised_a = True
    anthropic_style.httpx = _httpx
    check("anthropic mid-stream error → RuntimeError", raised_a)
    check("only the pre-error delta surfaced", aeg == ["Hi"])

    # ---- 5. mock streaming double via call_model; tuple == non-stream --------
    print("5. call_model(mock, on_delta) — per-word deltas, ModelReply identical to non-stream")
    rooms.settings.VAULT_DIR.mkdir(parents=True, exist_ok=True)
    plain = providers.call_model("mock", payload)
    dgot = []
    streamed = providers.call_model("mock", payload, on_delta=dgot.append)
    check("mock emitted >1 delta", len(dgot) > 1)
    check("deltas concatenate to the reply text", "".join(dgot) == streamed.text)
    check("streamed text == non-streamed text (display channel only)", streamed.text == plain.text)

    # ---- 6. run_mode/converse thread on_delta ONLY on converse single-seat ---
    print("6. converse streams; panel/judge + yes-and never see on_delta")
    rid = rooms.create_room("cv", participants=["mock"], judge="mock")
    cgot = []
    reply = modes.converse(rid, "hello there friend", addressed_to="mock", on_delta=cgot.append)
    check("converse emitted deltas", len(cgot) > 1 and "".join(cgot) == reply)
    turns = transcript.load(rooms.main_path(rid))
    check("exactly two turns appended (human + ai)", len(turns) == 2)
    check("last turn is the ai reply, full text", turns[-1]["role"] == "ai" and turns[-1]["text"] == reply)

    fus = rooms.create_room("fus", participants=["mock", "mockthink"], judge="mock")
    fgot = []
    modes.run_mode(fus, modes.FUSION_MODE, "task?", {"panel": ["mock", "mockthink"], "judge": "mock"},
                   on_delta=fgot.append)
    check("fusion panel+judge NEVER called on_delta", fgot == [])

    ya = rooms.create_room("ya", participants=["mock", "mockthink"], judge="mock")
    ygot = []
    modes.run_mode(ya, modes.YES_AND_MODE, "go", {"seats": ["mock", "mockthink"]}, on_delta=ygot.append)
    check("yes-and (turn_mode=converse but name!=converse) does NOT stream", ygot == [])

    # ---- 7. abort mid-stream appends no ai turn (human turn already committed)
    print("7. abort mid-stream → RuntimeError, no ai turn, human turn stands (today's failure shape)")
    ab = rooms.create_room("ab", participants=["mock"], judge="mock")

    def boom(_chunk):
        raise RuntimeError("client aborted")

    try:
        modes.converse(ab, "please answer", addressed_to="mock", on_delta=boom)
        aborted = False
    except RuntimeError:
        aborted = True
    ab_turns = transcript.load(rooms.main_path(ab))
    check("abort propagated as RuntimeError", aborted)
    check("only the human turn was appended (no ai turn)",
          len(ab_turns) == 1 and ab_turns[0]["role"] == "human")

    print()
    if _fails:
        print(f"\033[31m{_fails} check(s) failed\033[0m"); return 1
    print("\033[32mall Phase 36.1/36.2 (converse streaming: adapters + engine threading) checks passed\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
