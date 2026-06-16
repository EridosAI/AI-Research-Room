# Research room — Claude Code build plan

A phased, executable plan for the multi-model research room. Self-contained: it folds in the
v0 spec and every amendment since. Build one phase at a time and run its **Done when** check
before moving on.

## How to use this with Claude Code
1. Drop this file in the repo root as `BUILD.md`. Point CC at it: *"Implement BUILD.md phase by phase. After each phase, run the Done-when check and stop for me to confirm."*
2. CC may already have scaffolding from the earlier v0 spec — have it **reconcile** against this plan rather than starting over (this is the authoritative version).
3. Reuse the existing fusion runner package (`run_grok.sh`, `run_mock.sh`, `run_mockfail.sh`, the OpenAI/Anthropic adapter shapes) — they already satisfy the runner/adapter contracts below.
4. Test orchestration with the **mock** providers first (no tokens). Use DeepSeek for the first *real* call (cheapest). Verify Grok's subscription separately (see Testing).

---

## Provider lineup (bake this into config at Phase 0)

| key | auth_mode | backend | base_url / runner | default model | notes |
|-----|-----------|---------|-------------------|---------------|-------|
| `claude` | `api` | anthropic HTTP | `https://api.anthropic.com` | `claude-opus-4-8` | used sparingly; metered key |
| `grok` | `cli` | Grok Build CLI | `run_grok*.sh` | `grok-build-0.1` | SuperGrok Heavy subscription; **no key** |
| `kimi` | `api` | openai HTTP | `https://api.moonshot.ai/v1` | `kimi-k2.6` | cheap key; note `/v1` in base |
| `deepseek` | `api` | openai HTTP | `https://api.deepseek.com` | `deepseek-v4-pro` | cheap key; base has no `/v1` |

Provider registry must be **user-extensible** (add any OpenAI-compatible endpoint via the UI),
so the four above are presets, not a hardcoded enum. `research_judge` is a global setting
(default `claude` / `claude-opus-4-8`, since Claude is used sparingly but is the judge).

---

## Hard requirements (non-negotiable, apply across all phases)

- **Secrets live OUTSIDE the vault and OUTSIDE the repo.** Store API keys at
  `~/.config/research-room/secrets.json`, `chmod 600`. The transcript lives in the
  git-tracked Obsidian vault; **keys never do** (hourly auto-commit would push them to GitHub).
- **Keys are write-only over the API.** `GET /providers` returns last-4 + status, never the key. No endpoint ever returns a full key. Redact keys from logs and error bodies.
- **Bind the server to `127.0.0.1` only.** Single-user localhost tool; nothing on the LAN.
- **Sanitize rendered markdown** (model output → DOM) with DOMPurify. No `localStorage`/`sessionStorage`.
- **Grok subscription:** keep `XAI_API_KEY` UNSET in the server environment so `grok` uses the
  `~/.grok/auth.json` subscription token, not a metered key.

---

## Project layout

```
research-room/
  engine/
    transcript.py        # append-only JSONL store + schema
    context.py           # build_context (synthesis-only filter) + build_cli_prompt
    providers.py         # registry, config, call_model dispatch (api vs cli)
    adapters/
      openai_style.py    # OpenAI/xAI/DeepSeek/Kimi: Bearer, POST {base}/chat/completions
      anthropic_style.py # Claude: x-api-key + anthropic-version, POST /v1/messages
    runners/
      run_grok.sh            # research panelist (agentic web+shell) — from fusion pkg
      run_grok_converse.sh   # converse turn (subscription, single answer) — below
      run_mock.sh, run_mockfail.sh   # testing — from fusion pkg
    modes.py             # research() and converse()
    secrets.py           # load/store keys outside vault, chmod 600
    settings.py          # transcript dir (= vault path), config paths
  cli/room.py            # CLI smoke test
  web/
    server.py            # FastAPI: research/converse/transcript/providers
    static/{index.html, app.js, styles.css}
  config.toml            # provider registry (NOT secrets): base_urls, models, auth_mode, enabled
  pyproject.toml
```

---

## Phase 0 — scaffold + config
**Goal:** project skeleton, config registry, secrets module, settings.
**Create:** layout above (empty modules), `pyproject.toml` (deps: `fastapi`, `uvicorn`, `httpx`, `pydantic`), `config.toml` with the four providers from the lineup table, `secrets.py` (read/write `~/.config/research-room/secrets.json`, create with mode 600, never under vault/repo), `settings.py` (transcript dir defaults to the vault path, overridable by env).
**Done when:** `python -c "import engine.providers"` loads the registry; `secrets.py` writes/reads a dummy key at the config path with 600 perms; the secrets path is confirmed outside the vault tree.

