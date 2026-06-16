# Research Room

A multi-model research room: a headless **engine** plus thin **clients** (a CLI and a
local web UI) that let several LLMs — Claude, Grok, Kimi, DeepSeek, or any
OpenAI-compatible endpoint you add — work the same shared transcript. Two modes:

- **converse** — address one model; it answers seeing the conversation so far.
- **research** — a panel of models answers the prompt **blind and in parallel**, then a
  **judge** model synthesizes their answers into one (the "fusion" pattern). You pick which
  models join each round.

The engine owns the transcript and all orchestration; clients are pure views over it. The
transcript is append-only JSONL in a git-tracked (Obsidian-friendly) vault — **API keys
never go there**.

---

## Why it's built this way

- **One transcript, two call patterns.** Every mode is just a pattern over a shared
  transcript and a single `call_model` interface — no per-mode state machine.
- **Blind panel + judge.** In research mode panelists never see each other's work; only the
  judge's synthesis flows forward into later turns (raw panel answers are kept for the record
  and the UI's "view full", but are filtered out of model context — the *synthesis-only
  filter*). This keeps the panel honestly independent and the context lean.
- **Two adapter shapes cover everything.** `openai` (Bearer, `POST {base}/chat/completions`)
  and `anthropic` (`x-api-key`, `POST {base}/v1/messages`). Any OpenAI-compatible service
  (OpenRouter, a local vLLM/Ollama server, …) drops in with no code change.
- **Subscription or API per provider.** `auth_mode` is `api` (HTTP + key) or `cli` (shell out
  to an agentic CLI runner, e.g. Grok on a SuperGrok subscription — **no key**).
- **Graceful degradation.** A failed panelist is dropped and marked *absent* (never treated
  as agreement); a round aborts only if everyone fails. If the **judge** itself is
  unavailable (no key / down), it falls back to a panelist that answered, so a bad judge
  can't sink an otherwise-good round.

## Security model (the part that matters)

- **Keys live outside the repo and the vault** — `~/.config/research-room/secrets.json`,
  `chmod 600`. The git-tracked vault holds transcripts only; an hourly auto-commit can never
  push a key.
- **Keys are write-only over the API.** `GET /providers` returns last-4 + status, never the
  key. No endpoint returns a full key; keys are redacted from logs and error bodies.
- **Localhost only.** The server binds `127.0.0.1`; provider/config endpoints additionally
  refuse non-loopback callers.
- **Model output is sanitized** (markdown → DOMPurify → DOM) on every bubble and panel card,
  and **fails closed** to plain text if the sanitizer can't load. No browser storage — the UI
  is a pure view of the transcript.

---

## Install

Requires Python 3.11+.

```bash
pip install -e .          # fastapi, uvicorn, httpx, pydantic
```

Research mode's `cli` providers also need their CLI installed and authed (e.g. `grok login`).

## Configure providers

The registry is `config.toml` (base URLs, models, `auth_mode`, `enabled`, colour) — **not
secrets**. It's machine-managed by the web UI but human-readable. The seeded lineup:

| key | auth | adapter | base_url | default model |
|-----|------|---------|----------|---------------|
| `claude` | api | anthropic | `https://api.anthropic.com` | `claude-opus-4-8` |
| `grok` | cli | — (`run_grok*.sh`) | SuperGrok subscription | `grok-build-0.1` |
| `kimi` | api | openai | `https://api.moonshot.ai/v1` | `kimi-k2.6` |
| `deepseek` | api | openai | `https://api.deepseek.com` | `deepseek-v4-pro` |

`base_url` is stored verbatim; the adapter appends `/chat/completions` (openai) or
`/v1/messages` (anthropic) — it never injects `/v1`, so bases that already end in `/v1`
aren't doubled. `research_judge` (default `claude`) names the synthesizing model.

