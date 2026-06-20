# BUILD amendment — Grok via Hermes proxy (+ xAI-native-search probe) (phase 19)

> **Status: BUILT (19.1) · PROBED & DECIDED — NOT WIRED (19.2).** Companion to [BUILD.md](BUILD.md)
> and the phase 11–18 amendments. Preceded by a recon pass (CC, against locally installed Hermes
> v0.14.0). Spec preserved; as-built notes + probe results at the foot.

---

Recon established: `hermes proxy start --provider xai` runs a **local OpenAI-compatible server** that
forwards to xAI with SuperGrok **OAuth attached**, as **pure inference** (no agent/tools/skills/x_search),
returning a standard `chat.completion` carrying `model`, `reasoning_content`, `usage.reasoning_tokens`,
`finish_reason`. So Grok-via-Hermes is **a config row, not a runner**, and it upgrades the seat from a
coding-tuned CLI default to a genuine **grok-4.3** reasoner, free at the margin.

## 19.1 — Grok-via-proxy provider (the config row) — BUILT
- **Sidecar (not Fusion-supervised):** `hermes proxy start --provider xai --host 127.0.0.1 --port 8645`
  run manually/at login. If down → existing graceful degradation (absent panelist). Documented in README.
- **Provider row:** `backend = openai`, `base_url = http://127.0.0.1:8645/v1`, dummy key (proxy does
  OAuth), `model = grok-4.3`. Supersedes the CLI Grok seat; `run_grok.sh` left unused, not deleted.
- **Zero adapter work:** `openai_style` already reads content / `reasoning_content` (P11) /
  `usage.reasoning_tokens` (P14) / `finish_reason` (P18) / `response.model`→`served_model` (P16). The
  show-reasoning toggle surfaces Grok's reasoning. Header + served_model pill now honestly read `grok-4.3`.
- **Secrets/packaging:** no new Fusion secret (token lives in `~/.hermes/auth.json`). Personal
  convenience, never shipped; a friend substitutes a key-based Grok row (xAI key / OpenRouter) — same
  `openai` backend, zero code difference.

## 19.2 — xAI-native search through the proxy — PROBED, FAILED, FALLBACK CHOSEN (no code)
Probed live against the running proxy:
- `tools:[{type:"web_search"}]` / `{type:"x_search"}` (Agent Tools API) → **400 unknown variant**,
  `expected 'function' or 'live_search'` — the Agent Tools API is Responses-API-only.
- `tools:[{type:"live_search", sources:[…]}]` → schema-recognized but **runtime-deprecated**:
  *"Live search is deprecated. Please switch to the Agent Tools API."*
- legacy top-level `search_parameters` → same deprecation error.

So xAI-native search does **not** traverse the proxy (chat-completions). **Fallback (recorded in
DEFERRED.md):** proxy-Grok is the search-less converse/default seat; for Grok-with-search in research,
use a second OpenRouter-routed Grok seat (Phase 17 already covers it). No `search_dialect` branch built.

## Gate
- **19.1:** `engine_phase19.py` (mock + stubbed-httpx) replays the **real captured** proxy `grok-4.3`
  response and asserts the existing adapter + `call_model` parse content / `reasoning_content` /
  usage / `finish_reason` / `served_model == grok-4.3`, that the localhost base is not mistaken for
  OpenRouter (no search tool attached), and that the request hits `…:8645/v1/chat/completions`.
- **19.2:** none — the probe failed, the decision is recorded.

## Housekeeping
README (proxy sidecar command, grok-4.3 seat, auth-is-Hermes', packaging substitution, run_grok
superseded); DEFERRED.md decision record; test list.

---

## As-built notes

- **19.1 needed no production code** — it is genuinely a provider row plus a regression test proving
  the claim. I did **not** add the row to the user's personal (skip-worktree'd) `config.toml`; the
  exact values are in the README for them to add via the UI, with the proxy running + a server
  restart. A `grok_proxy` fixture (disabled, openai backend, localhost:8645, `reasoning=true`) was
  added to `tests/config.toml` for the gate only.
- **The live probe earned its keep twice.** First it confirmed the response shape (served `grok-4.3`,
  `reasoning_content`, `usage.reasoning_tokens`) — and caught the model's prose claiming it was
  "grok-1" while `response.model` said `grok-4.3`, a perfect served_model-pill demonstration baked
  into the test. Second, the 19.2 search probe overturned the spec's own plan twice: `web_search`/
  `x_search` aren't on chat-completions at all, and the `live_search`/`search_parameters` paths the
  error messages hinted at are runtime-deprecated. Verifying beat trusting.
- **Auth persistence confirmed on WSL:** the proxy reused the stored `xai-oauth` credential pool with
  zero re-prompt across repeated calls and auto-refreshes on 401 (`xai.py get_retry_credential`). The
  loopback browser login is a one-time hurdle (already completed); per-call needs nothing.
- **Bundled small fix (the test-ping floor).** Same session: the provider **test** button sent
  `max_tokens=1`, which 400s on reasoning models (GPT-5.x via OpenRouter/Azure floor
  `max_output_tokens` at 16). Fixed `providers.TEST_MAX_TOKENS = 32`; real calls were never affected
  (converse 8192 / research 32768). Gated in `engine_phase18.py` §5.
- **Gate:** `engine_phase19.py`. Full suite **24/24** (8 engine + 16 browser), DOM unchanged
  (provider row + relabel only — no UI structural change).
