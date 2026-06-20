# BUILD amendment — per-panelist web search (phase 17)

> **Status: BUILT.** Build record (companion to [BUILD.md](BUILD.md) and the phase 11 / 13 / 14 /
> 15 / 16 amendments). Spec preserved verbatim; as-built notes appended at the foot. Current
> architecture is in [README.md](README.md).

---

Fixes the research-mode bug: panelists are told to "research with web search" (`modes.py:26`) and
called with `tools=True` (`modes.py:43`), but `tools=True` is a **documented no-op on the API
adapters** (`providers.py:290`) — only the Grok CLI runner actually searches. So API panelists
answered from training knowledge and hedged their citations. This attaches real web search to the
API adapters.

## The model (read first)

**Independent search per panelist — by design.** Each search-enabled API panelist runs its **own**
provider-side search loop when answering the shared round prompt: separate result pools, common
scope. This is deliberate — divergent exploration across models is the point of Fusion, and the
synthesis step is more valuable when panelists drew on genuinely different sources. **No
shared-retrieval layer.** The common scope is already enforced by the shared panel prompt;
independent search supplies the separate pools — so once search is attached, the existing structure
delivers "separate pools, common scope" with no extra work.

**Scope: research panelists only.** Search fires on the `tools=True` calls (research panel
fan-out). Converse stays no-search unless you later pass `tools=True` there too. Matches the bug.

**Single call, server-side.** Both mechanisms below run the search→answer loop **server-side** and
return in one response. Do **not** build a client-side tool loop, and do **not** implement
Anthropic's `encrypted_content` multi-turn passback — each panel answer is one request, and forward
context is synthesis-only (`turn.text`), so prior raw results are never re-fed; if a later round
needs fresh info, the panelist just searches again. `meta.search` is provenance/display only.

**Two mechanisms cover everyone** (given DeepSeek routes through OpenRouter):
- `anthropic` backend → Claude's native web_search tool.
- `openai` backend on the **OpenRouter** base_url → OpenRouter's web_search server tool.
- `cli` (Grok) → already searches via its agentic runner; **unchanged** (toggle N/A).
- **Kimi-direct (Moonshot):** route through OpenRouter like DeepSeek, or add Moonshot's native
  search later. **Defaulting to OR-routed.**

**Invariant holds.** `meta.search` lives in meta; `build_context` serializes only `turn.text`, so
search traces are excluded from forward context by construction — same as `meta.reasoning` /
`meta.served_model`. No `forward_turns` change.

## 17.1 — Enable (per-provider flag + adapter attach)
- Add `web_search: bool` to the registry (**default false**), with a "web search" toggle in the
  Providers panel beside "show reasoning" — mirror the `reasoning` flag.
- Replace the no-op: in the API adapters, when a call has `tools=True` **and** the provider's
  `web_search` is true, attach the backend-appropriate search tool:
  - **anthropic**: `{"type": "web_search_20260209", "name": "web_search"}` — **verify the dated
    string at wire time.**
  - **openai + OpenRouter base_url**: `openrouter:web_search` server tool (`:online` / `web` plugin
    are deprecated).
- Flag off → request byte-identical to today.

## 17.2 — Capture the search trace (provenance → `meta.search`)
- Capture searches into `meta.search`, **normalized across backends**: anthropic (queries from
  `server_tool_use`, results from `web_search_tool_result`, citations from text blocks); OpenRouter
  (`url_citation` annotations). Form: `meta.search = [{query?, sources:[{url,title,snippet?}]}]` plus
  a flat `meta.citations`.
- Stamp via the same `_reply_meta` helper. Persists on JSONL meta; confirm on read-back.
- Excluded from `build_context` (assert, mirroring the reasoning isolation gate).

## 17.3 — Sources disclosure (UI) — rides the phase-16 footer
- In the turn footer (beside thinking/model), a collapsed **"sources (N)"** disclosure when
  `t.meta?.search` has entries; expanded lists sources as links.
- **Safe links:** label via `textContent`; `href` set ONLY after an http/https scheme allowlist
  (reject `javascript:` etc.), `target="_blank"`, `rel="noopener noreferrer"`. Never innerHTML.