**Set keys through the web UI** (write-only masked field) or drop them into
`~/.config/research-room/secrets.json`. Env vars are honored as a fallback:
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`, `MOONSHOT_API_KEY`, `DEEPSEEK_API_KEY`.
For Grok-on-subscription, keep `XAI_API_KEY` **unset** so it uses `~/.grok/auth.json`.

---

## Use

### Web UI (recommended)

```bash
python -m web.server        # → http://127.0.0.1:8765
```

A single static page (vanilla HTML/JS, `marked` + `DOMPurify` from CDN, no build step): a
colour-coded transcript stream, research rounds rendered as one composite block (collapsed
panel cards with "view full" above a foregrounded synthesis), a composer with a mode toggle,
an addressee selector (converse) and a per-round model picker (research), and a **⚙ providers**
panel to enter keys, test connections, pick
models, toggle a provider to subscription/CLI, choose the judge, and add new providers.

### CLI

```bash
./room new "embedding models"                 # create a transcript in the vault
./room ask "best open embedding model?"        # research: all enabled models + judge
./room say @deepseek "build on that"           # converse, addressed
./room say "and the tradeoffs?"                # converse, default = last AI speaker
./room show                                     # print the transcript
./room who                                      # providers + models + key status
```

(`python -m cli.room <cmd>` works too.)

### One-click launch (Windows + WSL)

`python -m web.server --open` starts the server and opens the UI in your default
browser once it's accepting connections (opt-in, so headless/test runs stay
browser-free). For a double-clickable / pinnable launcher:

```bash
# from the repo root, create a Desktop shortcut (portable — derives its own paths)
powershell.exe -ExecutionPolicy Bypass -File "$(wslpath -w tools/create_shortcut.ps1)"
# then right-click "Research Room" on the Desktop → Pin to taskbar
```

`Room.bat` is the launcher it points at (the console window it opens *is* the
server — close it to stop). Drop a `room.ico` in the repo root for a custom
taskbar icon; without one, Windows uses a default.

---

## Layout

```
engine/
  transcript.py        append-only JSONL store
  context.py           build_context (synthesis-only filter) + build_cli_prompt
  providers.py         registry (config.toml) + call_model dispatch (api | cli | mock)
  adapters/
    openai_style.py    Bearer, POST {base}/chat/completions
    anthropic_style.py x-api-key + version, POST {base}/v1/messages
  runners/             cli runners (run_grok*.sh) + mock runners for tests
  modes.py             research() and converse()
  secrets.py           keys outside the vault, chmod 600
  settings.py          paths (vault, config, secrets)
cli/room.py            CLI smoke client
web/
  server.py            FastAPI (127.0.0.1): research/converse/transcript/providers
  static/              the single-page UI
config.toml            provider registry (NOT secrets)
references/            judge rubric
vault/                 transcripts (JSONL) — point RESEARCH_ROOM_VAULT at your Obsidian vault
tests/                 mock-provider tests + headless-browser UI tests (Playwright)
BUILD.md               the phased build plan this was built from
```

## Testing

Orchestration is validated with **mock providers** (`run_mock.sh` / `run_mockfail.sh` + a
`tests/config.toml` fixture) — fan-out, judge-sees-N, degradation, the synthesis-only filter,
all at zero token cost. The web UI's security-critical behavior (DOMPurify sanitization,
fail-closed rendering, the write-only key round-trip, the localhost guard) is verified in a
real headless Chromium:

```bash
pip install playwright && playwright install chromium     # dev only
python tests/browser_phase6.py        # composite render, view-full, sanitization, fail-closed
python tests/browser_phase7.py        # key round-trip, cli toggle, test/models, secrets loop
```

## Environment

`RESEARCH_ROOM_VAULT` (transcript dir), `RESEARCH_ROOM_HOME` / `RESEARCH_ROOM_SECRETS`
(secrets location), `RESEARCH_ROOM_CONFIG` (registry path), `RESEARCH_ROOM_HOST` /
`RESEARCH_ROOM_PORT`, `RESEARCH_ROOM_MAX_TOKENS`.

## License

MIT © Jason Dury — see [LICENSE](LICENSE).