## Phase 1 — engine core: transcript + context
**Goal:** the shared substrate.
**Create:**
- `transcript.py` — append-only JSONL, one object per turn:
  ```json
  {"id":"uuid4","ts":"ISO8601","mode":"converse|research","role":"human|ai|judge",
   "speaker":"human|claude|grok|kimi|deepseek","text":"...",
   "meta":{"model":"...","addressed_to":"grok","round_id":"uuid4","is_panelist_raw":true}}
  ```
  Functions: `append(turn)`, `load(path)`. Never rewrite, only append.
- `context.py`:
  - `build_context(transcript, for_speaker, mode) -> {system, messages}`. Flatten the whole transcript into ONE labeled block as a single `user` message; system prompt = ROOM_SYSTEM (you are `[for_speaker]`, other AI speakers are peers, respond as yourself). Do NOT map other models' turns to the `assistant` role. **Synthesis-only filter:** exclude every turn where `meta.is_panelist_raw` is true — only the judge synthesis (`role=judge`) of a research round flows forward. Raw panel answers stay in the transcript (for the UI's "view full" and the record) but never enter context.
  - `build_cli_prompt(ctx) -> str`: `f"{ctx['system']}\n\n{ctx['messages'][0]['content']}"` (the CLI takes a prompt string, not a messages array).
**Done when:** unit test — a transcript with 3 `is_panelist_raw` turns + 1 `judge` turn yields a `build_context` body containing the judge text and none of the raw panel text; round-trips through `append`/`load`.

## Phase 2 — provider layer: adapters + call_model
**Goal:** one interface over every backend, both auth modes.
**Create:**
- `adapters/openai_style.py` — `POST {base_url}/chat/completions`, `Authorization: Bearer <key>`; covers openai/xai/deepseek/kimi. Store `base_url` verbatim; append `/chat/completions`; never double `/v1`. `list_models()` → `GET {base_url}/v1/models` (or `{base}/models` for deepseek).
- `adapters/anthropic_style.py` — `POST /v1/messages`, headers `x-api-key` + `anthropic-version: 2023-06-01`. `list_models()` → `GET /v1/models`.
- `providers.py` — `call_model(provider, payload, tools=False) -> text` dispatching on `auth_mode`:
  - `api` → the matching HTTP adapter with the key from `secrets.py`.
  - `cli` → write `build_cli_prompt(payload)` to a temp file, shell out to the provider's runner (`run_grok_converse.sh` for converse, `run_grok.sh` for research), read the answer back. No key.
**Done when:** `call_model('mock', …)` returns deterministic text; a real `call_model('deepseek', …)` returns a completion with a test key; the `cli` path invokes the runner and captures output.

## Phase 3 — modes: research + converse
**Goal:** the two call patterns over the substrate.
**Create:** `modes.py`:
- `research(prompt)`: append human turn (research) → fan out to all enabled participants in **parallel, blind**, `tools=True` (agentic runners / api) → append each raw answer (`is_panelist_raw`, shared `round_id`) → build judge payload (prompt + all answers + rubric) → call `research_judge` → append synthesis (`role=judge`, same `round_id`) → return synthesis. Degrade gracefully: a failed panelist is dropped and marked absent, never treated as agreement; abort only if zero panelists return.
- `converse(prompt, addressed_to)`: append human turn (converse, `addressed_to`) → `build_context(…, addressed_to, "converse")` → `call_model(addressed_to, payload, tools=False)` per its auth_mode → append reply → return. `addressed_to` explicit; fallback = last AI speaker.
**Done when:** with mock providers, a research round's judge sees N panel answers and a panelist failure is marked absent; a converse turn round-trips; raw answers are stored but absent from the next turn's context.

## Phase 4 — CLI smoke test
**Goal:** validate the engine headlessly before any UI.
**Create:** `cli/room.py`: `room new "<title>"`, `room ask "<q>"` (research), `room say @grok "<msg>"` / `room say "<msg>"` (converse), `room show`, `room who`.
**Done when:** full mock run end to end; then one real cheap round (`room say @deepseek "…"`).

## Phase 5 — web server (FastAPI)
**Goal:** thin API + static host. Engine ships with the UI (in-process calls).
**Create:** `web/server.py`, bound to `127.0.0.1`:
- `POST /research {prompt}`, `POST /converse {prompt, addressed_to}`, `GET /transcript`.
- `GET /providers` (config, keys redacted to last-4 + status), `PUT /providers/{name}` (base_url/model/enabled/auth_mode; accepts key **write-only**), `POST /providers/{name}/test` (1-token completion → ok/error), `GET /providers/{name}/models` (proxy provider model list).
- Serve `static/`. `/research` and `/converse` degrade gracefully (one model down ≠ crash).
**Done when:** curl each endpoint; a key set via `PUT` never appears in any `GET`; `test` validates a real key.