## Gate
- Engine: stubbed-httpx — tool attached iff on (`web_search_20260209` / `openrouter:web_search`),
  capture → `meta.search`, excluded from `build_context`.
- Browser: `tests/browser_phase17.py` — sources disclosure expands to safe links.
- Real-key (opt-in, `RR_LIVE=1`): live Anthropic + OR calls confirm the shapes / dated string.

## Housekeeping
Replace the stale `providers.py:290` no-op comment; DEFERRED.md decision record (shared-retrieval
rejected); README (toggle, independent-search semantics, sources disclosure, Grok note); cost axis.

---

## As-built notes (deviations / confirmations worth recording)

- **Adapters grew to a 5-tuple.** Following the phase-16 pattern, `*_style.chat()` now returns
  `(text, reasoning, usage, served_model, search)`, where `search` is the normalized
  `{"searches": [...], "citations": [...]}` dict (or `None`). `call_model` computes
  `do_search = tools and p.web_search` and passes `web_search=do_search` to the adapter; the cli path
  is untouched (its runner governs search) and leaves `search=None`. `ModelReply` gained a single
  `search` dict field; `_reply_meta` unpacks it into `meta.search` + `meta.citations` so panel, judge,
  and converse are all covered by the one helper. The three `.chat()` unpackings in `engine_phase11`
  were widened to 5 (no behaviour change there).
- **OpenRouter detection is by base_url.** `_is_openrouter(provider)` = `"openrouter.ai" in base_url`.
  The tool is only attached for openai-backend providers whose base_url is OpenRouter — a direct
  DeepSeek/Moonshot base gets nothing (no mechanism), asserted in the engine gate. So "route DeepSeek
  (or Kimi) through OpenRouter to get search" is enforced by construction, matching the spec's
  two-mechanism plan.
- **Mock honours the toggle (offline testability).** `call_model`'s mock branch returns a
  deterministic `_mock_search(p)` when `do_search` — one `https://example.com/a` source **and** one
  `javascript:alert(1)` source — which is what lets `browser_phase17` exercise the real render +
  the link allowlist with zero tokens/network. New `mocksearch` fixture (mock backend,
  `web_search=true`, disabled-by-default like `mockthink`).
- **The dated Anthropic string + OR tool id are best-effort (cutoff caveat).** I used the spec's
  `web_search_20260209` and `openrouter:web_search` verbatim; the offline gates assert *our own*
  assumed request/response shapes (we write both stub and parser), so they prove the wiring, not the
  live contract. `tests/live_phase17.py` (opt-in `RR_LIVE=1`, billed) is where the real shapes get
  confirmed — it surfaces a bumped dated string or a changed OR tool id / annotation field as a
  failure, with a note to update the adapter. Could not run it here (no keys/network); it's yours to
  run once.
- **UI: footer return shape changed `{footer, body}` → `{footer, bodies[]}`.** `turnFooterParts`
  now collects multiple below-footer bodies (reasoning + sources); `appendTurnFooter` appends each.
  `.reasoning-toggle` / `.reasoning-body` names + wiring are byte-preserved (browser_reasoning
  passes unchanged). Sources get their own `.sources-toggle` / `.sources-body` classes (not reused
  from reasoning, to avoid coupling the two disclosures' selectors). `safeLink()` builds each `<a>`
  with `textContent` + a `new URL().protocol` http/https allowlist; blocked links render struck-through
  with no href. `sourcesOf()` flattens `meta.search` groups + `meta.citations` and dedupes by url so
  the "(N)" count is honest.
- **Scope held to research.** Converse/margin call `tools=False`, so `do_search` is false there —
  asserted (`converse turn has NO meta.search`). The panel "searched" badge (`meta.tools`) was left
  as the cli marker; API search surfaces through the sources disclosure instead.
- **Gate:** `engine_phase17.py` (attach iff on + correct backend, normalize both shapes, e2e
  meta.search + persistence, build_context isolation), `browser_phase17.py` (sources disclosure +
  allowlist), `live_phase17.py` (opt-in real probe). Full suite **21/21** (15 browser + 6 engine),
  DOM ids intact, `.reasoning-*` classes unchanged.