## Phase 6 — web UI (static SPA)
**Goal:** the reading-and-steering surface. Plain HTML/JS, markdown lib + DOMPurify via CDN, no build step.
**Create:** `static/index.html`+`app.js`+`styles.css`:
- One vertical **transcript stream**; one colour per speaker (dot used consistently). Converse turns as chat blocks. A research round renders as ONE embedded composite block: collapsed panel cards (one per panelist, with "view full" expanding the stored raw answer) above a foregrounded synthesis tagged with judge + agreement.
- **Composer:** explicit mode toggle (converse | research) + addressee selector for converse (default last speaker). Markdown/code rendering, sanitized.
- Reads/writes the **same transcript** the engine owns (UI is not a separate store).
**Done when:** behaviour matches the agreed mockup; a research round shows parallel cards + synthesis + working "view full"; sanitized output.

## Phase 7 — model management UI
**Goal:** key entry, live model selection, connection testing, auth-mode per provider.
**Create:** a settings panel over the `/providers` endpoints. Per provider row: colour dot + name; status pill (connected / not tested / not configured); **masked, write-only key field** + save; **test** button (calls `/test`); **model dropdown** populated from `/models` with a refresh; enable toggle. For **Grok**, show an `auth_mode` toggle — "use SuperGrok via Grok Build" — which *replaces the key field* (no key; relies on `grok login`). Footer: `research_judge` selector. Footnote: "keys stored locally, never in the vault."
**Done when:** all four providers configurable via UI; keys stay server-side; the Grok row shows the subscription toggle instead of a key field; model dropdowns populate live.

---

## run_grok_converse.sh (Phase 2)

```bash
#!/usr/bin/env bash
# One Grok converse turn via Grok Build, on the SuperGrok Heavy plan. Single reply, not an agent loop.
# Auth: uses ~/.grok/auth.json from `grok login` (subscription), NOT an API key. Keep XAI_API_KEY UNSET.
set -uo pipefail
prompt_file="${1:?usage: run_grok_converse.sh <prompt_file> <output_file>}"
output_file="${2:?}"
model="${FUSION_GROK_MODEL:-}"   # empty = grok-build-0.1 (subscription-safe)
command -v grok >/dev/null 2>&1 || { echo "[grok-converse] grok CLI missing — skip." >&2; exit 127; }
[ -n "${XAI_API_KEY:-}" ] && echo "[grok-converse] WARNING: XAI_API_KEY set — grok may bill API, not your sub. Unset it." >&2
scratch="$(mktemp -d "${TMPDIR:-/tmp}/room-grok.XXXXXX")"; trap 'rm -rf "$scratch"' EXIT
model_args=(); [ -n "$model" ] && model_args=(--model "$model")
# --cwd scratch = throwaway blast radius; --no-auto-update = no mid-run phone-home; --always-approve = no stall.
# Verify flags against your installed Grok Build (early beta).
grok -p "$(cat "$prompt_file")" --cwd "$scratch" --no-auto-update --always-approve "${model_args[@]}" \
  > "$output_file" 2> "$scratch/err.log"
[ $? -eq 0 ] && [ -s "$output_file" ] || { echo "[grok-converse] failed:" >&2; tail -20 "$scratch/err.log" >&2; exit 1; }
echo "[grok-converse] ok -> $output_file"
```

Runner contract (all runners): `run_X.sh <prompt_file> <output_file> [effort]` → clean final
answer to `<output_file>`; exit 127 if the CLI is missing; exit 1 on other failure.

---

## Testing strategy
- **Orchestration:** mock providers (`run_mock.sh`, `run_mockfail.sh`) — validate fan-out, judge-sees-N, degradation, the synthesis-only filter, parallel vs single, with zero token cost.
- **First real call:** DeepSeek (cheapest) via `room say @deepseek "…"`.
- **Grok subscription check (do once, before trusting it):** run `grok` interactively and sign in (browser); confirm `~/.grok/auth.json` exists; ensure `XAI_API_KEY` is unset in the server env; smoke-test `grok -p "say ok"` and confirm it answers without prompting for a key. If it falls back to a key, the subscription path isn't active.
- **Security check:** after setting a key in the UI, grep the repo + vault for the key string (must be absent), and confirm `GET /providers` shows only last-4.

## Deferred (do NOT build yet)
Mode 3 (hand-up/interject), context compression/summarization (full transcript for now — revisit when sessions get long), auth/multi-user, cost dashboards.
```
