"use strict";

// ===== sanitization (load-bearing) ==========================================
// Order is strict: markdown -> HTML -> DOMPurify.sanitize -> insert. If marked
// or DOMPurify failed to load (e.g. CDN down), FAIL CLOSED: render as plain text
// via textContent, NEVER raw innerHTML. This applies to every speaker bubble and
// every panel card, since model output (incl. Grok's web-searched content) is
// untrusted text.
function libsReady() {
  return typeof window.marked !== "undefined" && typeof window.DOMPurify !== "undefined";
}
function renderMd(el, text) {
  if (libsReady()) {
    el.innerHTML = DOMPurify.sanitize(window.marked.parse(text || "", { breaks: true }));
    el.classList.add("md");
  } else {
    el.textContent = text || "";   // fail closed
  }
}

// ===== state (no browser storage — the server is the single source) ==========
// STATE.room is the room ON SCREEN (id, title, participants[], judge). STATE.rooms
// is the sidebar list. Reload reconstructs everything from /ui + /rooms + the
// active room — nothing is read from localStorage.
let STATE = {
  participants: [],          // global registry (colours, addressee)
  globalJudge: "",
  room: null,                // active room or null
  turns: [],
  rooms: [],                 // sidebar list
  ui: { sidebar_collapsed: false, sidebar_width: 260 },
  marginTurns: [],           // active room's margin.jsonl
  marginOpen: false,
  viewerOpen: false,         // artifact viewer pane (Phase 33); mutually exclusive with the margin
  codeOpen: false,           // code seat pane + outbox (Phase 39)
  codeTurns: [],             // isolated code.jsonl turns (Phase 39.2) — never main
  codeMode: "build",         // harness mode: build | plan | ask
  codeReasoning: "",         // OpenCode variant: "" | low | medium | high | max
  codeStreaming: null,       // live code-seat bubble {text}
  codeAbort: null,           // AbortController for code stream
  outbox: [],                // pending diplomatic crossings for the active room
  staged: [],                // composer-staged files [{filename, content}] (Phase 22)
  drafts: {},                // room_id -> composer draft; session-only, NOT persisted (Phase 31.2)
  marginDrafts: {},          // room_id -> margin draft; session-only (Phase 31.2)
  pending: null,             // optimistic user turn {text, ts} awaiting the server (Phase 31.3)
  streaming: null,           // live converse AI bubble {speaker, text} while a stream runs (Phase 36.4)
  streamAbort: null,         // AbortController for the in-flight converse stream (Phase 36.5)
  roomModes: {},             // room_id -> session interaction mode (Phase 35.2); default converse
  roomAddressees: {},        // room_id -> session addressee (Phase 35.2); default auto (last AI)
  advancedOpen: false,       // is the composer's mode disclosure open? (Phase 35.1)
  paintDots: null,           // 38.4: non-null ONLY while a painted future pattern does NOT
                             // compile — the bare overlay. A compiling paint is written into
                             // the composer controls instead; state stays the single truth.
};

// ===== theme mode (dark / light / system) ===================================
// The accent + text ramps below are INLINE styles on documentElement, so a
// [data-theme="light"] CSS block would be overridden by them — light surfaces with
// dark-tuned text/accent. So the single repaint path is applyThemeMode(): it sets
// data-theme (drives the CSS surface block) AND re-runs both ramps with mode-aware
// values. currentHue/currentLevel/currentTheme are kept in module scope so any flip
// (control, OS change) can re-apply. localStorage stays empty — the mode lives in
// ui.json like accent_hue, applied from the server value on boot.
let currentHue = 233;          // accent hue (oklch degrees)
let currentLevel = "default";  // text-brightness step
let currentTheme = "dark";     // RESOLVED concrete mode (system → dark|light)
let _mq = null, _mqListener = null;   // single OS-theme listener (system mode only)

function resolveMode(mode) {
  if (mode === "system") {
    return (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
  }
  return mode === "light" ? "light" : "dark";
}

function applyThemeMode(mode) {
  currentTheme = resolveMode(mode);
  document.documentElement.dataset.theme = currentTheme;   // drives the CSS surface block
  applyAccent(currentHue);                                // re-derive inline vars for THIS mode
  applyBrightness(currentLevel);
  // live OS-follow ONLY in system mode; hold one ref so listeners never stack.
  if (_mq && _mqListener) { _mq.removeEventListener("change", _mqListener); _mqListener = null; }
  if (mode === "system" && window.matchMedia) {
    _mq = window.matchMedia("(prefers-color-scheme: dark)");
    _mqListener = () => {
      currentTheme = _mq.matches ? "dark" : "light";
      document.documentElement.dataset.theme = currentTheme;
      applyAccent(currentHue); applyBrightness(currentLevel);
    };
    _mq.addEventListener("change", _mqListener);
  }
}

// ===== accent engine (one hue, six derived; mode-aware states) ===============
// Compose oklch(L C H) per role — only the hue varies, so any hue recolours every
// interactive/selected state coherently. Hue stays user-selectable in both modes;
// what forks by currentTheme is the state DIRECTION (dark hover lightens / light
// hover+active darken for contrast on white) and --accent-text's L. --accent /
// --accent-subtle / --accent-border are shared (the translucent tint reads on
// either base). The browser does oklch→screen; no colour math, no lib, no build.
function applyAccent(hue) {
  const h = Number(hue);
  if (Number.isNaN(h)) return;
  const r = document.documentElement.style;
  const light = currentTheme === "light";
  const hoverL  = light ? 0.50 : 0.60;   // base 0.55: dark +0.05 / light −0.05
  const activeL = light ? 0.45 : 0.50;   //            dark −0.05 / light −0.10
  const textL   = light ? 0.47 : 0.72;   // legible accent text on white vs dark
  r.setProperty("--accent",        `oklch(0.55 0.15 ${h})`);
  r.setProperty("--accent-hover",  `oklch(${hoverL} 0.15 ${h})`);
  r.setProperty("--accent-active", `oklch(${activeL} 0.15 ${h})`);
  r.setProperty("--accent-text",   `oklch(${textL} 0.15 ${h})`);
  r.setProperty("--accent-subtle", `oklch(0.55 0.15 ${h} / 0.16)`);
  r.setProperty("--accent-border", `oklch(0.55 0.15 ${h} / 0.36)`);
}

// Text brightness — derive the whole grey ramp from ONE control, mode-aware.
// DARK: a top-lightness × fixed proportions (calmer on dark). LIGHT: explicit
// per-role L rows (near-black primary descending toward white). Same UX (soft /
// default / crisp), two tables — the ramp-as-function pattern light reuses.
const BRIGHTNESS_TOP = { soft: 0.82, default: 0.90, crisp: 0.97 };
const RAMP_STEPS = [1.0, 0.856, 0.649, 0.495];   // dark primary→quaternary proportions
const LIGHT_RAMP = {   // light per-role L (primary→quaternary), neutral greys
  crisp:   [0.12, 0.32, 0.51, 0.66],
  default: [0.13, 0.36, 0.56, 0.71],
  soft:    [0.20, 0.41, 0.60, 0.74],
};
const TEXT_VARS = ["--text-primary", "--text-secondary", "--text-tertiary", "--text-quaternary"];
function applyBrightness(level) {
  const r = document.documentElement.style;
  if (currentTheme === "light") {
    const rows = LIGHT_RAMP[level] ?? LIGHT_RAMP.default;
    TEXT_VARS.forEach((n, i) => r.setProperty(n, `oklch(${rows[i].toFixed(3)} 0.012 256)`));
  } else {
    const top = BRIGHTNESS_TOP[level] ?? BRIGHTNESS_TOP.default;
    TEXT_VARS.forEach((n, i) => r.setProperty(n, `oklch(${(top * RAMP_STEPS[i]).toFixed(3)} 0.012 256)`));
  }
}

// Font size — one multiplier the 12–35px ramp is expressed against (mode-independent).
const FONT_SCALE = { compact: 0.92, default: 1.0, large: 1.12, xlarge: 1.3, huge: 1.5 };
function applyFontScale(level) {
  document.documentElement.style.setProperty("--font-scale", String(FONT_SCALE[level] ?? 1));
}

// How the app addresses you — replaces the "human" label in the UI (and [human]
// in build_context, server-side). Still the human role under the hood.
function displayName() { return (STATE.ui.display_name || "").trim() || "human"; }

// Speaker-dot identity colours — a small map kept OUTSIDE the token/accent system
// (semantic identity, not theme). Provider dots come from each provider's config.
const DOT_MAP = { human: "#6ee7b7", judge: "#f0abfc" };
const DOT_DEFAULT = "#9aa3b2";

function colorOf(s) {
  const p = STATE.participants.find((x) => x.name === s);
  if (p) return p.color;
  return DOT_MAP[s] || DOT_DEFAULT;
}
function dot(color) {
  const d = document.createElement("span");
  d.className = "dot"; d.style.background = color; return d;
}
function whoLine(speaker, color, extra) {
  const d = document.createElement("div"); d.className = "who";
  d.appendChild(dot(color));
  const nm = document.createElement("span"); nm.style.color = color; nm.textContent = speaker;
  d.appendChild(nm);
  if (extra) { const e = document.createElement("span"); e.style.color = "var(--text-tertiary)"; e.textContent = " · " + extra; d.appendChild(e); }
  return d;
}
function $(s) { return document.querySelector(s); }
function el(tag, cls) { const e = document.createElement(tag); if (cls) e.className = cls; return e; }
function lbl(t) { const e = el("label"); e.textContent = t; return e; }

function banner(msg) {
  const b = $("#banner");
  if (!msg) { b.classList.add("hidden"); return; }
  b.textContent = msg; b.classList.remove("hidden");
}
function setStatus(msg, busy) {
  const s = $("#status");
  s.innerHTML = "";
  s.classList.toggle("busy", !!busy);
  if (busy) { const sp = document.createElement("span"); sp.className = "spinner"; s.appendChild(sp); }
  if (msg) s.appendChild(document.createTextNode(msg));
}

// Focus the composer — but never yank focus out of an open overlay/palette, and never
// scroll-jump. Called from the four sites recon confirmed leave focus nowhere: app load,
// room switch, new-room create, margin close (Phase 31.1). A missing overlay element
// (order-independent) is simply skipped.
function focusComposer() {
  const blocked = ["#room-settings-overlay", "#providers-overlay", "#palette-overlay"]
    .some((s) => { const e = $(s); return e && !e.classList.contains("hidden"); });
  if (blocked) return;
  const input = $("#input");
  if (input) input.focus({ preventScroll: true });
}

// ===== API ===================================================================
function _errDetail(data, res) {
  // FastAPI may return detail as string, list of validation errors, or object.
  const d = data && data.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join("; ");
  if (d && typeof d === "object") return JSON.stringify(d);
  return `${res.status} ${res.statusText}`;
}
async function api(path, method, body) {
  const opts = { method: method || "GET" };
  if (body !== undefined) { opts.headers = { "Content-Type": "application/json" }; opts.body = JSON.stringify(body); }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(_errDetail(data, res));
  return data;
}

// ===== transcript rendering (unchanged shape) ================================
function groupTurns(turns) {
  const blocks = []; let round = null;
  for (const t of turns) {
    const rid = t.meta && t.meta.round_id;
    if (t.mode === "research" && rid) {
      if (!round || round.rid !== rid) { round = { type: "round", rid, prompt: null, panels: [], judge: null }; blocks.push(round); }
      if (t.role === "human") round.prompt = t;
      else if (t.role === "judge") round.judge = t;
      else if (t.meta && t.meta.is_panelist_raw) round.panels.push(t);
      continue;
    }
    round = null; blocks.push({ type: "converse", turn: t });
  }
  return blocks;
}

function renderConverse(t) {
  if (t.meta && t.meta.kind === "file") return renderFileTurn(t);   // attached document (Phase 22)
  const div = document.createElement("div");
  div.className = "turn" + (t.role === "human" ? " human" : "");
  div.dataset.turnId = t.id;                // graph jump anchor (Phase 37); stamped at BUILD time —
                                            // render() tears #stream down on every streaming frame
  const isHuman = t.role === "human";
  const fromMargin = t.meta && t.meta.from_margin;
  const fromCode = t.meta && t.meta.from_code;
  const extra = (fromMargin ? "from margin" : fromCode ? "from code" : "") || (t.meta && t.meta.model) || "";
  // label uses the display name for human turns; dot colour stays keyed on "human"
  div.appendChild(whoLine(isHuman ? displayName() : t.speaker, colorOf(isHuman ? "human" : t.speaker), extra));
  const body = document.createElement("div"); body.className = "body";
  renderMd(body, t.text); div.appendChild(body);
  appendTurnFooter(div, t);                 // thinking + model pills, reasoning body below
  const ac = artifactControls(t); if (ac) div.appendChild(ac);
  return div;
}

// The optimistic user turn (Phase 31.3): the just-sent message painted immediately,
// before the server round-trip, with a subtle pending affordance (dimmed + a spinner
// matching the status idiom). Transient — adoptRoom nulls STATE.pending so the
// authoritative server turn replaces it in the same paint; no IDs, no reconciliation.
function renderPending(p) {
  const div = el("div", "turn human pending");
  div.appendChild(whoLine(displayName(), colorOf("human"), ""));
  const body = el("div", "body"); renderMd(body, p.text); div.appendChild(body);
  const foot = el("div", "pending-foot");
  foot.append(el("span", "spinner"), document.createTextNode("sending…"));
  div.appendChild(foot);
  return div;
}

// The live AI bubble while a converse streams (Phase 36.4): the speaker's turn, its body
// re-rendered per delta, plus a spinner + a Stop button (36.5). Transient — on the terminal
// `done`, adoptRoom swaps in the authoritative turn (STATE.streaming is nulled first, so no
// duplicate); the who-line speaker is a best-guess until then (auto-addressee resolves on adopt).
function renderStreaming(s) {
  const div = el("div", "turn streaming");
  div.appendChild(whoLine(s.speaker, colorOf(s.speaker), ""));
  const body = el("div", "body"); renderMd(body, s.text || "…"); div.appendChild(body);
  const foot = el("div", "pending-foot");
  const stop = el("button", "stop-btn"); stop.type = "button"; stop.textContent = "Stop";
  stop.addEventListener("click", () => { if (STATE.streamAbort) STATE.streamAbort.abort(); });
  foot.append(el("span", "spinner"), document.createTextNode("streaming… "), stop);
  div.appendChild(foot);
  return div;
}

function plainPreview(text, n = 160) { return (text || "").replace(/\s+/g, " ").trim().slice(0, n); }

// The thinking level actually REQUESTED for a turn (stamped in meta.reasoning_effort):
// 'off' (reasoning toggle was off → the effort dial was inert), 'default', or the effort.
function thinkingLabel(e) {
  if (!e) return "—";
  if (e === "off") return "off (reasoning disabled)";
  if (e === "default") return "default";
  return e;
}

// Per-turn metadata popover, anchored to the model pill (singleton, mirrors the
// model-square popover). Keeps the footer clean: served model · thinking level ·
// reasoning tokens (the ACTUAL think, vs the requested level) · tokens · cost · finish,
// plus a "view thinking" button when a trace exists (toggles the footer disclosure).
let _turnPopTimer = null;
function hideTurnPopover() { clearTimeout(_turnPopTimer); const p = $("#turn-popover"); if (p) p.classList.add("hidden"); }
function scheduleHideTurnPop() { clearTimeout(_turnPopTimer); _turnPopTimer = setTimeout(hideTurnPopover, 180); }
function showTurnPopover(t, toggleBtn, rect) {
  clearTimeout(_turnPopTimer);
  const pop = $("#turn-popover"); if (!pop) return;
  pop.innerHTML = "";
  const meta = t.meta || {}; const u = meta.usage || {};
  const head = el("div", "mp-headrow"); const box = el("div", "mp-headbox");
  const nm = el("div", "mp-head"); nm.textContent = meta.served_model || meta.model || "model"; box.append(nm);
  if (meta.model && meta.served_model && meta.model !== meta.served_model) {
    const s = el("div", "mp-sub"); s.textContent = "configured: " + meta.model; box.append(s);
  }
  head.append(box); pop.append(head);
  if (toggleBtn) {
    const vb = el("button", "tp-view"); vb.append(boltIcon(), document.createTextNode(" view thinking"));
    vb.addEventListener("click", () => { hideTurnPopover(); toggleBtn.click(); toggleBtn.scrollIntoView({ block: "nearest" }); });
    pop.append(vb);
  }
  const stats = el("div", "mp-stats");
  const rows = [["Thinking", thinkingLabel(meta.reasoning_effort)],
                ["Reasoning", (u.reasoning != null ? fmtTokens(u.reasoning) + " tok" : (meta.reasoning_effort === "off" ? "none" : "—"))],
                ["Tokens", (u.input != null ? `${u.exact ? "" : "~"}${fmtTokens(u.input)} in / ${fmtTokens(u.output || 0)} out` : "—")]];
  if (u.cached) rows.push(["Cached", `${fmtTokens(u.cached)} in (~90% off)`]);   // prompt-cache hit
  if (typeof u.cost === "number") rows.push(["Cost", fmtCost(u.cost)]);
  if (meta.finish_reason) rows.push(["Finish", meta.finish_reason]);
  for (const [l, v] of rows) stats.append(mpRow(l, v));
  pop.append(stats);
  pop.classList.remove("hidden");
  pop.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - pop.offsetWidth - 12)) + "px";
  pop.style.top = Math.max(8, rect.top - pop.offsetHeight - 8) + "px";   // above the pill
  pop.onmouseenter = () => clearTimeout(_turnPopTimer);
  pop.onmouseleave = scheduleHideTurnPop;
}

// The provenance pill: served model as text (prefix-stripped); hover opens the metadata
// popover above. Tints + names both when served ≠ configured. textContent only.
function modelPill(t, toggleBtn) {
  const served = t.meta && t.meta.served_model;
  if (!served) return null;
  const pill = el("span", "model-pill");
  pill.textContent = served.includes("/") ? served.split("/").pop() : served;   // e.g. grok-4.3
  pill.title = "served model: " + served;
  const configured = t.meta && t.meta.model;
  if (configured && configured !== served) {            // header label ≠ what the API served
    pill.classList.add("mismatch");
    pill.title += "  (configured: " + configured + ")";
  }
  pill.addEventListener("mouseenter", () => showTurnPopover(t, toggleBtn, pill.getBoundingClientRect()));
  pill.addEventListener("mouseleave", scheduleHideTurnPop);
  pill.addEventListener("click", () => showTurnPopover(t, toggleBtn, pill.getBoundingClientRect()));   // touch
  return pill;
}

// Flatten + dedupe (by url) a turn's web-search provenance into a single source
// list. meta.search is grouped by query; meta.citations is the flat in-text set —
// both feed the disclosure, deduped so the "(N)" count is honest.
function sourcesOf(meta) {
  const out = []; const seen = new Set();
  const push = (s) => { if (s && s.url && !seen.has(s.url)) { seen.add(s.url); out.push(s); } };
  for (const g of (meta.search || [])) for (const s of (g.sources || [])) push(s);
  for (const c of (meta.citations || [])) push(c);
  return out;
}

// A clickable source link, hardened because the url is web-sourced (untrusted):
// label via textContent (never innerHTML); href set ONLY after an http/https scheme
// allowlist (rejects javascript: etc.) with target/rel; blocked links render as
// plain, non-clickable text.
function safeLink(url, label) {
  let ok = false;
  try { const u = new URL(url, location.href); ok = (u.protocol === "http:" || u.protocol === "https:"); }
  catch (e) { ok = false; }
  const a = el("a", "source-link");
  a.textContent = label || url || "(source)";
  if (ok) { a.setAttribute("href", url); a.setAttribute("target", "_blank"); a.setAttribute("rel", "noopener noreferrer"); }
  else { a.classList.add("blocked"); a.title = "blocked non-http(s) link"; }   // no href → not clickable
  return a;
}

// The per-turn footer: a small muted row holding, side by side, the "thinking"
// toggle, the "model" pill, and a "sources (N)" toggle. Their bodies (reasoning,
// sources) are returned separately so callers render them FULL-WIDTH below the
// footer, not width-constrained inside the flex row. The .reasoning-toggle button +
// .reasoning-body element + click→toggle wiring are kept exactly as named —
// browser_reasoning keys off both classes. Returns null if the turn has none of them.
// A non-interactive badge flagging that the answer didn't end cleanly: "length" =
// the model hit its token ceiling (answer truncated mid-thought); "tool_calls" = it
// stopped expecting a tool round it never got. A clean "stop" → no badge.
function truncBadge(meta) {
  const fr = meta.finish_reason;
  if (fr !== "length" && fr !== "tool_calls") return null;
  const b = el("span", "trunc-badge");
  if (fr === "length") { b.textContent = "⚠ truncated"; b.title = "hit the token ceiling — answer cut off. Raise RESEARCH_ROOM_RESEARCH_MAX_TOKENS."; }
  else { b.textContent = "⚠ incomplete"; b.title = "stopped on a tool call that wasn't continued."; }
  return b;
}

// a copy button for an output turn: copies the turn's text with a brief "copied" state.
function copyButton(t) {
  const btn = el("button", "copy-btn");
  btn.textContent = "copy"; btn.title = "copy this answer";
  btn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(t.text || "");
      btn.textContent = "copied ✓"; setTimeout(() => (btn.textContent = "copy"), 1200);
    } catch (e) { banner("copy failed: " + e.message); }
  });
  return btn;
}

function turnFooterParts(t) {
  const meta = t.meta || {};
  const hasReasoning = !!meta.reasoning;
  const served = meta.served_model;
  const sources = sourcesOf(meta);
  const trunc = truncBadge(meta);
  const isOutput = t.role === "ai" || t.role === "judge";   // copy button on every output turn
  if (!hasReasoning && !served && !sources.length && !trunc && !isOutput) return null;
  const footer = el("div", "turn-footer");
  const bodies = [];
  let thinkToggle = null;                                // the trace toggle, surfaced in the pill popover
  if (trunc) footer.append(trunc);                       // truncation flag leads (most important)
  if (hasReasoning) {
    const summarized = meta.reasoning_kind === "summarized";
    const btn = el("button", "reasoning-toggle");
    btn.textContent = summarized ? "▸ thinking (summary)" : "▸ thinking";
    const body = el("div", "reasoning-body hidden"); renderMd(body, meta.reasoning);
    btn.addEventListener("click", () => {
      const show = body.classList.contains("hidden");
      body.classList.toggle("hidden", !show);
      btn.textContent = (show ? "▾ " : "▸ ") + (summarized ? "thinking (summary)" : "thinking");
    });
    footer.append(btn); bodies.push(body); thinkToggle = btn;   // thinking first…
  }
  if (served) footer.append(modelPill(t, thinkToggle));  // …then model (hover → metadata popover)…
  if (sources.length) {                                  // …then sources
    const btn = el("button", "sources-toggle");
    const label = (n) => `sources (${n})`;
    btn.textContent = "▸ " + label(sources.length);
    const body = el("div", "sources-body hidden");
    for (const s of sources) {
      const row = el("div", "source-row");
      row.append(safeLink(s.url, s.title || s.url));
      if (s.snippet) { const sn = el("div", "source-snippet"); sn.textContent = s.snippet; row.append(sn); }
      body.append(row);
    }
    btn.addEventListener("click", () => {
      const show = body.classList.contains("hidden");
      body.classList.toggle("hidden", !show);
      btn.textContent = (show ? "▾ " : "▸ ") + label(sources.length);
    });
    footer.append(btn); bodies.push(body);
  }
  if (isOutput) footer.append(copyButton(t));            // …copy last (rightmost)
  return { footer, bodies };
}

// Append the footer (if any pill/toggle applies) then each full-width body below it.
function appendTurnFooter(container, t) {
  const parts = turnFooterParts(t);
  if (!parts) return;
  container.appendChild(parts.footer);
  parts.bodies.forEach((b) => container.appendChild(b));
}

// Markdown artifact detection — ONE rule: a fenced ```markdown block. On a match,
// show copy (raw .md → clipboard) + save (→ artifacts dir, server-side) controls.
function extractMdBlocks(text) {
  const re = /```markdown[ \t]*\r?\n([\s\S]*?)```/gi;
  const out = []; let m;
  while ((m = re.exec(text || ""))) { const c = m[1].trim(); if (c) out.push(c); }
  return out;
}
function baseName(p) { return String(p || "").split(/[\\/]/).filter(Boolean).pop() || String(p || ""); }

// "copy path" — the CC-handoff gesture (Phase 32.4): clipboard gets the saved .md path so
// you can hand it straight to Claude Code / a spec that references companion files.
function copyPathBtn(path) {
  const cp = el("button", "artifact-btn"); cp.textContent = "copy path"; cp.title = path;
  cp.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(path); cp.textContent = "copied ✓";
          setTimeout(() => (cp.textContent = "copy path"), 1200); }
    catch (e) { banner("copy failed: " + e.message); }
  });
  return cp;
}

// Artifact chips under a turn (Phase 14 detection; Phase 32.4 saved-state). Detection stays
// client-side (a ```markdown block); when the turn ALSO carries meta.artifact_paths (32.3
// auto-save), the chip upgrades to the saved FILENAME + a "copy path" button (tooltip = full
// path). Block↔path is positional — on a count mismatch we fall back to detection-only rather
// than guess. Legacy turns (no meta) and no-dir rooms render exactly as before.
function artifactControls(t) {
  const blocks = extractMdBlocks(t.text);
  if (!blocks.length) return null;
  const saved = (t.meta && t.meta.artifact_paths) || [];
  const matched = saved.length === blocks.length;      // positional match or bust
  const wrap = el("div", "artifacts");
  blocks.forEach((content, i) => {
    const row = el("div", "artifact");
    const lab = el("span", "artifact-label");
    const savedPath = matched ? saved[i] : null;
    const title = savedPath ? baseName(savedPath) : `markdown artifact${blocks.length > 1 ? " " + (i + 1) : ""}`;
    if (savedPath) { row.classList.add("saved"); lab.textContent = "📄 " + baseName(savedPath); lab.title = "saved to " + savedPath; }
    else lab.textContent = `📄 markdown artifact${blocks.length > 1 ? " " + (i + 1) : ""}`;
    // open the block rendered in the right-side viewer pane (Phase 33.4) — source is the
    // turn's own text (already in this closure), no endpoint. The filename is a click
    // target too, and the "open" button carries the discoverable/a11y affordance.
    const openThis = () => openViewer({ title, content, savedPath });
    lab.classList.add("clickable"); lab.addEventListener("click", openThis);
    const open = el("button", "artifact-btn"); open.textContent = "open";
    open.addEventListener("click", openThis);
    const copy = el("button", "artifact-btn"); copy.textContent = "copy";
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(content); copy.textContent = "copied ✓";
            setTimeout(() => (copy.textContent = "copy"), 1200); }
      catch (e) { banner("copy failed: " + e.message); }
    });
    row.append(lab, open, copy);
    if (savedPath) row.append(copyPathBtn(savedPath));   // auto-saved → offer its path
    const save = el("button", "artifact-btn"); save.textContent = "save";
    save.addEventListener("click", async () => {
      if (!STATE.room) return;
      try {
        const r = await api(`/rooms/${STATE.room.id}/artifact`, "POST", { content });
        banner(`Saved ${r.path}`);
        if (r.path && !row.classList.contains("saved")) {  // reflect the manual save on the chip (32.4)
          row.classList.add("saved"); lab.textContent = "📄 " + baseName(r.path); lab.title = "saved to " + r.path;
          row.insertBefore(copyPathBtn(r.path), save);
        }
      } catch (e) { banner(e.message); }
    });
    row.append(save); wrap.append(row);
  });
  return wrap;
}

function renderRound(b) {
  const div = document.createElement("div"); div.className = "round";
  if (b.prompt) {
    // A round is a COMPOUND container: the graph anchors the prompt, each panel card and the
    // synthesis separately — never the .round div, which spans ~6 turns (Phase 37).
    const pr = document.createElement("div"); pr.className = "prompt";
    pr.dataset.turnId = b.prompt.id;
    // round provenance (Phase 27): the mode that ran + whether the panel saw the
    // conversation — read from the round-head turn's stamped selection.
    const sel = (b.prompt.meta && b.prompt.meta.selection) || {};
    let lbl = (sel.mode || "research").replace(/_/g, "-");
    if (sel.panel_context === "transcript") lbl += " · panel saw chat";
    pr.appendChild(whoLine(displayName(), colorOf("human"), lbl));
    const body = document.createElement("div"); body.className = "body"; renderMd(body, b.prompt.text);
    pr.appendChild(body); div.appendChild(pr);
  }
  if (b.panels.length) {
    const grid = document.createElement("div"); grid.className = "panels";
    for (const p of b.panels) {
      const c = colorOf(p.speaker);
      const card = document.createElement("div"); card.className = "panel";
      card.dataset.turnId = p.id;
      const head = document.createElement("div"); head.className = "phead";
      head.appendChild(dot(c));
      const nm = document.createElement("span"); nm.className = "pname"; nm.style.color = c; nm.textContent = p.speaker; head.appendChild(nm);
      const mb = document.createElement("span"); mb.className = "badge"; mb.textContent = (p.meta && p.meta.model) || ""; head.appendChild(mb);
      if (p.meta && p.meta.tools) { const sb = document.createElement("span"); sb.className = "badge searched"; sb.textContent = "searched"; head.appendChild(sb); }
      card.appendChild(head);
      const prev = document.createElement("div"); prev.className = "preview"; prev.textContent = plainPreview(p.text); card.appendChild(prev);
      const full = document.createElement("div"); full.className = "full hidden"; renderMd(full, p.text); card.appendChild(full);
      const btn = document.createElement("button"); btn.className = "viewfull"; btn.textContent = "view full";
      btn.addEventListener("click", () => {
        const showing = full.classList.contains("hidden");   // about to show?
        full.classList.toggle("hidden", !showing);
        prev.classList.toggle("hidden", showing);
        btn.textContent = showing ? "collapse" : "view full";
      });
      card.appendChild(btn);
      appendTurnFooter(card, p);            // panel provenance: thinking + model
      grid.appendChild(card);
    }
    div.appendChild(grid);
  }
  // dropped panelists (failed → absent, NEVER counted as agreement). The reason rides the
  // judge turn's meta.absent (Phase 30) — surfaced here + on hover, so "why did X drop?"
  // is answerable in the UI instead of lost to the judge prompt.
  const absent = (b.judge && b.judge.meta && b.judge.meta.absent) || [];
  if (absent.length) {
    const box = el("div", "absent-note");
    box.append(document.createTextNode("⚠ dropped (not counted): "));
    absent.forEach((a, i) => {
      const s = el("span", "absent-seat");
      s.textContent = a.speaker;
      s.title = a.error || "failed";          // the reason, on hover
      box.append(s);
      if (i < absent.length - 1) box.append(document.createTextNode(", "));
    });
    div.appendChild(box);
  }
  if (b.judge) {
    const syn = document.createElement("div"); syn.className = "synthesis";
    syn.dataset.turnId = b.judge.id;
    const n = b.panels.length;
    const ff = b.judge.meta && b.judge.meta.judge_fallback_from;
    // mode-aware label: synthesis (fusion) | map (mapping) | divergence (side-by-side)
    const kind = (b.judge.meta && b.judge.meta.judge_kind) || "synthesis";
    const extra = `${kind} · ${n} panelist${n === 1 ? "" : "s"}` + (ff ? ` · judge fell back from ${ff}` : "");
    syn.appendChild(whoLine(b.judge.speaker, colorOf(b.judge.speaker), extra));
    const body = document.createElement("div"); renderMd(body, b.judge.text); syn.appendChild(body);
    appendTurnFooter(syn, b.judge);         // synthesis provenance: thinking + model
    const ac = artifactControls(b.judge); if (ac) syn.appendChild(ac);
    div.appendChild(syn);
  }
  return div;
}

// Set by adoptRoom on a room SWITCH: a freshly opened room always lands at the bottom,
// whatever the outgoing room's scroll position was.
let _forcePin = false;

function render() {
  $("#title").textContent = STATE.room ? STATE.room.title : "";
  $("#room-settings-btn").disabled = !STATE.room;
  $("#margin-toggle").disabled = !STATE.room;
  const codeBtn = $("#code-toggle"); if (codeBtn) codeBtn.disabled = !STATE.room;
  $("#rollback-btn").disabled = !STATE.room || !STATE.turns.length;
  renderModelBar();
  const main = $("#stream");
  // Pin to the bottom only if we were ALREADY there (Phase 37). render() runs once per
  // animation frame while a converse streams, so an unconditional pin yanks the reader back
  // from scrollback mid-stream — and it would eat every graph jump.
  const pin = _forcePin || main.scrollTop + main.clientHeight >= main.scrollHeight - 40;
  _forcePin = false;
  main.innerHTML = "";
  if (!STATE.room) {
    main.innerHTML = '<div class="empty">No room yet. Click <b>+ new room</b> to start one.</div>';
    return;
  }
  if (!STATE.turns.length && !STATE.pending && !STATE.streaming) {
    const roster = (STATE.room.participants || []).length;
    main.innerHTML = roster
      ? '<div class="empty">Empty room — send the first message.</div>'
      : '<div class="empty">Empty room. Pick this room\'s models with <b>models</b> (top-right) to begin.</div>';
    return;
  }
  for (const b of groupTurns(STATE.turns)) main.appendChild(b.type === "round" ? renderRound(b) : renderConverse(b.turn));
  if (STATE.pending) main.appendChild(renderPending(STATE.pending));       // optimistic user turn (Phase 31.3)
  if (STATE.streaming) main.appendChild(renderStreaming(STATE.streaming)); // live converse AI bubble (Phase 36.4)
  if (pin) main.scrollTop = main.scrollHeight;
}

// ===== trajectory graph (Phase 37) ==========================================
// A client-side mirror of the engine's forward view. The bright line traces exactly
// what flows into the next model's context; raw panel answers hang off it as dim nodes.
//
// The predicate below is the ONE thing that must stay in step with the engine.
// Canonical definition: engine/context.forward_turns. Four consumers today —
//   engine/context.forward_turns  (canonical, feeds build_context + the margin window)
//   engine/export_md._group       (the Obsidian export)
//   groupTurns                    (this file — round grouping)
//   isForwardTurn                 (this file — the trajectory line)
// Change the semantics in one and you must change all four.
function isForwardTurn(t) { return !(t.meta && t.meta.is_panelist_raw); }

const TRAJ = { railW: 150, padX: 14, marginGap: 16 };
const VISIBLE_ROWS = 12;  // fixed scale (38.3): ROW_H = rail height / 12; the rail scrolls
const FUTURE_ROWS = 5;    // the future zone below the live edge

// The opacity registers. Brightness encodes context: full-bright touches ONLY forward turns;
// the panel fan sits at the mid register (clearly above the lane guides, clearly below the
// trajectory); the guides are the faintest thing on the rail. Single knobs — no literals.
const OP_LANE = 0.30;    // lane guides
const OP_MID = 0.55;     // fan edges + raw panelist dots
const OP_FULL = 1.0;     // the trajectory and its vertices
const OP_GHOST = 0.25;   // the default-future ghost: what send would do right now
const CURVE_K = 0.45;    // Bézier handle length, as a fraction of the segment's dy
const OP_HOVER_DIM = 0.6; // hover: everything OUTSIDE the hovered round/call drops to 0.6×

const SVGNS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs) {
  const e = document.createElementNS(SVGNS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}

// A segment that peels off one lane and merges into another. The whole trick is VERTICAL
// TANGENCY at both ends — control points share their endpoint's x — so a stroke leaves a lane
// travelling along it and arrives travelling along the next, the way a subway map draws a
// branch. A same-lane segment is the degenerate case: just a straight vertical.
function swervePath(x0, y0, x1, y1) {
  if (x0 === x1 || y0 === y1) return `M ${x0} ${y0} L ${x1} ${y1}`;
  const dy = y1 - y0;
  return `M ${x0} ${y0} C ${x0} ${y0 + CURVE_K * dy}, ${x1} ${y1 - CURVE_K * dy}, ${x1} ${y1}`;
}
function swerve(x0, y0, x1, y1, attrs) {
  return svgEl("path", { d: swervePath(x0, y0, x1, y1), fill: "none", ...attrs });
}
// Model output is untrusted everywhere, including here: text reaches the SVG only as the
// textContent of a <title>, never as markup.
function svgTitle(node, text) {
  const t = document.createElementNS(SVGNS, "title");
  t.textContent = text;
  node.appendChild(t);
  return node;
}

// Which lane a turn belongs to. Human turns (incl. attached files) share the human lane;
// everything else — ai, judge, and promoted margin notes — sits on its speaker's lane.
function laneOf(t) { return t.role === "human" ? "human" : t.speaker; }

// Rounds, indexed by turn position. A research round is a fan-out/fan-in EVENT, not a step in a
// conversation, and the graph draws it as one: head → every surviving panelist → judge.
// Absent panelists produce no turn, so they produce no edge — correct by construction.
function trajRounds(turns) {
  const rounds = new Map();
  turns.forEach((t, i) => {
    const rid = (t.meta || {}).round_id;
    if (!rid) return;
    if (!rounds.has(rid)) rounds.set(rid, { head: -1, judge: -1, panels: [] });
    const r = rounds.get(rid);
    if (t.meta.is_panelist_raw) r.panels.push(i);
    else if (t.role === "human") r.head = i;
    else if (t.role === "judge") r.judge = i;
  });
  return rounds;
}

// LOGICAL rows, not turns. A panel is blind and concurrent: N panelists answering the same
// prompt are one event, not N steps, so every raw turn of a round collapses onto a single shared
// row. A fusion round is three rows — prompt, panel band, judge — whatever the panel's size.
// Grouped by round_id, not by file adjacency: rounds are contiguous under the room lock today,
// and nothing here should depend on that staying true.
function trajRows(turns) {
  const rowOf = new Map();          // turn id → logical row
  const bandOf = new Map();         // round_id → that round's shared panel row
  let row = 0;
  for (const t of turns) {
    const rid = (t.meta || {}).round_id;
    if (isForwardTurn(t) || !rid) { rowOf.set(t.id, row++); continue; }
    if (!bandOf.has(rid)) bandOf.set(rid, row++);
    rowOf.set(t.id, bandOf.get(rid));
  }
  return { rowOf, rows: row };
}

// Model lanes in roster order, then any speaker only the transcript knows about: a departed
// seat, a judge who never sat on a panel, a promoted margin model. The human lane is inserted at
// the MIDPOINT, so a fan spreads both ways and a converse swerve leaves and returns to the
// middle. A speaker appearing mid-session shifts that index on the next redraw — the graph fully
// re-derives anyway, and new speakers are rare; not worth position-pinning machinery.
function trajLanes() {
  const models = [];
  const add = (k) => { if (k && k !== "human" && !models.includes(k)) models.push(k); };
  for (const k of (STATE.room && STATE.room.participants) || []) add(k);
  for (const t of STATE.turns) add(laneOf(t));
  const lanes = models.slice();
  lanes.splice(Math.floor(models.length / 2), 0, "human");
  return lanes;
}

// NEVER call this from render(): that path runs once per animation frame while a
// converse streams (36.4). Drive it off committed-turn changes only — adoptRoom, the
// toggle, a debounced resize, and marginSend's success path.
function drawTrajGraph() {
  const rail = $("#traj-rail");
  const svg = $("#traj-svg");
  if (!svg) return;
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  if (!STATE.ui.trajectory_open || !STATE.room || !STATE.turns.length) {
    svg.setAttribute("height", "0");
    return;
  }
  // FIXED scale (38.3): ROW_H = visible height / 12, however long the transcript — the rail
  // scrolls rather than compressing. Rows stay LOGICAL (a panel is one row). Below the live
  // edge sits a FUTURE_ROWS-deep zone the ghosts (and 38.4's paint) draw into.
  const { rowOf, rows } = trajRows(STATE.turns);
  const railH = Math.max(rail.clientHeight || 0, 120);
  const gap = railH / VISIBLE_ROWS;
  const height = Math.round((rows + FUTURE_ROWS) * gap);
  svg.setAttribute("height", String(height));
  svg.setAttribute("viewBox", `0 0 ${TRAJ.railW} ${height}`);

  const lanes = trajLanes();
  const left = TRAJ.padX;
  const marginX = TRAJ.railW - TRAJ.padX;               // the margin rail's column (37.4)
  const right = Math.max(left, marginX - TRAJ.marginGap);
  const laneX = (key) => {
    const i = Math.max(0, lanes.indexOf(key));
    return lanes.length < 2 ? left : left + (i * (right - left)) / (lanes.length - 1);
  };
  const rowY = (r) => (r + 0.5) * gap;                  // future rows are rowY(rows), rowY(rows+1), …

  // Pin-to-live-edge mirrors the transcript's conditional rule (37.3) exactly: pinned if at
  // the edge before the redraw, position preserved otherwise, a room switch force-pins.
  // _forcePin is read-only here — render() still owns clearing it.
  const atEdge = rail.scrollTop + rail.clientHeight >= rail.scrollHeight - 40;
  drawTrajBody(svg, { gap, height, lanes, laneX, rowY, rowOf, rows, marginX });
  if (_forcePin || atEdge) rail.scrollTop = rail.scrollHeight;
}

// A vertex. The judge carries the round's KIND in its shape — the one cheap signal that tells
// fusion from side-by-side from mapping at a glance, since all three draw the same fan.
// `judge_kind` is absent on pre-Phase-26 judge turns; those read as synthesis, as they do in
// the transcript itself (renderRound defaults the label the same way).
const JUDGE_GLYPH = { synthesis: "circle", divergence: "ring", map: "diamond" };

function trajNode(t, x, y, color, fwd) {
  const common = {
    class: `traj-node traj-dimmable ${fwd ? "traj-vertex" : "traj-panel"}`,
    "data-turn-id": t.id, "data-forward": fwd ? "1" : "0",
    "fill-opacity": fwd ? OP_FULL : OP_MID,
  };
  const rid = (t.meta || {}).round_id;
  if (rid) common["data-round-id"] = rid;      // hover raises the whole round together (38.1)
  if (t.role !== "judge") return svgEl("circle", { cx: x, cy: y, r: 2.5, fill: color, ...common });

  const kind = (t.meta && t.meta.judge_kind) || "synthesis";
  const glyph = JUDGE_GLYPH[kind] || "circle";
  common["data-judge-kind"] = kind;
  if (glyph === "ring") {                                    // side-by-side: exposes, doesn't merge
    return svgEl("circle", { cx: x, cy: y, r: 2.8, fill: "none",
                             stroke: color, "stroke-width": 1.5, "stroke-opacity": OP_FULL, ...common });
  }
  if (glyph === "diamond") {                                 // mapping: a map, not a verdict
    const r = 3.2;
    return svgEl("polygon", { points: `${x},${y - r} ${x + r},${y} ${x},${y + r} ${x - r},${y}`,
                              fill: color, ...common });
  }
  return svgEl("circle", { cx: x, cy: y, r: 2.5, fill: color, ...common });
}

// Paint order, back to front. SVG has no z-index: document order IS depth.
//   margin connectors + brackets → lane guides → fan edges → bright trajectory
//   → dim panel dots → bright vertices → hit geometry (invisible, on top)
// The margin connector crosses the model lanes now that the human lane is centred; putting it
// first is what keeps it behind the lanes and dots it passes under.
function drawTrajBody(svg, geom) {
  const { gap, height, lanes, laneX, rowY, rowOf, rows } = geom;
  const turns = STATE.turns;
  const rounds = trajRounds(turns);
  const yOf = (i) => rowY(rowOf.get(turns[i].id));
  const xy = (i) => ({ x: laneX(laneOf(turns[i])), y: yOf(i) });

  geom.marginHits = [];        // hit geometry the margin pass builds; appended at the TOP later
  geom.marginIds = [];
  drawTrajMargin(svg, geom);   // furthest back: it passes beneath everything it crosses

  // lane guides — thin, solid, dot-coloured; they run on through the future zone
  for (const key of lanes) {
    svg.appendChild(svgTitle(svgEl("line", {
      x1: laneX(key), y1: 0, x2: laneX(key), y2: height, class: "traj-lane traj-dimmable",
      "data-lane": key, stroke: colorOf(key), "stroke-width": 1, "stroke-opacity": OP_LANE,
    }), key));
  }

  // the NOW boundary: everything above happened; everything below is the ghost's territory
  svg.appendChild(svgEl("line", {
    x1: 0, y1: rows * gap, x2: TRAJ.railW, y2: rows * gap, class: "traj-now traj-dimmable",
    stroke: DOT_DEFAULT, "stroke-width": 1, "stroke-opacity": 0.15,
  }));

  // The fan: head → every surviving panelist → judge. ORIGIN colour, as everywhere else (37.7):
  // a stroke carries the voice of whoever just spoke, so the fan-out spreads in the asker's
  // colour and each panelist's answer converges on the judge in its own.
  for (const [rid, r] of rounds.entries()) {
    if (!r.panels.length) continue;              // nothing to fan; the chord below stays
    for (const p of r.panels) {
      if (r.head >= 0) {
        const a = xy(r.head), b = xy(p);
        svg.appendChild(swerve(a.x, a.y, b.x, b.y, {
          class: "traj-fan-out traj-dimmable", stroke: colorOf(laneOf(turns[r.head])),
          "stroke-width": 1, "stroke-opacity": OP_MID, "data-round-id": rid,
          "data-from": turns[r.head].id, "data-to": turns[p].id,
        }));
      }
      if (r.judge >= 0) {
        const a = xy(p), b = xy(r.judge);
        svg.appendChild(swerve(a.x, a.y, b.x, b.y, {
          class: "traj-fan-in traj-dimmable", stroke: colorOf(laneOf(turns[p])),
          "stroke-width": 1, "stroke-opacity": OP_MID, "data-round-id": rid,
          "data-from": turns[p].id, "data-to": turns[r.judge].id,
        }));
      }
    }
  }

  // Is this forward segment the head→judge chord of a round that actually fanned? Then the fan
  // already carries it, and a direct chord would misread as "the conversation skipped to the
  // judge". A round whose panel turns are all absent or rolled away keeps its chord — the
  // trajectory must never simply break.
  const isFannedChord = (a, b) => {
    const rid = (turns[a].meta || {}).round_id;
    if (!rid || (turns[b].meta || {}).round_id !== rid) return false;
    if (turns[a].role !== "human" || turns[b].role !== "judge") return false;
    const r = rounds.get(rid);
    return !!(r && r.panels.length);
  };

  // The bright line traces forward context exactly. Each segment is coloured by the turn it
  // LEAVES (37.7): the line carries the voice of whoever just spoke, and the dot — its own
  // speaker's colour on both rules — is where the colour changes hands. The chord-exception
  // segment of a panel-less round is human-coloured by the same rule, no special case.
  //
  // Yes-and (38.2): the A→B hand-off gets a halo — two voices in one motion. Keyed on the
  // round-head's meta.selection.mode, NEVER on topology: an AI turn followed by a promoted
  // note is also two consecutive non-human forward turns, and must not halo. Pre-Phase-27
  // rooms carry no selection at all and render unmarked, silently.
  let prev = -1, lastSel = null, sinceHuman = 0;
  turns.forEach((t, i) => {
    if (!isForwardTurn(t)) return;
    if (prev >= 0 && !isFannedChord(prev, i)) {
      const a = xy(prev), b = xy(i);
      if (sinceHuman === 1 && lastSel === "yes_and") {
        svg.appendChild(swerve(a.x, a.y, b.x, b.y, {   // appended just before its segment = beneath it
          class: "traj-halo traj-dimmable", stroke: colorOf(laneOf(turns[prev])), "stroke-width": 4,
          "stroke-opacity": 0.15, "data-from": turns[prev].id, "data-to": t.id,
        }));
      }
      svg.appendChild(swerve(a.x, a.y, b.x, b.y, {
        class: "traj-line traj-dimmable", stroke: colorOf(laneOf(turns[prev])), "stroke-width": 1.5,
        "stroke-opacity": OP_FULL, "data-from": turns[prev].id, "data-to": t.id,
      }));
    }
    if (t.role === "human") { lastSel = ((t.meta || {}).selection || {}).mode || null; sinceHuman = 0; }
    else sinceHuman += 1;
    prev = i;
  });

  // nodes, in two passes so the panel band never paints over a vertex. A judge who also sat on
  // the panel gets BOTH on its lane — the fan re-converging, by design.
  const drawNodes = (wantForward) => turns.forEach((t, i) => {
    const fwd = isForwardTurn(t);
    if (fwd !== wantForward) return;
    const p = xy(i);
    const node = trajNode(t, p.x, p.y, colorOf(laneOf(t)), fwd);
    svgTitle(node, `${laneOf(t)}: ${(t.text || "").slice(0, 80)}`);
    svg.appendChild(node);
  });
  drawNodes(false);            // dim panel dots
  drawNodes(true);             // bright vertices

  trajGhost(svg, geom);        // 38.3 — the future zone previews the current composer state

  // One full-width hit rect per LOGICAL row, on top, so a click anywhere on a row lands however
  // thin the node. A panel row spans several turns, so its rect jumps to the round's prompt —
  // the one unambiguous target; the dots stay the precise per-turn targets.
  const rowTarget = new Array(rows);
  turns.forEach((t, i) => {
    const r = rowOf.get(t.id);
    if (rowTarget[r]) return;
    if (isForwardTurn(t)) { rowTarget[r] = t; return; }
    const rnd = rounds.get((t.meta || {}).round_id);
    rowTarget[r] = rnd && rnd.head >= 0 ? turns[rnd.head] : t;
  });
  rowTarget.forEach((t, r) => {
    const attrs = {
      x: 0, y: rowY(r) - gap / 2, width: TRAJ.railW, height: Math.max(gap, 8),
      class: "traj-hit", "data-turn-id": t.id, "data-row": r,
    };
    if ((t.meta || {}).round_id) attrs["data-round-id"] = t.meta.round_id;
    const hit = svgEl("rect", attrs);
    svgTitle(hit, `${laneOf(t)}: ${(t.text || "").slice(0, 80)}`);
    svg.appendChild(hit);
  });

  // …and a per-node hit circle ABOVE the row rects. Without these the row rect would swallow
  // every dot's click, and a panel row — several turns on one row — would lose its per-turn
  // targets entirely. Hit geometry, never a drawn path.
  const hitR = Math.max(3, Math.min(6, gap / 2));
  turns.forEach((t, i) => {
    const p = xy(i);
    const attrs = { cx: p.x, cy: p.y, r: hitR, class: "traj-hit-node", "data-turn-id": t.id };
    if ((t.meta || {}).round_id) attrs["data-round-id"] = t.meta.round_id;
    const hit = svgEl("circle", attrs);
    svgTitle(hit, `${laneOf(t)}: ${(t.text || "").slice(0, 80)}`);
    svg.appendChild(hit);
  });

  // Future-zone hit geometry (38.4): a paint target at every lane × future-row intersection,
  // plus the margin rail's future column — asking sideways is also a next step. None carry
  // data-turn-id, so the click handler's jump branch never sees them. Row +1 is the ghost
  // round-head (38.5A) and is NOT paintable: the grid starts at +2 — the dead clicks are
  // removed structurally, not disabled.
  const paintR = Math.max(5, hitR);
  for (let k = 2; k <= FUTURE_ROWS; k++) {
    for (const key of lanes) {
      const hit = svgEl("circle", { cx: laneX(key), cy: rowY(rows - 1 + k), r: paintR,
                                    class: "traj-hit-future", "data-lane": key, "data-frow": k });
      svgTitle(hit, `paint: ${key} at +${k}`);
      svg.appendChild(hit);
    }
  }
  const marginFut = svgEl("rect", { x: geom.marginX - 6, y: rows * gap, width: 12,
                                    height: height - rows * gap, class: "traj-hit-future",
                                    "data-margin-rail": "1" });
  svgTitle(marginFut, "ask in the margin");
  svg.appendChild(marginFut);

  // margin hit geometry last (drawTrajMargin painted its strokes FIRST — the very back), so
  // hovering a connector or bracket works even though the strokes themselves sit under rows
  for (const m of geom.marginHits) { svg.appendChild(m); }

  trajHoverRules(svg, rounds, geom.marginIds);
}

// One generated <style> per redraw: a dim + raise rule pair per round and per margin call.
// Hover then only flips ONE attribute on the SVG root — no per-element style mutation, no
// redraw, no element creation. (CSS alone cannot match "elements whose data-round-id equals
// the root's data-hover-round", so the identity is compiled into rules at draw time.)
function trajHoverRules(svg, rounds, marginIds) {
  const rules = [];
  for (const rid of rounds.keys()) {
    const r = CSS.escape(rid);
    rules.push(`#traj-svg[data-hover-round="${r}"] .traj-dimmable:not([data-round-id="${r}"]) { opacity: ${OP_HOVER_DIM}; }`);
    rules.push(`#traj-svg[data-hover-round="${r}"] [data-round-id="${r}"] { stroke-opacity: 1; fill-opacity: 1; }`);
  }
  for (const mid of marginIds || []) {
    const m = CSS.escape(mid);
    rules.push(`#traj-svg[data-hover-margin="${m}"] .traj-dimmable:not([data-margin-id="${m}"]) { opacity: ${OP_HOVER_DIM}; }`);
    rules.push(`#traj-svg[data-hover-margin="${m}"] [data-margin-id="${m}"] { stroke-opacity: 1; fill-opacity: 1; }`);
  }
  if (!rules.length) return;
  const style = document.createElementNS(SVGNS, "style");
  style.textContent = rules.join("\n");
  svg.appendChild(style);
}

// The engine resolves an "auto" addressee to the last AI speaker (modes.py:356-359, via
// transcript.last_ai_speaker), falling back to the room's first participant. The ghost mirrors
// that resolution so the default future is shown honestly, never as a blank.
function lastAiSpeaker() {
  for (let i = STATE.turns.length - 1; i >= 0; i--) {
    const t = STATE.turns[i];
    if (t.role === "ai" || t.role === "judge") return t.speaker;
  }
  return null;
}

// The default-future ghost (38.3): with nothing painted, the future zone shows what SEND would
// do right now — the compiled selection, rendered from the same controls buildSelection reads.
// Hollow rings for the would-be vertices, solid strokes at the ghost register; origin-coloured
// like everything else (the first hop is the prompt you are about to speak: human-voiced).
//
// 38.4 makes the future zone an EDITOR too. The dots are a VIEW over the composer's selection
// state, compiled in both directions: a pattern that compiles is written INTO the composer
// controls and the dots re-derive from state (STATE.paintDots stays null — state is the only
// truth); a pattern that does not compile renders from STATE.paintDots — the dots, plus every
// stroke whose endpoints both exist (38.5B) — and the composer keeps the last valid state.
//
// 38.5A makes the round-head explicit: future row +1 always carries a ghost human ring (every
// round begins with a human turn) joined to the last real vertex by the now-connection, and
// the grammar's offsets count from it — target row +2, judge +3, yes-and discriminator +4.

// One ghost vertex. Plain = a hollow ring. A judge wears its round-kind GLYPH (the 37.5B
// language doubling as the paint cycle's read-back): filled = synthesis, double ring =
// divergence, diamond = map. A yes-and second dot stays plain — the glyph is precisely what
// discriminates "B judges A" from "B builds on A".
function ghostNode(svg, geom, lane, frow, kind) {
  const x = geom.laneX(lane), y = geom.rowY(geom.rows - 1 + frow);
  const c = colorOf(lane);
  const base = { "data-lane": lane, "data-frow": frow,
                 class: `traj-ghost traj-ghost-node traj-dimmable${kind ? " traj-ghost-judge" : ""}` };
  if (kind) base["data-kind"] = kind;
  if (kind === "synthesis") {
    svg.appendChild(svgEl("circle", { cx: x, cy: y, r: 3, fill: c, "fill-opacity": OP_GHOST, ...base }));
  } else if (kind === "divergence") {   // two voices left standing side by side
    svg.appendChild(svgEl("circle", { cx: x, cy: y, r: 3.8, fill: "none", stroke: c,
                                      "stroke-width": 1.2, "stroke-opacity": OP_GHOST, ...base }));
    svg.appendChild(svgEl("circle", { cx: x, cy: y, r: 1.6, fill: "none", stroke: c,
                                      "stroke-width": 1.2, "stroke-opacity": OP_GHOST,
                                      class: "traj-ghost traj-ghost-pip traj-dimmable" }));
  } else if (kind === "map") {
    const r = 3.4;
    svg.appendChild(svgEl("polygon", { points: `${x},${y - r} ${x + r},${y} ${x},${y + r} ${x - r},${y}`,
                                       fill: "none", stroke: c, "stroke-width": 1.5,
                                       "stroke-opacity": OP_GHOST, ...base }));
  } else {
    svg.appendChild(svgEl("circle", { cx: x, cy: y, r: 2.8, fill: "none", stroke: c,
                                      "stroke-width": 1.5, "stroke-opacity": OP_GHOST, ...base }));
  }
}

function trajGhost(svg, geom) {
  const { lanes, laneX, rowY, rowOf, rows } = geom;
  let last = -1;
  STATE.turns.forEach((t, i) => { if (isForwardTurn(t)) last = i; });
  if (last < 0) return;
  const t0 = STATE.turns[last];
  const x0 = laneX(laneOf(t0)), y0 = rowY(rowOf.get(t0.id));
  const fy = (k) => rowY(rows - 1 + k);                 // future row k = 1..FUTURE_ROWS

  const edge = (xa, ya, xb, yb, color) => svg.appendChild(swerve(xa, ya, xb, yb, {
    class: "traj-ghost traj-ghost-edge traj-dimmable", stroke: color,
    "stroke-width": 1, "stroke-opacity": OP_GHOST,
  }));

  // The ghost ROUND-HEAD (38.5A): every round begins with a human turn — the engine has no
  // other path — so future row +1 always says so, and the now-connection joins the last real
  // vertex to it in the LAST FORWARD SPEAKER's colour (the origin rule: judge-coloured after
  // a round, model-coloured after converse). The bright line doesn't just stop; the present
  // moment is continuous. The head is NOT paintable — the hit grid starts at +2.
  const hx = laneX("human"), hy = fy(1);
  svg.appendChild(swerve(x0, y0, hx, hy, {
    class: "traj-ghost traj-ghost-edge traj-ghost-now traj-dimmable",
    stroke: colorOf(laneOf(t0)), "stroke-width": 1, "stroke-opacity": OP_GHOST,
  }));
  ghostNode(svg, geom, "human", 1, null);

  // A non-compiling paint draws every stroke whose endpoints BOTH exist (38.5B): the shape
  // connects as it is built, at the same register, and full validity is visually just "the
  // shape completed" — the state write and the chip flip stay the only signal that send
  // behaviour changed. This branch READS paint state; it never writes selection state. The
  // one deliberately bare state is a judge with no panel — a fan-in has no sources, and a
  // head→judge stroke would falsely read as converse. The +3 dot follows the discriminator
  // exactly as compile does: a human dot at +4 makes it a plain yes-and B (B→human stroke);
  // its absence makes it a judge (glyph + fan-in).
  if (STATE.paintDots) {
    const dots = STATE.paintDots.filter((d) => lanes.includes(d.lane));
    const disc = dots.some((d) => d.frow === 4 && d.lane === "human");
    const targets = dots.filter((d) => d.frow === 2 && d.lane !== "human");
    const thirds = dots.filter((d) => d.frow === 3 && d.lane !== "human");
    for (const t of targets) edge(hx, hy, laneX(t.lane), fy(2), colorOf("human"));
    for (const j of thirds) {
      for (const t of targets) edge(laneX(t.lane), fy(2), laneX(j.lane), fy(3), colorOf(t.lane));
      if (disc) edge(laneX(j.lane), fy(3), laneX("human"), fy(4), colorOf(j.lane));
    }
    for (const d of dots) {
      const asJudge = d.frow === 3 && d.lane !== "human" && !disc;
      ghostNode(svg, geom, d.lane, d.frow, asJudge ? d.kind || "synthesis" : null);
    }
    return;
  }

  const mode = currentMode();
  if (mode === "converse") {
    const target = $("#addressee").value || lastAiSpeaker() || ((STATE.room.participants || [])[0]);
    if (!target || !lanes.includes(target)) return;
    edge(hx, hy, laneX(target), fy(2), colorOf("human"));
    ghostNode(svg, geom, target, 2, null);
    return;
  }
  if (mode === "fusion" || mode === "mapping" || mode === "side_by_side") {
    const members = (mode === "side_by_side" ? pickedSeats() : pickedPanel()).filter((m) => lanes.includes(m));
    const judge = $(mode === "side_by_side" ? "#sxs-judge" : "#judge-pick").value;
    for (const m of members) {
      edge(hx, hy, laneX(m), fy(2), colorOf("human"));
      ghostNode(svg, geom, m, 2, null);
      if (judge && lanes.includes(judge)) edge(laneX(m), fy(2), laneX(judge), fy(3), colorOf(m));
    }
    if (members.length && judge && lanes.includes(judge)) {
      ghostNode(svg, geom, judge, 3,
                mode === "side_by_side" ? "divergence" : mode === "mapping" ? "map" : "synthesis");
    }
    return;
  }
  if (mode === "yes_and") {
    const a = $("#ya-a").value, b = $("#ya-b").value;
    if (!a || !b || !lanes.includes(a) || !lanes.includes(b)) return;
    edge(hx, hy, laneX(a), fy(2), colorOf("human")); ghostNode(svg, geom, a, 2, null);
    edge(laneX(a), fy(2), laneX(b), fy(3), colorOf(a)); ghostNode(svg, geom, b, 3, null);
    edge(laneX(b), fy(3), laneX("human"), fy(4), colorOf(b)); ghostNode(svg, geom, "human", 4, null);
  }
}

// ---- paint-to-compose (38.4; offsets from the explicit round-head since 38.5) -------------
// The grammar. Future row +1 is the ghost ROUND-HEAD — never a dot, never a hit. Row +2 = who
// answers. A single KINDED dot at +3 is the judge, and its glyph IS the mode: synthesis →
// fusion, divergence → side-by-side (which demands exactly two seats), map → mapping. A human
// dot at +4 is the yes-and discriminator: with it, +2 is A and +3 is B building on A; without
// it, the same two dots read as a one-panelist round judged by B. Everything else — human dots
// off +4, model dots at +4, anything past +4, a judge with no panel, several dots at +3, a
// lane the roster can't express — does not compile. Returns the compiled selection,
// {noop: true} for an empty pattern (= the composer as it stands), or null.
function compilePaint(dots) {
  if (!dots.length) return { noop: true };
  const roster = roomRoster();
  const r1 = dots.filter((d) => d.frow === 2), r2 = dots.filter((d) => d.frow === 3);
  const r3 = dots.filter((d) => d.frow === 4);
  if (dots.some((d) => d.frow > 4 || d.frow < 2)) return null;
  if ([...r1, ...r2].some((d) => d.lane === "human" || !roster.includes(d.lane))) return null;
  if (r3.some((d) => d.lane !== "human") || r3.length > 1) return null;
  if (r3.length) {                                       // the human dot: this is a yes-and
    if (r1.length !== 1 || r2.length !== 1 || r1[0].lane === r2[0].lane) return null;
    return { mode: "yes_and", a: r1[0].lane, b: r2[0].lane };
  }
  if (r2.length === 1 && r1.length) {                    // a judged round; the glyph is the mode
    const kind = r2[0].kind || "synthesis";
    if (kind === "divergence") {
      if (r1.length !== 2) return null;                  // side-by-side is exactly two seats
      return { mode: "side_by_side", seats: r1.map((d) => d.lane), judge: r2[0].lane };
    }
    return { mode: kind === "map" ? "mapping" : "fusion",
             panel: r1.map((d) => d.lane), judge: r2[0].lane };
  }
  if (!r2.length && r1.length === 1) return { mode: "converse", target: r1[0].lane };
  return null;
}

// The dots the current composer state DISPLAYS — the derived editor view, never stored.
// Mirrors trajGhost's branches control-for-control, so a toggle always works against exactly
// what is on screen.
function paintDerived() {
  const mode = currentMode();
  if (mode === "converse") {
    const target = $("#addressee").value || lastAiSpeaker() || roomRoster()[0];
    return target ? [{ lane: target, frow: 2 }] : [];
  }
  if (mode === "fusion" || mode === "mapping" || mode === "side_by_side") {
    const dots = (mode === "side_by_side" ? pickedSeats() : pickedPanel())
      .map((m) => ({ lane: m, frow: 2 }));
    const judge = $(mode === "side_by_side" ? "#sxs-judge" : "#judge-pick").value;
    if (dots.length && judge) {
      dots.push({ lane: judge, frow: 3,
                  kind: mode === "side_by_side" ? "divergence" : mode === "mapping" ? "map" : "synthesis" });
    }
    return dots;
  }
  const a = $("#ya-a").value, b = $("#ya-b").value;      // yes_and
  return a && b ? [{ lane: a, frow: 2 }, { lane: b, frow: 3 }, { lane: "human", frow: 4 }] : [];
}

// A compiled paint writes THE SAME controls the picker edits, then goes through the picker's
// own change pathway (the #mode dispatch → syncModeUI, chip, disclosure, redraw). Nothing here
// is a second store: setting the controls programmatically is equivalent to clicking them
// (recon 38.0), and the per-room stash captures them on room exit exactly as if the picker had
// been used.
function applyPaint(sel) {
  if (sel.mode === "converse") {
    $("#addressee").value = sel.target;
  } else if (sel.mode === "yes_and") {
    $("#ya-a").value = sel.a; $("#ya-b").value = sel.b;
  } else if (sel.mode === "side_by_side") {
    document.querySelectorAll("#sxs-pick input").forEach((cb) => { cb.checked = sel.seats.includes(cb.value); });
    $("#sxs-judge").value = sel.judge;
  } else {
    document.querySelectorAll("#panel-pick input").forEach((cb) => { cb.checked = sel.panel.includes(cb.value); });
    $("#judge-pick").value = sel.judge;
  }
  $("#mode").value = sel.mode;
  $("#mode").dispatchEvent(new Event("change"));
}

// One paint gesture. A dot that currently wears a judge glyph cycles it — filled → ring →
// diamond → off, i.e. synthesis → divergence → map → removed; every other dot simply toggles.
// Then the WHOLE pattern recompiles: into the composer if it means something, into a bare
// overlay if it doesn't.
function paintClick(lane, frow) {
  const cur = STATE.paintDots || paintDerived();
  const hit = cur.find((d) => d.lane === lane && d.frow === frow);
  let next;
  if (!hit) {
    next = [...cur, { lane, frow, ...(frow === 3 && lane !== "human" ? { kind: "synthesis" } : {}) }];
  } else if (hit.kind) {
    const CYCLE = { synthesis: "divergence", divergence: "map", map: null };
    const nk = CYCLE[hit.kind];
    next = nk ? cur.map((d) => (d === hit ? { ...d, kind: nk } : d)) : cur.filter((d) => d !== hit);
  } else {
    next = cur.filter((d) => d !== hit);
  }
  const sel = compilePaint(next);
  if (sel && !sel.noop) { STATE.paintDots = null; applyPaint(sel); }   // state took over; dots re-derive
  else if (sel) { STATE.paintDots = null; drawTrajGraph(); }           // empty → the composer's own default
  else { STATE.paintDots = next; drawTrajGraph(); }                    // bare dots; last valid state stands
}

// The margin rail: the side-channel made visible. A margin question hangs a connector off
// the main row it was asked beside, and brackets the forward turns it actually read.
//
// `meta.window_ids` (Phase 37.1) is the exact span, captured from the same snapshot the
// margin's background was built from. Turns can be rolled back out from under those ids, so
// every id is resolved against the CURRENT transcript and missing ones are simply dropped.
//
// Legacy margin turns predate window_ids and carry only the policy string. For those the row
// is correlated by `ts` — which is second-granular and can over-include a turn appended by a
// concurrent round. Good enough to point at; NOT good enough to bracket. So: no bracket.
const BRACKET_CAP = 3;   // px the bracket overshoots its end rows, so last_1 still draws

function drawTrajMargin(svg, geom) {
  const { laneX, rowY, rowOf, marginX, height } = geom;
  const margins = STATE.marginTurns || [];
  const promoted = STATE.turns.filter((t) => t.meta && (t.meta.from_margin || t.meta.from_code));
  if (!margins.length && !promoted.length) return;

  svg.appendChild(svgEl("line", {
    x1: marginX, y1: 0, x2: marginX, y2: height, class: "traj-margin-rail",
    stroke: DOT_DEFAULT, "stroke-width": 1, "stroke-opacity": 0.45,
  }));

  // window_ids only ever name forward turns, and every forward turn still owns its own logical
  // row — so the row model change cannot move an anchor or a bracket.
  const forward = STATE.turns.filter(isForwardTurn);
  const humanX = laneX("human");

  // A connector is an indicator, not a trajectory: straight, never curved. It spans the full
  // width from its origin lane to the rail. Terminal dot in the CONNECTOR's colour, not the
  // lane's — the side-question came from you, but it isn't a turn in the conversation.
  const connector = (y, cls, x0, mid) => svgEl("line", {
    x1: marginX, y1: y, x2: x0, y2: y, class: `${cls} traj-dimmable`, "data-margin-id": mid,
    stroke: DOT_DEFAULT, "stroke-width": 1, "stroke-opacity": 0.4,
  });
  const originDot = (y, mid) => svgEl("circle", {
    cx: humanX, cy: y, r: 2.5, fill: DOT_DEFAULT, "fill-opacity": 0.4,
    class: "traj-margin-dot traj-dimmable", "data-margin-id": mid,
  });
  // The strokes above paint at the very BACK; a transparent hit RECT per call, appended at the
  // hit stage, is what makes them hoverable (a zero-height line is invisible to hit testing).
  // It carries the anchor row's turn id too, so clicking a connector jumps to its row.
  const marginHit = (x, y, w, h, mid, turnId, label) => {
    const r = svgEl("rect", { x, y, width: Math.max(w, 9), height: Math.max(h, 9),
                              class: "traj-hit-margin", "data-margin-id": mid, "data-turn-id": turnId });
    geom.marginHits.push(svgTitle(r, label));
    if (!geom.marginIds.includes(mid)) geom.marginIds.push(mid);
  };

  for (const q of margins) {
    if (q.role !== "human") continue;            // one connector per QUESTION, not per answer
    const meta = q.meta || {};
    const ids = meta.window_ids;

    if (Array.isArray(ids)) {
      const rows = ids.map((id) => rowOf.get(id)).filter((r) => r !== undefined);
      if (!rows.length) continue;                // every windowed turn was rolled back — draw nothing
      const lo = Math.min(...rows), hi = Math.max(...rows);
      const label = `margin (${meta.window || "window"}): ${(q.text || "").slice(0, 80)}`;
      svg.appendChild(svgTitle(connector(rowY(hi), "traj-connector", humanX, q.id), label));
      svg.appendChild(originDot(rowY(hi), q.id));
      // BRACKET_CAP encloses the windowed rows rather than ending on their centres — and it is
      // what makes a single-row window (last_1) a visible tick instead of a zero-length line.
      svg.appendChild(svgTitle(svgEl("line", {
        x1: marginX, y1: rowY(lo) - BRACKET_CAP, x2: marginX, y2: rowY(hi) + BRACKET_CAP,
        class: "traj-bracket traj-dimmable", "data-margin-id": q.id,
        stroke: DOT_DEFAULT, "stroke-width": 2, "stroke-opacity": 0.6,
      }), label));
      const anchor = STATE.turns.find((t) => rowOf.get(t.id) === hi);   // the connector's row
      marginHit(humanX, rowY(hi) - 4.5, marginX - humanX, 9, q.id, anchor ? anchor.id : "", label);
      marginHit(marginX - 4.5, rowY(lo) - BRACKET_CAP, 9, rowY(hi) - rowY(lo) + 2 * BRACKET_CAP,
                q.id, anchor ? anchor.id : "", label);            // the bracket is hoverable too
      continue;
    }

    // legacy: best-effort ts correlation, clamped into range. Never throws, never brackets.
    const seen = forward.filter((t) => (t.ts || "") <= (q.ts || "")).pop();
    if (!seen) continue;
    const anchor = rowOf.get(seen.id);
    const label = `margin (${meta.window || "window"}, approximate): ${(q.text || "").slice(0, 80)}`;
    svg.appendChild(svgTitle(connector(rowY(anchor), "traj-connector traj-approx", humanX, q.id), label));
    svg.appendChild(originDot(rowY(anchor), q.id));
    marginHit(humanX, rowY(anchor) - 4.5, marginX - humanX, 9, q.id, seen.id, label);
  }

  // The one deliberate margin → main backflow. It already terminates on a bright forward vertex
  // (the promoted note's own), so it gets no origin dot — that would double-mark the row.
  for (const t of promoted) {
    const r = rowOf.get(t.id);
    if (r === undefined) continue;
    const fromCode = t.meta && t.meta.from_code;
    const label = fromCode
      ? `from code seat: ${(t.text || "").slice(0, 80)}`
      : `promoted from margin: ${(t.text || "").slice(0, 80)}`;
    const x0 = laneX(laneOf(t));
    const cls = fromCode ? "traj-promoted traj-from-code" : "traj-promoted";
    svg.appendChild(svgTitle(connector(rowY(r), cls, x0, t.id), label));
    marginHit(x0, rowY(r) - 4.5, marginX - x0, 9, t.id, t.id, label);
  }
}

// Scroll the transcript to a turn and flash it. Instant, not smooth: no smooth scrolling
// exists anywhere in the app and a graph click shouldn't be the first.
function jumpToTurn(id) {
  const node = document.querySelector(`#stream [data-turn-id="${CSS.escape(id)}"]`);
  if (!node) return;                                   // rolled back, or not rendered
  node.scrollIntoView({ block: "center" });
  node.classList.remove("jump-flash");
  void node.offsetWidth;                               // restart the animation on a repeat click
  node.classList.add("jump-flash");
  setTimeout(() => node.classList.remove("jump-flash"), 1200);
}

$("#traj-svg").addEventListener("click", (e) => {
  // future zone first (38.4): paint a dot, or open the margin from its rail's future column.
  // Past rows keep click-to-jump untouched — future hits never carry data-turn-id.
  const fut = e.target.closest(".traj-hit-future");
  if (fut) {
    if (fut.hasAttribute("data-margin-rail")) { openMargin(); $("#margin-input").focus(); }
    else paintClick(fut.getAttribute("data-lane"), Number(fut.getAttribute("data-frow")));
    return;
  }
  const hit = e.target.closest("[data-turn-id]");
  if (hit) jumpToTurn(hit.getAttribute("data-turn-id"));
});

// Hover (38.1): resolve the hovered HIT element's round/call and flip one attribute on the SVG
// root; the draw-time stylesheet does the rest. pointerover fires per element entered, so a
// non-round hit (a converse row, the future zone) clears the highlight on its own.
$("#traj-svg").addEventListener("pointerover", (e) => {
  const svg = $("#traj-svg");
  const hit = e.target.closest(".traj-hit, .traj-hit-node, .traj-hit-margin");
  const rid = hit && hit.getAttribute("data-round-id");
  const mid = hit && hit.getAttribute("data-margin-id");
  if (rid) svg.setAttribute("data-hover-round", rid); else svg.removeAttribute("data-hover-round");
  if (mid) svg.setAttribute("data-hover-margin", mid); else svg.removeAttribute("data-hover-margin");
});
$("#traj-svg").addEventListener("pointerleave", () => {
  $("#traj-svg").removeAttribute("data-hover-round");
  $("#traj-svg").removeAttribute("data-hover-margin");
});

// ===== composer pickers (scoped to the ACTIVE ROOM's roster) =================
function roomRoster() { return (STATE.room && STATE.room.participants) || []; }
function providerOf(key) { return STATE.participants.find((p) => p.name === key); }

function renderAddressee() {
  const sel = $("#addressee");
  const cur = sel.value;                                    // preserve the live pick across the rebuild —
  const opts = roomRoster().map((k) => `<option value="${k}">@${k}</option>`).join("");
  sel.innerHTML = '<option value="">auto (last AI)</option>' + opts;
  // …so an in-room re-adopt (send result, poll, rollback, promote, settings-save) doesn't silently
  // revert a chosen addressee to auto (Phase 35.2). restoreRoomComposer stays authoritative on switch.
  if (cur && [...sel.options].some((o) => o.value === cur)) sel.value = cur;   // else falls back to auto
}

function renderPanelPick() {
  const box = $("#panel-pick"); box.innerHTML = "";
  const roster = roomRoster();
  if (!roster.length) { box.append(document.createTextNode("· no models in this room — set them in “models”")); return; }
  box.append(document.createTextNode("· panel:"));
  for (const k of roster) {
    const p = providerOf(k);
    const lab = el("label", "pickitem");
    const cb = el("input"); cb.type = "checkbox"; cb.value = k; cb.checked = true;
    lab.append(cb, dot(p ? p.color : DOT_DEFAULT), document.createTextNode(k));
    box.append(lab);
  }
}
function pickedPanel() {
  return [...document.querySelectorAll("#panel-pick input:checked")].map((i) => i.value);
}

function renderJudgePick() {
  const sel = $("#judge-pick");
  const roster = roomRoster();
  const judge = STATE.room && STATE.room.judge;
  // Forced decision: if the room has no judge, show a disabled "select…" so a
  // research round can't be fired without one.
  let html = "";
  if (!judge) html += `<option value="" disabled selected>select…</option>`;
  html += roster.map((k) => `<option value="${k}"${k === judge ? " selected" : ""}>${k}</option>`).join("");
  sel.innerHTML = html || `<option value="" disabled selected>select…</option>`;
}

// side-by-side: a two-seat picker (checkboxes from the room roster) + its own judge.
function renderSxsPick() {
  const box = $("#sxs-pick"); if (!box) return;
  box.innerHTML = "";
  const roster = roomRoster();
  if (!roster.length) { box.append(document.createTextNode("· no models in this room — set them in “models”")); return; }
  box.append(document.createTextNode("· two:"));
  for (const k of roster) {
    const p = providerOf(k);
    const lab = el("label", "pickitem");
    const cb = el("input"); cb.type = "checkbox"; cb.value = k;
    lab.append(cb, dot(p ? p.color : DOT_DEFAULT), document.createTextNode(k));
    box.append(lab);
  }
}
function pickedSeats() { return [...document.querySelectorAll("#sxs-pick input:checked")].map((i) => i.value); }

function renderSxsJudge() {
  const sel = $("#sxs-judge"); if (!sel) return;
  const roster = roomRoster();
  const judge = STATE.room && STATE.room.judge;
  let html = "";
  if (!judge) html += `<option value="" disabled selected>select…</option>`;
  html += roster.map((k) => `<option value="${k}"${k === judge ? " selected" : ""}>${k}</option>`).join("");
  sel.innerHTML = html || `<option value="" disabled selected>select…</option>`;
}

// yes-and: an ordered pair (A → B) from the room roster.
function renderYesAnd() {
  const roster = roomRoster();
  for (const id of ["#ya-a", "#ya-b"]) {
    const sel = $(id); if (!sel) continue;
    const cur = sel.value;
    sel.innerHTML = roster.length
      ? roster.map((k) => `<option value="${k}">${k}</option>`).join("")
      : `<option value="" disabled selected>no models</option>`;
    if (cur && roster.includes(cur)) sel.value = cur;
  }
  // sensible default: A = first, B = second (distinct) when nothing chosen yet
  if (roster.length >= 2 && $("#ya-a") && $("#ya-a").value === $("#ya-b").value) $("#ya-b").value = roster[1];
}

function renderComposerPickers() {
  renderAddressee(); renderPanelPick(); renderJudgePick(); renderSxsPick(); renderSxsJudge(); renderYesAnd();
}

// ===== token / context indicator =============================================
function fmtTokens(n) {
  if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M";
  if (n >= 1000) return Math.round(n / 1000) + "k";
  return "" + n;
}
function fmtCost(n) {
  if (!n) return "$0.00";
  return "$" + (n < 0.01 ? n.toFixed(4) : n.toFixed(2));
}
// is this seat billed via OpenRouter (has a real usage.cost) vs free/subscription
// (proxy-Grok, cli — off-OR, no cost field)?
function isORSeat(k) { return (((providerOf(k) || {}).base_url) || "").includes("openrouter.ai"); }

// per-model spend share over the room's stored usage (Grok estimate-only → ~). Cost
// (OpenRouter's authoritative usage.cost) is summed alongside tokens; off-OR seats
// carry no cost field (free / subscription).
function modelPercents() {
  const per = {}, cost = {}; let total = 0, totalCost = 0, approx = false, anyCost = false;
  for (const t of STATE.turns) {
    const u = t.meta && t.meta.usage;
    if (!u || t.role === "human") continue;        // model turns only carry usage
    const tok = (u.input || 0) + (u.output || 0);
    per[t.speaker] = (per[t.speaker] || 0) + tok; total += tok;
    if (typeof u.cost === "number") { cost[t.speaker] = (cost[t.speaker] || 0) + u.cost; totalCost += u.cost; anyCost = true; }
    if (!u.exact) approx = true;
  }
  return { per, cost, total, totalCost, approx, anyCost };
}

// forward-context token estimate (~chars/4) — the turn.text that WOULD be sent next:
// the synthesis-only forward view (raw panel answers excluded, like build_context).
// Shared across models pre-compaction; each ring divides it by that model's own window.
function forwardTokenEstimate() {
  let chars = 0;
  for (const t of STATE.turns) {
    if (t.meta && t.meta.is_panelist_raw) continue;
    chars += (t.text || "").length;
  }
  return Math.ceil(chars / 4);
}

// ===== model-square bar (per-panelist tiles + an extensible hover popover) ====
// Each active panelist gets a square (dot + abbreviated spend). Hover/click opens a
// popover whose CONTENTS come from a declarative cell list (MODEL_CELLS) — a new
// field is a one-line append, not a re-layout. Session total sits at the bar's end.

// Declarative popover cells. Each: build(key, info) → element | null (null skips it).
// Declarative STAT rows (one line each: label left, value right). Append one entry
// to add a field (e.g. cost, latency) — the extensibility lives here, not a placeholder.
const STAT_CELLS = [
  { label: "Tokens",        val: (k, i) => `${i.approx ? "~" : ""}${fmtTokens(i.raw)}` },
  { label: "Share of room", val: (k, i) => `${i.approx ? "~" : ""}${i.pct}%` },
  { label: "Cost",          val: (k, i) => isORSeat(k) ? fmtCost(i.cost) : "free" },
  { label: "Context",       val: (k, i) => { const w = effectiveWindow(k); return w ? `${fmtTokens(i.ctxUsed)} / ${fmtTokens(w)}` : "—"; },
                            note: (k) => windowDot(k) },
];

function mpRow(label, value, extra) {
  const c = el("div", "mp-row");
  const l = el("span", "mp-rlabel"); l.textContent = label;
  const v = el("span", "mp-rval"); v.textContent = value;
  if (extra) v.append(extra);                          // e.g. the Phase-24 window dot
  c.append(l, v); return c;
}

// a small inline bolt (no icon-font dependency; themes via currentColor)
function boltIcon() {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("class", "mp-bolt");
  svg.setAttribute("width", "12"); svg.setAttribute("height", "12");
  svg.setAttribute("fill", "currentColor");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", "M13 2 4 14h6l-1 8 9-12h-6l1-8z");
  svg.append(path); return svg;
}

// served/configured model name with the provider/ prefix stripped (claude-opus-4.8).
function modelLabel(k) {
  const m = (providerOf(k) || {}).model || k;
  return m.includes("/") ? m.split("/").pop() : m;
}
// subtitle derived from the row's base_url.
function modelVia(k) {
  const b = (providerOf(k) || {}).base_url || "";
  if (b.includes("openrouter.ai")) return "via OpenRouter";
  if (/127\.0\.0\.1|localhost/.test(b)) return "via Hermes proxy";
  return b ? "direct" : "";
}

function popoverHeader(k) {
  const p = providerOf(k);
  const head = el("div", "mp-headrow");
  head.append(dot(p ? p.color : DOT_DEFAULT));
  const box = el("div", "mp-headbox");
  const name = el("div", "mp-head"); name.textContent = modelLabel(k); box.append(name);
  const via = modelVia(k);
  if (via) { const s = el("div", "mp-sub"); s.textContent = via; box.append(s); }
  head.append(box); return head;
}

// effort selector — data-driven from the provider's effort_options (ASCENDING);
// returns null (omitted) when the model exposes none (proxy-Grok / direct rows).
function effortSection(k) {
  const p = providerOf(k) || {};
  const opts = p.effort_options;
  if (!opts || !opts.length) return null;
  // The dial is INERT when the model's reasoning toggle is off — the effort is never sent
  // (RR Loom 4 bug). Show it greyed + a note so it can't silently mislead.
  const off = !p.reasoning;
  const cur = (STATE.room && STATE.room.reasoning_effort && STATE.room.reasoning_effort[k]) || opts[opts.length - 1];
  const c = el("div", "mp-effort" + (off ? " off" : ""));
  const l = el("div", "mp-label"); l.append(boltIcon(), document.createTextNode(" reasoning effort")); c.append(l);
  const seg = el("div", "mp-seg");
  for (const o of opts) {                              // already ascending: left = less
    const b = el("button", o === cur ? "sel" : "");
    b.textContent = o;
    if (off) b.disabled = true;
    else b.addEventListener("click", () => setRoomEffort(k, o));
    seg.append(b);
  }
  c.append(seg);
  if (off) { const n = el("div", "mp-note"); n.textContent = 'reasoning off — enable “show reasoning” in Settings → Providers'; c.append(n); }
  return c;
}

async function setRoomEffort(k, effort) {
  if (!STATE.room) return;
  const map = { ...(STATE.room.reasoning_effort || {}), [k]: effort };
  STATE.room.reasoning_effort = map;                                   // effective next turn
  if (_popoverFor) showModelPopover(_popoverFor.k, _popoverFor.rect);  // re-highlight in place
  try { await api(`/rooms/${STATE.room.id}`, "PUT", { reasoning_effort: map }); } catch (e) { /* non-fatal */ }
}

function squareInfo(k, spend) {
  const raw = spend.per[k] || 0;
  return { raw, pct: spend.total ? Math.round(raw / spend.total * 100) : 0, approx: spend.approx,
           cost: spend.cost[k] || 0, ctxUsed: forwardTokenEstimate() };
}

// a per-model context-fill ring: the speaker dot centred in a coloured ring whose
// arc = forward-context tokens ÷ THIS model's window, ramping green→amber→red. The
// ring is the trigger surface for Wave-5 per-model compaction (it reads the same
// window data). No window known → just the bare dot.
function ringClass(r) { return r < 0.6 ? "ok" : r < 0.85 ? "warn" : "crit"; }
function contextRing(ratio) {
  const ns = "http://www.w3.org/2000/svg";
  const r = 8, circ = 2 * Math.PI * r;
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", "ctx-ring"); svg.setAttribute("viewBox", "0 0 20 20");
  svg.setAttribute("width", "18"); svg.setAttribute("height", "18");
  const mk = (cls) => { const c = document.createElementNS(ns, "circle");
    c.setAttribute("cx", "10"); c.setAttribute("cy", "10"); c.setAttribute("r", "" + r);
    c.setAttribute("fill", "none"); c.setAttribute("class", cls); return c; };
  const bg = mk("ctx-ring-bg");
  const fg = mk("ctx-ring-fg " + ringClass(ratio));
  fg.setAttribute("stroke-dasharray", "" + circ);
  fg.setAttribute("stroke-dashoffset", "" + (circ * (1 - Math.max(0, Math.min(1, ratio)))));
  fg.setAttribute("transform", "rotate(-90 10 10)");
  svg.append(bg, fg); return svg;
}
// the window the ring calibrates to: the EFFECTIVE routed window (Phase 24) when
// resolved from OR, else the configured/headline window.
function effectiveWindow(k) {
  const p = providerOf(k) || {};
  return p.effective_window || p.context_window || 0;
}
function tileGlyph(k, ctxUsed) {
  const p = providerOf(k);
  const color = p ? p.color : DOT_DEFAULT;
  const win = effectiveWindow(k);
  const wrap = el("span", "tile-glyph");
  if (win) wrap.append(contextRing(ctxUsed / win));   // ring vs THIS model's effective window
  wrap.append(dot(color));                             // dot centred over the ring
  return wrap;
}

// a small red dot beside the popover's Context cell when the routed window is reduced
// from the headline, or the headline changed since seeding (Phase 24). null otherwise.
function windowDot(k) {
  const p = providerOf(k) || {};
  if (!p.window_reduced && !p.window_changed) return null;
  const d = el("span", "win-dot");
  if (p.window_changed)
    d.title = `headline changed: was ${fmtTokens(p.context_window)}, now ${fmtTokens(p.headline_window)}`;
  else
    d.title = `routed window ${fmtTokens(p.effective_window)} < headline ${fmtTokens(p.headline_window)} — ring uses ${fmtTokens(p.effective_window)}`;
  return d;
}

let _popoverFor = null, _popHideTimer = null;
function renderModelBar() {
  const bar = $("#token-bar"); if (!bar) return;
  bar.innerHTML = "";
  if (!STATE.room || !roomRoster().length) { hideModelPopover(); return; }
  const spend = modelPercents();
  const ctxUsed = forwardTokenEstimate();
  for (const k of roomRoster()) {
    const sq = el("span", "model-square"); sq.dataset.model = k;
    sq.append(tileGlyph(k, ctxUsed));               // context-fill ring + speaker dot
    const n = el("span"); n.textContent = fmtTokens(spend.per[k] || 0); sq.append(n);
    sq.addEventListener("mouseenter", () => showModelPopover(k, sq.getBoundingClientRect()));
    sq.addEventListener("mouseleave", scheduleHidePopover);
    sq.addEventListener("click", () => showModelPopover(k, sq.getBoundingClientRect()));   // touch
    bar.append(sq);
  }
  if (spend.total) {
    const s = el("span", "session-total");
    s.textContent = `session ${spend.approx ? "~" : ""}${fmtTokens(spend.total)} tok`
      + (spend.anyCost ? ` · ${fmtCost(spend.totalCost)}` : "");
    bar.append(s);
  }
}

function scheduleHidePopover() { clearTimeout(_popHideTimer); _popHideTimer = setTimeout(hideModelPopover, 180); }
function hideModelPopover() { clearTimeout(_popHideTimer); $("#model-popover").classList.add("hidden"); _popoverFor = null; }
function showModelPopover(k, rect) {
  clearTimeout(_popHideTimer);
  const pop = $("#model-popover"); pop.innerHTML = "";
  _popoverFor = { k, rect };
  const info = squareInfo(k, modelPercents());
  pop.append(popoverHeader(k));                     // dot + name + via-subtitle
  const eff = effortSection(k); if (eff) pop.append(eff);
  const stats = el("div", "mp-stats");             // divider + one-line rows
  for (const cell of STAT_CELLS) stats.append(mpRow(cell.label, cell.val(k, info), cell.note ? cell.note(k) : null));
  pop.append(stats);
  pop.classList.remove("hidden");
  // anchor ABOVE the square (the bar sits at the bottom), clamped to the viewport
  pop.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - pop.offsetWidth - 12)) + "px";
  pop.style.top = Math.max(8, rect.top - pop.offsetHeight - 8) + "px";
  pop.onmouseenter = () => clearTimeout(_popHideTimer);   // stay open while hovering the popover
  pop.onmouseleave = scheduleHidePopover;
}

// ===== sidebar ===============================================================
function applyUI() {
  const sb = $("#sidebar");
  sb.style.width = (STATE.ui.sidebar_width || 260) + "px";
  sb.classList.toggle("collapsed", !!STATE.ui.sidebar_collapsed);
  $("#sidebar-expand").classList.toggle("hidden", !STATE.ui.sidebar_collapsed);
  const trajOpen = !!STATE.ui.trajectory_open;
  $("#traj-rail").classList.toggle("hidden", !trajOpen);
  $("#traj-toggle").classList.toggle("active", trajOpen);
  if (trajOpen) drawTrajGraph();          // the rail only has a size once it's shown
  applyComposerHeight();
  enforcePaneFit();   // sidebar collapse/expand changes workspace width → re-check coexistence (Phase 34.3)
}

// composer (the model-bar + mode + input zone) height — dragged via #composer-resizer,
// persisted to ui.json like the sidebar/margin sizes. The input textarea flexes to fill.
function composerClamp(h) {
  return Math.max(110, Math.min(Math.round(window.innerHeight * 0.6), h));
}
function applyComposerHeight() {
  const c = document.querySelector(".composer");
  if (!c) return;
  const h = STATE.ui.composer_height;
  if (h) c.style.height = composerClamp(h) + "px";   // unset → natural height
}

function renderSidebar() {
  const list = $("#room-list"); list.innerHTML = "";
  if (!STATE.rooms.length) {
    const e = el("div", "sidebar-empty");
    e.innerHTML = "No rooms yet.<br />Create your first room to begin.";
    list.append(e);
    return;
  }
  for (const r of STATE.rooms) {
    const row = el("div", "room-row" + (STATE.room && r.id === STATE.room.id ? " active" : ""));
    if (r.running) row.append(el("span", "spinner room-spin"));               // a round is in flight here
    else if (r.unread && !(STATE.room && r.id === STATE.room.id)) row.append(el("span", "unread-dot"));
    const t = el("span", "rtitle"); t.textContent = r.title || r.id; row.append(t);
    if (r.turn_count) { const m = el("span", "rmeta"); m.textContent = r.turn_count; row.append(m); }
    row.addEventListener("click", () => switchRoom(r.id));
    row.addEventListener("mouseenter", () => schedulePreview(r, row));
    row.addEventListener("mouseleave", hidePreview);
    list.append(row);
  }
}

// ===== room hover preview (cheap, no model call) =============================
let _previewTimer = null;
function fmtDate(ts) {
  if (!ts) return "?";
  const d = new Date(ts);
  return isNaN(d) ? "?" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
function schedulePreview(room, rowEl) {
  clearTimeout(_previewTimer);
  _previewTimer = setTimeout(() => showPreview(room, rowEl.getBoundingClientRect()), 250);  // debounce pass-through
}
function hidePreview() {
  clearTimeout(_previewTimer);
  $("#room-preview").classList.add("hidden");
}
function showPreview(room, rect) {
  const pop = $("#room-preview"); pop.innerHTML = "";
  const title = el("div", "rp-title"); title.textContent = room.title || room.id; pop.append(title);
  const models = el("div", "rp-models");
  (room.participants || []).forEach((k) => {
    const p = providerOf(k); models.append(dot(p ? p.color : DOT_DEFAULT));
    const s = el("span"); s.textContent = k; s.style.marginRight = "8px"; models.append(s);
  });
  if (!(room.participants || []).length) { const s = el("span"); s.textContent = "no models yet"; models.append(s); }
  pop.append(models);
  const dates = el("div", "rp-dates");
  dates.textContent = `started ${fmtDate(room.created)} · last ${fmtDate(room.last_ts)} · ${room.turn_count || 0} turns`;
  pop.append(dates);
  if (room.preview) { const sum = el("div", "rp-summary"); sum.textContent = room.preview; pop.append(sum); }  // textContent = no HTML injection
  pop.classList.remove("hidden");
  // position to the right of the row, clamped to the viewport
  const top = Math.min(rect.top, window.innerHeight - pop.offsetHeight - 12);
  pop.style.top = Math.max(8, top) + "px";
  pop.style.left = (rect.right + 8) + "px";
}

async function refreshRooms() {
  const data = await api("/rooms");
  STATE.rooms = data.rooms || [];
  renderSidebar();
}

// ===== adopt / switch / new ==================================================
function adoptRoom(view) {
  const isSwitch = !STATE.room || STATE.room.id !== view.id;
  _forcePin = isSwitch;                  // a room SWITCH always lands at the bottom
  if (isSwitch) STATE.paintDots = null;  // a paint overlay is transient gesture state — it does
                                         // not follow you across rooms (38.4). Same-room adopts
                                         // (send results, polls, rollback) leave it alone.
  STATE.room = {
    id: view.id, title: view.title,
    participants: view.participants || [], judge: view.judge || null,
    margin_model: view.margin_model || null,
    splitter_width: view.splitter_width || null,
    tags: view.tags || [],
    reasoning_effort: view.reasoning_effort || {},
    artifacts_dir: view.artifacts_dir || "",   // per-room override; "" = inherit global (Phase 32.1)
    viewer_width: view.viewer_width || null,    // per-room viewer pane width (Phase 33.2)
    code_seats: view.code_seats || [],
    workspace_path: view.workspace_path || "",
    channel_mode: view.channel_mode || "auto",
    code_pane_width: view.code_pane_width || null,
  };
  STATE.turns = view.turns || [];
  STATE.outbox = view.outbox || [];
  if (view.code_turns !== undefined) STATE.codeTurns = view.code_turns || [];
  STATE.pending = null;                 // authoritative turns supersede any optimistic bubble (Phase 31.3)
  // A live converse stream belongs to ONE room; switching away detaches its bubble so it never
  // paints into another room (the stream keeps draining server-side as a background round). (36.4)
  if (STATE.streaming && STATE.streaming.roomId !== view.id) STATE.streaming = null;
  if (view.margin_turns !== undefined) STATE.marginTurns = view.margin_turns || [];
  drawTrajGraph();   // the ONE authoritative committed-turn mutation point — never render()
  renderComposerPickers();
  render();
  renderMargin();                       // show THIS room's own margin
  renderCodePane();
  if (STATE.marginOpen) applyMarginWidth();
  if (STATE.viewerOpen) applyViewerWidth();
  if (STATE.codeOpen) applyCodeWidth();
  watchActiveRoom(!!view.running);      // round-in-progress signal (Phase 30)
}

// In-room "round in progress" signal. The per-send status is cleared on room switch, so a
// backgrounded or resumed round looked idle. This reconstructs it from server state
// (room.running): show a spinner + poll the room every few seconds so the panels + synthesis
// appear live, then clear when it finishes.
let _roomPollTimer = null, _watching = null;
function stopRoomPoll() { if (_roomPollTimer) { clearTimeout(_roomPollTimer); _roomPollTimer = null; } }
function watchActiveRoom(running) {
  stopRoomPoll();
  if (STATE.streaming) return;          // the live stream IS the running view — poll stands down (Phase 36.4)
  if (STATE.room && running) {
    _watching = STATE.room.id;
    setStatus("a round is running in this room…", true);
    _roomPollTimer = setTimeout(pollActiveRoom, 3000);
  } else {
    if (_watching && (!STATE.room || _watching === STATE.room.id)) setStatus("");   // a watched round just ended
    _watching = null;
  }
}
async function pollActiveRoom() {
  _roomPollTimer = null;
  if (!STATE.room) { _watching = null; return; }
  const id = STATE.room.id;
  let view;
  try { view = await api(`/rooms/${id}`); }
  catch (e) { watchActiveRoom(true); return; }          // transient error → keep watching
  if (!STATE.room || STATE.room.id !== id) return;       // moved on; switchRoom manages the new room
  if ((view.turn_count || 0) !== (STATE.turns || []).length) {
    adoptRoom(view);                                     // new turns landed → re-render + re-watch
    refreshRooms();
  } else {
    watchActiveRoom(!!view.running);                     // still running → keep polling; done → clear
  }
}

async function markRead(id, count) {
  try { await api(`/rooms/${id}`, "PUT", { last_read_pos: count }); } catch (e) { /* non-fatal */ }
}

// Per-room composer drafts (Phase 31.2): a session-only, in-memory map so typed text
// doesn't bleed across the single shared #input / #margin-input when you switch rooms.
// Deliberately NOT persisted — ui.json is a global scalar store and message text has no
// business in a config file (cross-restart drafts are DEFERRED). The margin-input element
// is always in the DOM (even hidden), so read/write is safe regardless of margin state.
function stashDrafts() {
  if (!STATE.room) return;
  STATE.drafts[STATE.room.id] = $("#input").value;
  STATE.marginDrafts[STATE.room.id] = $("#margin-input").value;
}
function restoreDrafts() {
  const id = STATE.room && STATE.room.id;
  $("#input").value = (id && STATE.drafts[id]) || "";
  $("#margin-input").value = (id && STATE.marginDrafts[id]) || "";
}

async function switchRoom(id) {
  if (STATE.room && STATE.room.id === id) { focusComposer(); return; }   // already here — no-op re-adopt
  banner(null); setStatus("");   // a background round's status must not bleed across rooms
  stashDrafts();                 // save the room we're leaving BEFORE adopt swaps STATE.room (Phase 31.2)
  stashRoomComposer();           // …and its session mode + addressee (Phase 35.2)
  closeViewer();                 // the viewer's content belongs to the room we're leaving (Phase 33.2)
  STATE.staged = []; renderStagedFiles();   // staged files belong to the room you left
  try {
    const view = await api(`/rooms/${id}/activate`, "POST");   // sets active + marks read
    adoptRoom(view);
    restoreDrafts();             // load the room we arrived in — SYNCHRONOUS with adopt so the
    restoreRoomComposer();       // …restore its mode + addressee AFTER adopt rebuilt pickers (Phase 35.2)
    focusComposer();             // composer is settled before the title is observable (Phase 31.1/31.2)
    await refreshRooms();        // sidebar refresh is independent — after the composer is settled
  } catch (e) { banner(e.message); }
}

async function newRoom() {
  const title = prompt("room title:");
  if (!title) return;
  stashDrafts();                 // preserve the room we're leaving (Phase 31.2)
  stashRoomComposer();           // …and its session mode + addressee (Phase 35.2)
  closeViewer();                 // a fresh room has no artifact open (Phase 33.2)
  try {
    const data = await api("/rooms", "POST", { title });   // EMPTY room — forced decision
    adoptRoom(data.room);
    restoreDrafts();             // a fresh room starts with an empty composer — synchronous with adopt (Phase 31.2)
    restoreRoomComposer();       // fresh room → converse + auto, collapsed (Phase 35.2)
    focusComposer();             // caret ready in the new room (Phase 31.1)
    banner("New room — choose its models and judge in “models” (top-right) before researching.");
    await refreshRooms();        // sidebar refresh is independent
  } catch (e) { banner(e.message); }
}

// ===== attached files (Phase 22) =============================================
// Drag-drop / pick a .md / .txt onto the composer; it stages as a removable chip
// and, on send, becomes a file-turn (text = the file content) the panel reads —
// the way you load files at the start of a claude.ai / Grok chat. Text only: the
// allowlist mirrors the engine (TEXT_EXTS / MAX_FILE_BYTES); richer formats need
// extraction and stay out.
const FILE_EXTS = [".md", ".txt"];
const MAX_FILE_BYTES = 1_000_000;
function fileExt(name) { const n = (name || "").toLowerCase(); const i = n.lastIndexOf("."); return i >= 0 ? n.slice(i) : ""; }
function fileAllowed(name) { return FILE_EXTS.includes(fileExt(name)); }
function humanSize(n) { return n < 1024 ? n + " B" : (n / 1024).toFixed(n < 1024 * 10 ? 1 : 0) + " KB"; }

function readTextFile(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result || ""));
    r.onerror = () => reject(new Error("read failed"));
    r.readAsText(file);
  });
}

async function stageFiles(fileList) {
  for (const f of Array.from(fileList || [])) {
    if (!fileAllowed(f.name)) { banner(`text files only for now (.md / .txt) — skipped ${f.name}`); continue; }
    if (f.size > MAX_FILE_BYTES) { banner(`${f.name} is too large (max 1 MB) — skipped`); continue; }
    try { STATE.staged.push({ filename: f.name, content: await readTextFile(f) }); }
    catch (e) { banner(`could not read ${f.name}: ${e.message}`); }
  }
  renderStagedFiles();
}

function renderStagedFiles() {
  const box = $("#staged-files");
  box.innerHTML = "";
  if (!STATE.staged.length) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  STATE.staged.forEach((f, i) => {
    const chip = el("span", "file-chip");
    const nm = el("span", "file-chip-name"); nm.textContent = "📎 " + f.filename; chip.append(nm);
    const sz = el("span", "file-chip-size"); sz.textContent = humanSize(f.content.length); chip.append(sz);
    const x = el("button", "file-chip-x"); x.textContent = "✕"; x.title = "remove";
    x.addEventListener("click", () => { STATE.staged.splice(i, 1); renderStagedFiles(); });
    chip.append(x); box.append(chip);
  });
}

// A file-turn renders as a collapsed chip (filename + size), expanding to the
// content via a SAFE path: .md through the sanitized renderer, anything else as
// textContent — never innerHTML of raw file text.
function renderFileTurn(t) {
  const meta = t.meta || {};
  const div = el("div", "turn human file-turn");
  div.dataset.turnId = t.id;                                        // graph jump anchor (Phase 37)
  const head = el("button", "file-turn-head");
  const caret = el("span", "file-turn-caret"); caret.textContent = "▸";
  const name = el("span", "file-turn-name"); name.textContent = "📎 " + (meta.filename || "file");
  const size = el("span", "file-turn-size"); size.textContent = humanSize(meta.size || 0);
  head.append(caret, name, size);
  const bodyWrap = el("div", "file-turn-body hidden");
  const content = (t.text || "").replace(/^\[file:[^\]]*\]\n\n/, "");   // strip the header
  if (fileExt(meta.filename || "") === ".md") renderMd(bodyWrap, content);
  else { const pre = el("pre", "file-turn-pre"); pre.textContent = content; bodyWrap.append(pre); }
  head.addEventListener("click", () => {
    const show = bodyWrap.classList.contains("hidden");
    bodyWrap.classList.toggle("hidden", !show);
    caret.textContent = show ? "▾" : "▸";
  });
  div.append(head, bodyWrap);
  return div;
}

// ===== compose ===============================================================
function currentMode() { return $("#mode").value; }

// Build the mode-selection object (the v1 producer of what /run consumes — a future
// trajectory-graph is a second producer of the same shape). Returns null + banners on a
// validation miss. params reveal per mode (converse → target; fusion → panel+judge;
// side-by-side → two seats + judge).
function panelContext(checkboxSel) { return $(checkboxSel) && $(checkboxSel).checked ? "transcript" : "blind"; }

function buildSelection(mode, text) {
  if (mode === "fusion" || mode === "mapping") {     // shared panel params
    const panel = pickedPanel();
    if (!panel.length) { banner("select at least one model for the panel (or set the room's models)"); return null; }
    const judge = $("#judge-pick").value;
    if (!judge) { banner("select a judge for this round (or set one in “models”)"); return null; }
    return { mode, prompt: text, effort: $("#effort").value, panel, judge, panel_context: panelContext("#panel-context") };
  }
  if (mode === "side_by_side") {
    const seats = pickedSeats();
    if (seats.length !== 2) { banner("side-by-side needs exactly two models — pick two"); return null; }
    const judge = $("#sxs-judge").value;
    if (!judge) { banner("select a judge for the divergence note (or set one in “models”)"); return null; }
    return { mode, prompt: text, effort: $("#sxs-effort").value, seats, judge, panel_context: panelContext("#sxs-context") };
  }
  if (mode === "yes_and") {
    const a = $("#ya-a").value, bb = $("#ya-b").value;
    if (!a || !bb) { banner("yes-and needs two models (A then B)"); return null; }
    if (a === bb) { banner("yes-and needs two DIFFERENT models for A and B"); return null; }
    return { mode, prompt: text, effort: $("#ya-effort").value, seats: [a, bb] };
  }
  // converse
  return { mode, prompt: text, target: $("#addressee").value || null };
}

function modeStatus(sel) {
  const ctx = sel.panel_context === "transcript" ? " (panel sees chat)" : "";
  if (sel.mode === "fusion") return `fusion: ${sel.panel.length} model${sel.panel.length === 1 ? "" : "s"} working + ${sel.judge} synthesizes…${ctx}`;
  if (sel.mode === "mapping") return `mapping: ${sel.panel.length} model${sel.panel.length === 1 ? "" : "s"} working + ${sel.judge} maps the landscape…${ctx}`;
  if (sel.mode === "side_by_side") return `side-by-side: ${sel.seats.join(" + ")} → ${sel.judge} notes divergence…${ctx}`;
  if (sel.mode === "yes_and") return `yes-and: ${sel.seats[0]} → ${sel.seats[1]} builds on it…`;
  return `converse: ${sel.target ? "@" + sel.target : "(last AI)"} responding…`;
}

async function send() {
  const input = $("#input"); const text = input.value.trim();
  const hasFiles = STATE.staged.length > 0;
  if (!text && !hasFiles) return;
  if (!STATE.room) { banner("Create a room first (+ new room)."); return; }
  const mode = currentMode();
  const roomId = STATE.room.id;            // the message + files belong to this room
  banner(null);
  // Build + validate the mode-selection object UP FRONT (before attaching files) so a
  // misconfigured send doesn't half-commit the attachments.
  let sel = null;
  if (text) { sel = buildSelection(mode, text); if (!sel) return; }
  // Note: the send button is deliberately NOT globally disabled. A round may be
  // in flight in room A while the user switches to B and sends there; each send
  // captures its own roomId and the server serializes per-room. Disabling here
  // would defeat multi-room concurrency.
  try {
    // 1. flush staged files first — file-turns precede the message turn, so the
    //    panel reads "here's the document, now my question". NOTE (Phase 31.3): this is
    //    NOT atomic with the /run below — files commit as turns before the round, so a
    //    failed /run leaves the file-turns in place and preserves only the typed text
    //    (optimistic render covers the text only). Atomic send is deferred (DEFERRED.md).
    if (hasFiles) {
      const files = STATE.staged.map((f) => ({ filename: f.filename, content: f.content }));
      setStatus(`attaching ${files.length} file${files.length === 1 ? "" : "s"}…`, true);
      const fdata = await api(`/rooms/${roomId}/files`, "POST", { files });
      STATE.staged = []; renderStagedFiles();
      if (!text) {                           // files-only send: no model call
        if (STATE.room && STATE.room.id === fdata.room_id) {
          adoptRoom(fdata.transcript);
          await markRead(roomId, fdata.transcript.turn_count);
          setStatus("");
        }
        await refreshRooms();
        return;
      }
    }
    // 2. the message turn (+ its model round). Converse STREAMS (Phase 36); the other modes
    //    keep the one-shot /run dispatch (panel/judge stay synchronous by design).
    setStatus(modeStatus(sel), true);
    STATE.pending = { text, ts: Date.now() };   // optimistic user bubble, painted this frame (Phase 31.3)
    _forcePin = true;   // sending is an explicit act: always show your own message, even from scrollback.
    render();           // (the stream's later frames then follow the bottom — until you scroll away.)
    const data = mode === "converse"
      ? await streamConverse(roomId, sel)        // SSE: live AI bubble + Stop (Phase 36.4/36.5)
      : await api(`/rooms/${roomId}/run`, "POST", sel);
    // (streamConverse's finally already released its own STATE.streaming/streamAbort — scoped
    //  by identity so a backgrounded overlapping stream isn't clobbered.)
    input.value = "";
    delete STATE.drafts[roomId];                 // sent successfully → no draft to restore (Phase 31.2)
    STATE.paintDots = null;                      // the round consumed the paint (38.4); a non-compiling
                                                 // overlay was decoration over the last valid state anyway
    // Concurrency: render the result ONLY if its room is still on screen. If the
    // user switched away while it ran, leave the active view alone and let the
    // sidebar dot surface the background completion.
    if (STATE.room && STATE.room.id === data.room_id) {
      adoptRoom(data.transcript);
      await markRead(roomId, data.transcript.turn_count);
    }
    await refreshRooms();
    // Only clear the status line if it's still describing THIS (now-finished)
    // send and the user hasn't moved on to another room's activity.
    if (STATE.room && STATE.room.id === data.room_id) setStatus("");
  } catch (e) {
    // streamConverse's finally released its own stream slots (identity-scoped); just drop the echo.
    STATE.pending = null; render();              // drop the optimistic bubble
    if (e && e.name === "AbortError") {          // user hit Stop (Phase 36.5): the message WAS sent
      input.value = ""; delete STATE.drafts[roomId];   // (human turn committed) → don't restore the draft
      STATE.paintDots = null;                          // …and committed turns consumed the paint (38.4)
      try { if (STATE.room && STATE.room.id === roomId) adoptRoom(await api(`/rooms/${roomId}`)); } catch (_e) { /* */ }
      await refreshRooms();
      setStatus(""); banner("stopped — no answer saved.");
    } else {
      setStatus(""); banner(`${mode} failed: ${e.message}`);   // #input keeps the draft (Phase 31.3/31.2)
    }
  }
}

// Stream a converse round over SSE (Phase 36.4/36.5): open a fetch reader, feed deltas into
// STATE.streaming (throttled to an animation frame — never re-parse markdown per token), and
// resolve with the terminal `done` payload (same shape as /run's return). An `error` event
// rejects; the Stop button aborts the fetch (→ AbortError, handled by send()'s catch). The 3s
// poll stands down while streaming (watchActiveRoom checks STATE.streaming).
async function streamConverse(roomId, sel) {
  const speaker = sel.target || (STATE.room && STATE.room.participants && STATE.room.participants[0]) || "assistant";
  const ctrl = new AbortController();
  const mine = STATE.streaming = { speaker, text: "", roomId };   // this stream's bubble (identity-owned)
  STATE.streamAbort = ctrl;
  stopRoomPoll();                                // the live stream IS the running view
  render();
  let raf = 0;
  try {
    const res = await fetch(`/rooms/${roomId}/run/stream`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sel), signal: ctrl.signal,
    });
    if (!res.ok || !res.body) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `${res.status} ${res.statusText}`);
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "", done = null, errMsg = null;
    const paint = () => { raf = 0; render(); };
    while (true) {
      const { value, done: rdDone } = await reader.read();
      if (rdDone) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, i); buf = buf.slice(i + 2);
        let ev = null, dat = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) ev = line.slice(6).trim();
          else if (line.startsWith("data:")) dat = line.slice(5).trim();
        }
        if (ev === "delta") {
          const chunk = (JSON.parse(dat).text) || "";
          // paint only while THIS stream's bubble is the live one; if the user switched away
          // (adoptRoom nulled it) or started a newer stream, we keep DRAINING but stop painting —
          // the server round finishes as a background round (its turn surfaces via the sidebar dot + poll).
          if (STATE.streaming === mine) {
            STATE.streaming.text += chunk;
            if (!raf) raf = requestAnimationFrame(paint);
          }
        } else if (ev === "done") { done = JSON.parse(dat); }
        else if (ev === "error") { errMsg = JSON.parse(dat).message || "stream error"; }
      }
    }
    if (errMsg) throw new Error(errMsg);
    if (!done) throw new Error("stream ended without a result");
    return done;
  } finally {
    if (raf) cancelAnimationFrame(raf);
    // release the shared slots ONLY if a newer stream hasn't taken them over — with overlapping
    // cross-room sends, the first to finish must not wipe the other's live bubble / Stop button.
    if (STATE.streaming === mine) STATE.streaming = null;
    if (STATE.streamAbort === ctrl) STATE.streamAbort = null;
  }
}

function syncModeUI() {
  const m = currentMode();
  $("#converse-opts").classList.toggle("hidden", m !== "converse");
  $("#research-opts").classList.toggle("hidden", m !== "fusion" && m !== "mapping");   // shared panel params
  $("#sxs-opts").classList.toggle("hidden", m !== "side_by_side");
  $("#yesand-opts").classList.toggle("hidden", m !== "yes_and");
}

// ===== composer fast path (Phase 35) =========================================
// The collapsed composer asks nothing: a mode chip + addressee. Mode + its machinery live
// in #composer-advanced, opened via the chip. Mode + addressee are session-scoped PER-ROOM
// (STATE.roomModes / roomAddressees — the drafts precedent, one level up); no disk keys.
const MODE_LABELS = { converse: "converse", fusion: "fusion", mapping: "mapping",
                      side_by_side: "side-by-side", yes_and: "yes-and" };
// The toggle names the active mode (so non-converse machinery is never invisible when
// collapsed) + a chevron for the disclosure state; accented when non-converse.
function updateModeChip() {
  const m = currentMode();
  const t = $("#mode-toggle"); if (!t) return;
  t.textContent = (MODE_LABELS[m] || m) + " " + (STATE.advancedOpen ? "▾" : "▸");
  t.classList.toggle("active", m !== "converse");
}
function setAdvanced(open) {
  STATE.advancedOpen = !!open;
  $("#composer-advanced").classList.toggle("hidden", !open);
  updateModeChip();
}
// Stash/restore the room's session composer state, keyed by room id (mirrors stashDrafts).
function stashRoomComposer() {
  if (!STATE.room) return;
  STATE.roomModes[STATE.room.id] = $("#mode").value;
  STATE.roomAddressees[STATE.room.id] = $("#addressee").value;
}
function restoreRoomComposer() {
  const id = STATE.room && STATE.room.id;
  const mode = (id && STATE.roomModes[id]) || "converse";
  $("#mode").value = mode; syncModeUI();
  // addressee: re-select AFTER renderAddressee (in adoptRoom) rebuilt the options — that
  // rebuild wipes any prior pick (recon §1); silently fall back to auto if it left the roster.
  const want = (id && STATE.roomAddressees[id]) || "";
  const sel = $("#addressee");
  sel.value = [...sel.options].some((o) => o.value === want) ? want : "";
  setAdvanced(mode !== "converse");   // auto-expand non-converse so active machinery is visible
  drawTrajGraph();                    // restored composer state moves the ghost too (38.3)
}

// ===== room settings (per-room roster + judge) ===============================
function openRoomSettings() {
  if (!STATE.room) return;
  const roster = $("#room-roster"); roster.innerHTML = "";
  const inRoom = new Set(STATE.room.participants || []);
  for (const p of STATE.participants) {
    const lab = el("label", "pickitem");
    const cb = el("input"); cb.type = "checkbox"; cb.value = p.name; cb.checked = inRoom.has(p.name);
    cb.addEventListener("change", fillRoomJudge);
    lab.append(cb, dot(p.color), document.createTextNode(p.name));
    roster.append(lab);
  }
  fillRoomJudge();
  $("#room-tags").value = (STATE.room.tags || []).join(", ");
  // per-room artifacts dir (Phase 32.1): the room's own value; placeholder shows the
  // resolved GLOBAL so a blank field visibly means "inherit the global".
  const artIn = $("#room-artifacts-dir");
  if (artIn) {
    artIn.value = STATE.room.artifacts_dir || "";
    const g = (STATE.ui.artifacts_dir || "").trim();
    artIn.placeholder = g ? `blank = inherit global (${g})` : "blank = inherit global (none set)";
  }
  $("#room-settings-overlay").classList.remove("hidden");
}
function checkedRoster() {
  return [...document.querySelectorAll("#room-roster input:checked")].map((i) => i.value);
}
function fillRoomJudge() {
  const sel = $("#room-judge");
  const roster = checkedRoster();
  const cur = STATE.room && STATE.room.judge;
  let html = `<option value="" disabled${cur && roster.includes(cur) ? "" : " selected"}>select…</option>`;
  html += roster.map((k) => `<option value="${k}"${k === cur ? " selected" : ""}>${k}</option>`).join("");
  sel.innerHTML = html;
}
async function saveRoomSettings() {
  const participants = checkedRoster();
  const judge = $("#room-judge").value || null;
  const tags = $("#room-tags").value.split(",").map((s) => s.trim()).filter(Boolean);
  const artIn = $("#room-artifacts-dir");
  const artifacts_dir = artIn ? artIn.value.trim() : "";   // "" = inherit global (Phase 32.1)
  try {
    await api(`/rooms/${STATE.room.id}`, "PUT", { participants, judge, tags, artifacts_dir });
    STATE.room.participants = participants; STATE.room.judge = judge; STATE.room.tags = tags;
    STATE.room.artifacts_dir = artifacts_dir;
    renderComposerPickers(); render();
    $("#room-settings-overlay").classList.add("hidden");
    banner(null);
  } catch (e) { banner(e.message); }
}

// ===== margin (in-room side-channel) =========================================
function marginStatus(msg, busy) {
  const s = $("#margin-status"); s.innerHTML = ""; s.classList.toggle("busy", !!busy);
  if (busy) { const sp = el("span", "spinner"); s.appendChild(sp); }
  if (msg) s.appendChild(document.createTextNode(msg));
}

function renderMarginModel() {
  const sel = $("#margin-model");
  const cur = STATE.room && STATE.room.margin_model;
  let html = `<option value="" disabled${cur ? "" : " selected"}>model…</option>`;
  html += STATE.participants.map((p) => `<option value="${p.name}"${p.name === cur ? " selected" : ""}>${p.name}</option>`).join("");
  sel.innerHTML = html;
}

function renderMargin() {
  renderMarginModel();
  const box = $("#margin-stream"); box.innerHTML = "";
  if (!STATE.marginTurns.length) {
    box.innerHTML = '<div class="empty">Ask a side-question — it sees the main chat as background but never touches it.</div>';
    return;
  }
  for (const t of STATE.marginTurns) {
    const isQ = t.role === "human";
    const div = el("div", "margin-turn " + (isQ ? "q" : "a"));
    div.appendChild(whoLine(isQ ? "you" : t.speaker, colorOf(isQ ? "human" : t.speaker)));
    const body = el("div", "body"); renderMd(body, t.text); div.appendChild(body);
    if (!isQ) {
      const btn = el("button", "promote-btn"); btn.textContent = "copy to main";
      btn.title = "append this answer to the main thread (the one way margin → main)";
      btn.addEventListener("click", () => promoteMargin(t.id));
      div.appendChild(btn);
    }
    box.appendChild(div);
  }
  box.scrollTop = box.scrollHeight;
}

// ===== pane coexistence (Phase 34) ===========================================
// Both right panes (viewer + margin) may be open at once IFF the transcript column keeps a
// minimum readable width; otherwise opening one closes the other (Phase 33 behavior). Row
// order after 34.1: [main-col | v-splitter | viewer | m-splitter | margin].
const MIN_MAIN = 520;     // px — the transcript never shrinks below this when BOTH panes are open
const SPLITTER_PX = 5;    // each pane's drag handle (matches .margin-splitter / .viewer-splitter)
function workspaceWidth() { const w = document.querySelector(".workspace"); return w ? w.clientWidth : window.innerWidth; }
function viewerWidth() { return (STATE.room && STATE.room.viewer_width) || 500; }   // stored, else the CSS default
function marginWidth() { return (STATE.room && STATE.room.splitter_width) || 340; }
// would the transcript + BOTH panes (widths vW, mW) still leave ≥ MIN_MAIN for the transcript?
function fitsBoth(vW, mW) { return workspaceWidth() - vW - mW - 2 * SPLITTER_PX >= MIN_MAIN; }
// resize / sidebar toggle can violate the fit after both are open — yield the MARGIN (a
// deliberate fixed rule: the peripheral channel always gives way; no recency, no thrash —
// once it's closed only one pane remains and the guard is inert).
function enforcePaneFit() {
  if (STATE.viewerOpen && STATE.marginOpen && !fitsBoth(viewerWidth(), marginWidth())) closeMargin();
}

function applyMarginWidth() {
  const w = STATE.room && STATE.room.splitter_width;
  if (w) $("#margin").style.width = w + "px";
}

function openMargin() {
  if (!STATE.room) return;
  // coexist with the viewer iff the transcript still fits; else swap (Phase 34.2)
  if (STATE.viewerOpen && !fitsBoth(viewerWidth(), marginWidth())) closeViewer();
  STATE.marginOpen = true;
  $("#margin").classList.remove("hidden");
  $("#margin-splitter").classList.remove("hidden");
  applyMarginWidth(); renderMargin();
}
function closeMargin() {
  STATE.marginOpen = false;
  $("#margin").classList.add("hidden");
  $("#margin-splitter").classList.add("hidden");
  focusComposer();               // return the caret to the main composer (Phase 31.1)
}

// ===== artifact viewer pane (Phase 33) =======================================
// A right-side pane that renders a turn's ```markdown block as a DOCUMENT (source of
// truth = turn.text, passed in from the chip closure — no endpoint, no disk read).
// Mutually exclusive with the margin; per-room width (viewer_width, splitter_width
// precedent); closes on room switch (its content belongs to the room you're leaving).
function applyViewerWidth() {
  const w = STATE.room && STATE.room.viewer_width;
  if (w) $("#viewer").style.width = w + "px";   // else the CSS default (wider than the margin)
}
function openViewer(art) {
  if (!STATE.room) return;
  // coexist with the margin iff the transcript still fits; else swap (Phase 34.2)
  if (STATE.marginOpen && !fitsBoth(viewerWidth(), marginWidth())) closeMargin();
  STATE.viewerOpen = true;
  const savedPath = art && art.savedPath;
  $("#viewer-title").textContent = (art && art.title) || "artifact";
  $("#viewer-title").title = savedPath || (art && art.title) || "";
  const cp = $("#viewer-copypath");
  cp.classList.toggle("hidden", !savedPath);    // copy-path only when the block was saved (has meta)
  cp.onclick = savedPath ? (async () => {
    try { await navigator.clipboard.writeText(savedPath); cp.textContent = "copied ✓";
          setTimeout(() => (cp.textContent = "copy path"), 1200); }
    catch (e) { banner("copy failed: " + e.message); }
  }) : null;
  renderMd($("#viewer-body"), (art && art.content) || "");   // vendored renderer; #viewer .md styles it as a doc
  $("#viewer-body").scrollTop = 0;                            // a fresh artifact starts at the top
  $("#viewer").classList.remove("hidden");
  $("#viewer-splitter").classList.remove("hidden");
  applyViewerWidth();
}
function closeViewer() {
  if (!STATE.viewerOpen) return;                // no-op when already closed (don't steal focus)
  STATE.viewerOpen = false;
  $("#viewer").classList.add("hidden");
  $("#viewer-splitter").classList.add("hidden");
  focusComposer();               // parity with closeMargin (Phase 31.1)
}

async function marginSend() {
  if (!STATE.room) return;
  const input = $("#margin-input"); const text = input.value.trim();
  if (!text) return;
  const model = $("#margin-model").value;
  if (!model) { marginStatus("pick a margin model first."); return; }
  const window_ = $("#margin-window").value;
  const roomId = STATE.room.id;
  marginStatus(`${model} responding…`, true);
  try {
    const data = await api(`/rooms/${roomId}/margin`, "POST", { prompt: text, window: window_, model });
    input.value = "";
    delete STATE.marginDrafts[roomId];      // sent → no margin draft to restore (Phase 31.2)
    // Concurrency: only paint into the margin if we're still in that room.
    if (STATE.room && STATE.room.id === data.room_id) {
      STATE.marginTurns = data.margin_turns || [];
      renderMargin(); marginStatus("");
      drawTrajGraph();   // POST /margin returns no room view, so nothing else redraws the rail
    }
  } catch (e) { marginStatus(`margin failed: ${e.message}`); }
}

async function promoteMargin(turnId) {
  try {
    const data = await api(`/rooms/${STATE.room.id}/margin/${turnId}/promote`, "POST");
    if (STATE.room && STATE.room.id === data.room_id) adoptRoom(data.transcript);  // note now in main
    banner("Copied to main.");
  } catch (e) { banner(e.message); }
}

// ===== code seat pane + diplomatic outbox (Phase 39) =========================
function codeStatus(msg, busy) {
  const s = $("#code-status"); if (!s) return;
  s.innerHTML = ""; s.classList.toggle("busy", !!busy);
  if (busy) s.appendChild(el("span", "spinner"));
  if (msg) s.appendChild(document.createTextNode(msg));
}

function codeSeatOptions() {
  // Always offer the full provider registry so the user can pick any seat for the code pane.
  // Room code_seats only records the current selection — it does not limit the menu.
  const all = (STATE.participants || []).map((p) => p.name);
  return all.filter((k, i) => all.indexOf(k) === i);
}

function renderCodeStream() {
  const box = $("#code-stream");
  if (!box) return;
  // Phase 37 pin rule: only stick to bottom if already at the edge (or first paint).
  // Scrolling up mid-stream must not yank the reader back to the tail.
  const pin = box.scrollTop + box.clientHeight >= box.scrollHeight - 40
    || !box.dataset.hasContent;
  const savedTop = box.scrollTop;
  box.innerHTML = "";
  const turns = STATE.codeTurns || [];
  if (!turns.length && !STATE.codeStreaming) {
    box.innerHTML = '<div class="empty">Code seat harness — replies stay here. Main only via outbox.</div>';
    delete box.dataset.hasContent;
    return;
  }
  box.dataset.hasContent = "1";
  for (const t of turns) {
    const isQ = t.role === "human";
    const div = el("div", "code-turn " + (isQ ? "q" : "a"));
    const mode = (t.meta && t.meta.code_mode) || "";
    const extra = mode ? mode : "";
    div.appendChild(whoLine(isQ ? "you" : t.speaker, colorOf(isQ ? "human" : t.speaker), extra));
    const body = el("div", "body"); renderMd(body, t.text); div.appendChild(body);
    box.appendChild(div);
  }
  if (STATE.codeStreaming) {
    const div = el("div", "code-turn a streaming");
    div.appendChild(whoLine(
      (STATE.room && STATE.room.code_seats && STATE.room.code_seats[0]) || "code",
      colorOf((STATE.room && STATE.room.code_seats && STATE.room.code_seats[0]) || "human"),
      STATE.codeMode || "build"));
    const body = el("div", "body"); renderMd(body, STATE.codeStreaming.text || "…"); div.appendChild(body);
    box.appendChild(div);
  }
  if (pin) box.scrollTop = box.scrollHeight;
  else box.scrollTop = savedTop;
}

function renderCodeModes() {
  document.querySelectorAll(".code-mode").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.mode === STATE.codeMode);
  });
}

function renderCodePane() {
  const seatSel = $("#code-seat");
  const modeSel = $("#channel-mode");
  const meta = $("#code-meta");
  const list = $("#outbox-list");
  if (!seatSel || !list) return;
  const seats = codeSeatOptions();
  const cur = (STATE.room && STATE.room.code_seats && STATE.room.code_seats[0]) || seats[0] || "";
  seatSel.innerHTML = `<option value="">seat…</option>` + seats.map((name) => {
    const p = providerOf(name);
    // label = key; optional model in parens when it differs from the key
    const model = p && p.model ? p.model : "";
    const label = model && model !== name ? `${name} · ${model}` : name;
    return `<option value="${name}"${name === cur ? " selected" : ""}>${label}</option>`;
  }).join("");
  // default selection on open: first assigned/available seat (persisted if room had none)
  if (cur && seatSel.value !== cur) seatSel.value = cur;
  if (modeSel && STATE.room) modeSel.value = STATE.room.channel_mode || "auto";
  if (meta) {
    const ws = (STATE.room && STATE.room.workspace_path) || "(default on attach)";
    const seatLabel = cur || "—";
    meta.textContent = `seat: ${seatLabel} · workspace: ${ws}`;
  }
  renderCodeModes();
  renderCodeStream();
  list.innerHTML = "";
  const pending = (STATE.outbox || []).filter((i) => i.status === "pending");
  if (!pending.length) {
    list.innerHTML = '<div class="empty">No pending channel crossings.</div>';
    return;
  }
  for (const item of pending) {
    const div = el("div", "outbox-item");
    const kind = item.kind || "?";
    const payload = item.payload || {};
    const summary = kind === "ask_design_question" ? (payload.question || "")
      : kind === "comment_to_main" ? (payload.text || "")
      : kind === "request_compaction" ? (payload.note || "compaction")
      : JSON.stringify(payload).slice(0, 120);
    const kindEl = el("div", "outbox-kind"); kindEl.textContent = kind; div.appendChild(kindEl);
    const body = el("div", "outbox-body"); body.textContent = summary; div.appendChild(body);
    const actions = el("div", "outbox-actions");
    if (kind === "ask_design_question") {
      const inp = document.createElement("input");
      inp.type = "text"; inp.placeholder = "answer…"; inp.className = "outbox-answer";
      const ok = el("button"); ok.textContent = "answer";
      ok.addEventListener("click", () => approveOutbox(item.id, inp.value));
      actions.append(inp, ok);
    } else {
      const ok = el("button"); ok.textContent = "approve";
      ok.addEventListener("click", () => approveOutbox(item.id));
      actions.appendChild(ok);
    }
    const no = el("button"); no.textContent = "reject";
    no.addEventListener("click", () => rejectOutbox(item.id));
    actions.appendChild(no);
    div.appendChild(actions);
    list.appendChild(div);
  }
}

async function approveOutbox(itemId, answer) {
  if (!STATE.room) return;
  try {
    const body = answer != null ? { answer } : {};
    const data = await api(`/rooms/${STATE.room.id}/outbox/${itemId}/approve`, "POST", body);
    STATE.outbox = data.outbox || [];
    if (data.transcript) adoptRoom(data.transcript);
    else renderCodePane();
  } catch (e) { codeStatus(e.message); }
}

async function rejectOutbox(itemId) {
  if (!STATE.room) return;
  try {
    const data = await api(`/rooms/${STATE.room.id}/outbox/${itemId}/reject`, "POST");
    STATE.outbox = data.outbox || [];
    renderCodePane();
  } catch (e) { codeStatus(e.message); }
}

function codeWidth() {
  return (STATE.room && STATE.room.code_pane_width) || Math.min(Math.floor(workspaceWidth() * 0.45), 900);
}

function applyCodeWidth() {
  const pane = $("#code-pane");
  if (!pane || !STATE.codeOpen) return;
  const w = STATE.room && STATE.room.code_pane_width;
  pane.style.width = (w || codeWidth()) + "px";
}

function openCodePane() {
  if (!STATE.room) return;
  STATE.codeOpen = true;
  $("#code-pane").classList.remove("hidden");
  $("#code-splitter").classList.remove("hidden");
  // default-on-attach: if the room has no code_seats yet, pick the first available option
  // and persist it so the dropdown has a real selection (39.1).
  const seats = codeSeatOptions();
  if (seats.length && !(STATE.room.code_seats && STATE.room.code_seats.length)) {
    STATE.room.code_seats = [seats[0]];
    api(`/rooms/${STATE.room.id}`, "PUT", { code_seats: STATE.room.code_seats }).catch(() => {});
  }
  applyCodeWidth();
  renderCodePane();
  codeStatus("attaching OpenCode session…", true);
  api(`/rooms/${STATE.room.id}/code/attach`, "POST").then((d) => {
    if (STATE.room && d.room) {
      STATE.room.workspace_path = d.workspace || d.room.workspace_path || STATE.room.workspace_path;
      if (d.room.code_seats) STATE.room.code_seats = d.room.code_seats;
      if (d.code_turns) STATE.codeTurns = d.code_turns;
      renderCodePane();
    }
    const sid = d.session_id ? d.session_id.slice(0, 12) : "?";
    codeStatus(`ready · session ${sid} · :${d.port || "?"}`);
  }).catch((e) => {
    // Surface the real failure (service not restarted / opencode missing / workspace) —
    // send will re-attach via the stream endpoint, so this is advisory.
    codeStatus(`attach failed: ${e.message} — try send (re-attaches) or restart fusion`);
  });
}

function closeCodePane() {
  STATE.codeOpen = false;
  if (STATE.codeAbort) { try { STATE.codeAbort.abort(); } catch (_e) { /* */ } }
  STATE.codeStreaming = null;
  $("#code-pane").classList.add("hidden");
  $("#code-splitter").classList.add("hidden");
  focusComposer();
}

async function streamCodeSeat(roomId, body) {
  // Isolated SSE path — never touches main transcript / streamConverse.
  const ctrl = new AbortController();
  STATE.codeAbort = ctrl;
  STATE.codeStreaming = { text: "" };
  renderCodeStream();
  let raf = 0;
  try {
    const res = await fetch(`/rooms/${roomId}/code/run/stream`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body), signal: ctrl.signal,
    });
    if (!res.ok || !res.body) {
      const d = await res.json().catch(() => ({}));
      throw new Error(_errDetail(d, res));
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "", done = null, errMsg = null;
    const paint = () => { raf = 0; renderCodeStream(); };
    while (true) {
      const { value, done: rdDone } = await reader.read();
      if (rdDone) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, i); buf = buf.slice(i + 2);
        let ev = null, dat = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) ev = line.slice(6).trim();
          else if (line.startsWith("data:")) dat = line.slice(5).trim();
        }
        if (ev === "delta") {
          const chunk = (JSON.parse(dat).text) || "";
          if (STATE.codeStreaming) {
            STATE.codeStreaming.text += chunk;
            if (!raf) raf = requestAnimationFrame(paint);
          }
        } else if (ev === "done") { done = JSON.parse(dat); }
        else if (ev === "error") { errMsg = JSON.parse(dat).message || "stream error"; }
      }
    }
    if (raf) cancelAnimationFrame(raf);
    if (errMsg) throw new Error(errMsg);
    if (!done) throw new Error("code stream ended without done");
    return done;
  } finally {
    STATE.codeAbort = null;
    STATE.codeStreaming = null;
  }
}

async function codeSend() {
  if (!STATE.room) return;
  if (STATE.codeStreaming) { codeStatus("code seat already working…"); return; }
  const input = $("#code-input");
  const text = (input && input.value || "").trim();
  if (!text) return;
  const seat = ($("#code-seat") && $("#code-seat").value)
    || (STATE.room.code_seats && STATE.room.code_seats[0]);
  if (!seat) { codeStatus("pick a code seat first."); return; }
  const roomId = STATE.room.id;
  const mainCountBefore = (STATE.turns || []).length;
  const mode = STATE.codeMode || "build";
  const reasoning = STATE.codeReasoning || ($("#code-reasoning") && $("#code-reasoning").value) || "";
  codeStatus(`${seat} · ${mode}${reasoning ? " · " + reasoning : ""}…`, true);
  try {
    input.value = "";
    // optimistic human turn in the CODE stream only (tagged so we can drop it on commit)
    const optimistic = {
      role: "human", speaker: "human", text,
      meta: { code_mode: mode, seat, reasoning: reasoning || "default", _optimistic: true },
    };
    STATE.codeTurns = (STATE.codeTurns || []).concat([optimistic]);
    renderCodeStream();
    const data = await streamCodeSeat(roomId, { prompt: text, seat, mode, reasoning });
    if (STATE.room && STATE.room.id === roomId) {
      // authoritative code.jsonl replaces optimistic bubble (avoids double human on retry/done)
      STATE.codeTurns = data.code_turns || STATE.codeTurns.filter((t) => !(t.meta && t.meta._optimistic));
      STATE.outbox = data.outbox || STATE.outbox;
      renderCodePane();
    }
    // isolation invariant: main transcript length must not grow from a code-pane send
    if ((STATE.turns || []).length !== mainCountBefore) {
      codeStatus("warning: main transcript changed during code send");
    } else {
      codeStatus("done");
    }
  } catch (e) {
    // drop optimistic-only bubble if nothing was committed; keep server-backed turns
    STATE.codeTurns = (STATE.codeTurns || []).filter((t) => !(t.meta && t.meta._optimistic && t.text === text));
    renderCodeStream();
    if (e && e.name === "AbortError") codeStatus("stopped.");
    else codeStatus(`code failed: ${e.message}`);
  }
}

// ===== wiring ================================================================
$("#send-btn").addEventListener("click", send);
// attach files: pick (button → hidden input) or drop onto the composer (Phase 22)
$("#attach-btn").addEventListener("click", () => $("#file-input").click());
$("#file-input").addEventListener("change", (e) => { stageFiles(e.target.files); e.target.value = ""; });
(function wireFileDrop() {
  const composer = document.querySelector(".composer"); if (!composer) return;
  const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
  ["dragenter", "dragover"].forEach((ev) => composer.addEventListener(ev, (e) => { stop(e); composer.classList.add("dropping"); }));
  ["dragleave", "drop"].forEach((ev) => composer.addEventListener(ev, (e) => {
    stop(e);
    if (ev === "dragleave" && composer.contains(e.relatedTarget)) return;   // still inside → keep highlight
    composer.classList.remove("dropping");
  }));
  composer.addEventListener("drop", (e) => {
    const files = e.dataTransfer && e.dataTransfer.files;
    if (files && files.length) stageFiles(files);
  });
})();
// The rail lives outside .workspace, but showing it still shrinks .workspace's live width —
// so applyUI()'s enforcePaneFit() re-check is what keeps the viewer/margin clamps honest.
$("#traj-toggle").addEventListener("click", () => setUI({ trajectory_open: !STATE.ui.trajectory_open }));
$("#margin-toggle").addEventListener("click", () => (STATE.marginOpen ? closeMargin() : openMargin()));
$("#margin-close").addEventListener("click", closeMargin);
$("#margin-send").addEventListener("click", marginSend);
// Phase 39 — code seat pane + outbox
const _codeToggle = $("#code-toggle");
if (_codeToggle) _codeToggle.addEventListener("click", () => (STATE.codeOpen ? closeCodePane() : openCodePane()));
const _codeClose = $("#code-close");
if (_codeClose) _codeClose.addEventListener("click", closeCodePane);
const _codeSend = $("#code-send");
if (_codeSend) _codeSend.addEventListener("click", codeSend);
const _codeInput = $("#code-input");
if (_codeInput) _codeInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); codeSend(); }
});
document.querySelectorAll(".code-mode").forEach((btn) => {
  btn.addEventListener("click", () => {
    STATE.codeMode = btn.dataset.mode || "build";
    renderCodeModes();
  });
});
const _codeReason = $("#code-reasoning");
if (_codeReason) _codeReason.addEventListener("change", (e) => {
  STATE.codeReasoning = e.target.value || "";
});
const _channelMode = $("#channel-mode");
if (_channelMode) _channelMode.addEventListener("change", async (e) => {
  if (!STATE.room) return;
  const v = e.target.value;
  STATE.room.channel_mode = v;
  try { await api(`/rooms/${STATE.room.id}`, "PUT", { channel_mode: v }); } catch (_e) { /* */ }
});
const _codeSeat = $("#code-seat");
if (_codeSeat) _codeSeat.addEventListener("change", async (e) => {
  if (!STATE.room) return;
  const v = e.target.value;
  const seats = v ? [v] : [];
  STATE.room.code_seats = seats;
  try { await api(`/rooms/${STATE.room.id}`, "PUT", { code_seats: seats }); } catch (_e) { /* */ }
  renderCodePane();
});
(function wireCodeSplitter() {
  const rez = $("#code-splitter"); if (!rez) return;
  let dragging = false;
  rez.addEventListener("mousedown", (e) => { dragging = true; e.preventDefault(); });
  window.addEventListener("mousemove", (e) => {
    if (!dragging || !STATE.codeOpen) return;
    // code pane sits between main and margin: width = distance from splitter to right edge of code area
    const pane = $("#code-pane"); if (!pane) return;
    const rect = pane.getBoundingClientRect();
    // dragging the left edge of the code pane
    const rightEdge = rect.right;
    const marginStuff = STATE.marginOpen ? marginWidth() + SPLITTER_PX : 0;
    const dynMax = Math.max(360, workspaceWidth() - MIN_MAIN - SPLITTER_PX - marginStuff);
    const w = Math.max(360, Math.min(dynMax, rightEdge - e.clientX));
    if (STATE.room) STATE.room.code_pane_width = w;
    pane.style.width = w + "px";
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    if (STATE.room && STATE.room.code_pane_width != null) {
      api(`/rooms/${STATE.room.id}`, "PUT", { code_pane_width: STATE.room.code_pane_width }).catch(() => {});
    }
  });
})();
$("#margin-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); marginSend(); }
});
$("#margin-model").addEventListener("change", async (e) => {
  const v = e.target.value; if (!v || !STATE.room) return;
  STATE.room.margin_model = v;
  try { await api(`/rooms/${STATE.room.id}`, "PUT", { margin_model: v }); } catch (err) { /* non-fatal */ }
});
(function wireMarginSplitter() {
  const rez = $("#margin-splitter"); let dragging = false;
  rez.addEventListener("mousedown", (e) => { dragging = true; e.preventDefault(); });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    // margin is the rightmost pane → right edge is the viewport edge. Dynamic max keeps the
    // transcript ≥ MIN_MAIN even with the viewer open to its left (Phase 34.3).
    const viewerStuff = STATE.viewerOpen ? viewerWidth() + SPLITTER_PX : 0;
    const dynMax = Math.min(640, workspaceWidth() - MIN_MAIN - SPLITTER_PX - viewerStuff);
    const w = Math.max(240, Math.min(dynMax, window.innerWidth - e.clientX));
    if (STATE.room) STATE.room.splitter_width = w;
    $("#margin").style.width = w + "px";
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return; dragging = false;
    if (STATE.room) api(`/rooms/${STATE.room.id}`, "PUT", { splitter_width: STATE.room.splitter_width }).catch(() => {});
  });
})();
$("#viewer-close").addEventListener("click", closeViewer);
(function wireViewerSplitter() {
  const rez = $("#viewer-splitter"); if (!rez) return;
  let dragging = false;
  rez.addEventListener("mousedown", (e) => { dragging = true; e.preventDefault(); });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    // after 34.1 the viewer sits BETWEEN the transcript and the margin — so when the margin
    // is open the viewer's right edge is inset by the margin (+ its splitter), not the
    // viewport edge. Dynamic max keeps the transcript ≥ MIN_MAIN (Phase 34.3).
    const marginStuff = STATE.marginOpen ? marginWidth() + SPLITTER_PX : 0;
    const rightEdge = window.innerWidth - marginStuff;
    const dynMax = workspaceWidth() - MIN_MAIN - SPLITTER_PX - marginStuff;   // only limit: keep the transcript ≥ MIN_MAIN
    const w = Math.max(320, Math.min(dynMax, rightEdge - e.clientX));
    if (STATE.room) STATE.room.viewer_width = w;
    $("#viewer").style.width = w + "px";
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return; dragging = false;
    if (STATE.room) api(`/rooms/${STATE.room.id}`, "PUT", { viewer_width: STATE.room.viewer_width }).catch(() => {});
  });
})();
// window resize (debounced) → re-check coexistence; the sidebar toggle path re-checks via
// applyUI, and the sidebar drag via its own mouseup (Phase 34.3).
let _fitTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(_fitTimer);
  _fitTimer = setTimeout(() => { enforcePaneFit(); drawTrajGraph(); }, 150);   // row spacing tracks rail height
});
$("#input").addEventListener("keydown", (e) => {
  // Enter sends; Shift+Enter inserts a newline. isComposing guard: don't swallow
  // an IME candidate-commit (also pressed via Enter) as a send.
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
});
$("#mode").addEventListener("change", () => {
  syncModeUI();
  // reveal the machinery you just chose — a non-converse mode's controls must be visible,
  // not just active (Phase 35.1/35.3). Manual collapse (the toggle) still works after.
  if (currentMode() !== "converse") setAdvanced(true); else updateModeChip();
  STATE.paintDots = null;   // the state changed under the dots: they re-derive from it (38.4)
  drawTrajGraph();          // the default-future ghost previews the selection this compiles to (38.3)
});
// Any composer-state change moves the ghost — and drops a non-compiling paint overlay: the
// dots are a VIEW over the selection state, and the picker just changed that state (38.4).
// Covers the addressee and every control inside the disclosure (panel boxes, judges, seats —
// change events bubble to the container).
const composerMoved = () => { STATE.paintDots = null; drawTrajGraph(); };
$("#addressee").addEventListener("change", composerMoved);
$("#composer-advanced").addEventListener("change", composerMoved);
$("#mode-toggle").addEventListener("click", () => setAdvanced(!STATE.advancedOpen));  // open/close the disclosure
$("#new-room-btn").addEventListener("click", newRoom);
$("#room-settings-btn").addEventListener("click", openRoomSettings);

// how many trailing turns the last round spans (last human turn → end) — for the confirm.
function lastRoundSize() {
  const ts = STATE.turns;
  for (let i = ts.length - 1; i >= 0; i--) if (ts[i].role === "human") return ts.length - i;
  return ts.length;
}
$("#rollback-btn").addEventListener("click", async () => {
  if (!STATE.room || !STATE.turns.length) return;
  const n = lastRoundSize();
  if (!confirm(`Roll back the last round? Removes the last ${n} turn${n === 1 ? "" : "s"} from “${STATE.room.title}” (kept in rolledback.jsonl — recoverable).`)) return;
  const roomId = STATE.room.id;
  try {
    const data = await api(`/rooms/${roomId}/rollback`, "POST");
    if (STATE.room && STATE.room.id === data.room_id) {
      adoptRoom(data.transcript);
      await markRead(roomId, data.transcript.turn_count);
    }
    await refreshRooms();
    banner(`Rolled back ${data.removed} turn${data.removed === 1 ? "" : "s"}.`);
  } catch (e) { banner(e.message); }
});
$("#room-settings-close").addEventListener("click", () => $("#room-settings-overlay").classList.add("hidden"));
$("#room-settings-save").addEventListener("click", saveRoomSettings);

// sidebar collapse + resize (state lives server-side in ui.json)
async function setUI(patch) {
  STATE.ui = { ...STATE.ui, ...patch }; applyUI();
  try { await api("/ui", "PUT", patch); } catch (e) { /* non-fatal */ }
}
$("#sidebar-collapse").addEventListener("click", () => setUI({ sidebar_collapsed: true }));
$("#sidebar-expand").addEventListener("click", () => setUI({ sidebar_collapsed: false }));
(function wireResizer() {
  const rez = $("#sidebar-resizer"); let dragging = false;
  rez.addEventListener("mousedown", (e) => { dragging = true; e.preventDefault(); });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const w = Math.max(180, Math.min(480, e.clientX));
    STATE.ui.sidebar_width = w; $("#sidebar").style.width = w + "px";
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return; dragging = false;
    enforcePaneFit();   // a wider sidebar shrinks the workspace → re-check coexistence (Phase 34.3)
    api("/ui", "PUT", { sidebar_width: STATE.ui.sidebar_width }).catch(() => {});
  });
})();

// transcript ↔ composer divider: drag the Y axis to resize the composer height.
// The bar sits at the viewport bottom, so height ≈ innerHeight − cursorY (clamped).
(function wireComposerResizer() {
  const rez = $("#composer-resizer"); if (!rez) return;
  const composer = document.querySelector(".composer");
  let dragging = false;
  rez.addEventListener("mousedown", (e) => { dragging = true; e.preventDefault(); });
  window.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const h = composerClamp(window.innerHeight - e.clientY);
    STATE.ui.composer_height = h; composer.style.height = h + "px";
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return; dragging = false;
    api("/ui", "PUT", { composer_height: STATE.ui.composer_height }).catch(() => {});
  });
})();

// ===== model-management panel (Phase 7; unchanged behaviour) =================
async function refreshParticipants() {
  const part = await api("/participants");
  STATE.participants = part.participants || [];
  STATE.globalJudge = part.research_judge || STATE.globalJudge;
  renderComposerPickers(); render();
  reseedChangedWindows();   // fire-and-forget: keep the seeded window current (Phase 24)
}

// When a fresh /models headline differs from the seeded config window, re-seed it once
// (so the "changed" dot clears next refresh). Guarded per-key per session — a single
// PUT per genuine change, never a loop. The "reduced" dot (effective < headline) stays.
const _reseeded = new Set();
async function reseedChangedWindows() {
  for (const p of STATE.participants) {
    if (p.window_changed && p.headline_window && !_reseeded.has(p.name)) {
      _reseeded.add(p.name);
      try { await api(`/providers/${p.name}`, "PUT", { context_window: p.headline_window }); } catch (e) { /* non-fatal */ }
    }
  }
}

function providerCard(p) {
  let localAuth = p.auth_mode;   // pending UI state until save
  const card = el("div", "pcard");
  card.setAttribute("data-name", p.name);
  const head = el("div", "pcard-head");
  head.append(dot(p.color));
  const nm = el("span", "pcard-name"); nm.style.color = p.color; nm.textContent = p.name; head.append(nm);
  const adp = el("span", "adapter-tag"); adp.textContent = p.backend; head.append(adp);
  const pill = el("span", "pstatus " + p.status); pill.textContent = p.status; head.append(pill);
  card.append(head);

  const grid = el("div", "pgrid"); card.append(grid);
  const actions = el("div", "pcard-actions"); card.append(actions);
  const dl = el("datalist"); dl.id = "dl-" + p.name;
  let baseInput, modelInput, keyInput, enabledInput, reasoningInput, websearchInput, ctxInput;

  function buildGrid() {
    grid.innerHTML = "";
    grid.append(lbl("mode"));
    const cb = el("input"); cb.type = "checkbox"; cb.checked = localAuth === "cli"; cb.id = "cli-" + p.name;
    const cbl = el("label", "authtoggle"); cbl.append(cb, document.createTextNode(" use CLI subscription (no key)"));
    cb.addEventListener("change", () => { localAuth = cb.checked ? "cli" : "api"; buildGrid(); buildActions(); });
    const modeCell = el("div"); modeCell.append(cbl); grid.append(modeCell);

    if (localAuth === "api") {
      grid.append(lbl("base_url"));
      baseInput = el("input"); baseInput.type = "text"; baseInput.value = p.base_url || ""; grid.append(baseInput);
    } else {
      grid.append(lbl(""));
      const note = el("div", "cli-note");
      note.textContent = "use SuperGrok via Grok Build — subscription, no key";
      grid.append(note);
    }

    grid.append(lbl("model"));
    modelInput = el("input"); modelInput.type = "text"; modelInput.value = p.model || "";
    modelInput.setAttribute("list", dl.id);
    const mcell = el("div"); mcell.append(modelInput, dl); grid.append(mcell);

    if (localAuth === "api") {
      grid.append(lbl("api key"));
      keyInput = el("input"); keyInput.type = "password"; keyInput.value = "";   // never prefilled
      keyInput.placeholder = p.key_last4 ? `set ····${p.key_last4} — blank to keep` : "no key set";
      grid.append(keyInput);
    } else {
      keyInput = null;   // cli rows cannot hold a key
    }

    grid.append(lbl("enabled"));
    enabledInput = el("input"); enabledInput.type = "checkbox"; enabledInput.checked = p.enabled;
    const ecell = el("div"); ecell.append(enabledInput); grid.append(ecell);

    grid.append(lbl("reasoning"));
    reasoningInput = el("input"); reasoningInput.type = "checkbox"; reasoningInput.checked = !!p.reasoning;
    const rl = el("label", "authtoggle");
    rl.append(reasoningInput, document.createTextNode(" show reasoning (best-effort; may add cost)"));
    const rcell = el("div"); rcell.append(rl); grid.append(rcell);

    grid.append(lbl("web search"));
    websearchInput = el("input"); websearchInput.type = "checkbox"; websearchInput.checked = !!p.web_search;
    const wl = el("label", "authtoggle");
    wl.append(websearchInput, document.createTextNode(" search the web on research turns (bills per search)"));
    const wcell = el("div"); wcell.append(wl); grid.append(wcell);

    grid.append(lbl("context window"));
    ctxInput = el("input"); ctxInput.type = "number"; ctxInput.min = "0";
    ctxInput.value = p.context_window || ""; ctxInput.placeholder = "tokens (for the fill gauge)";
    const ccell = el("div"); ccell.append(ctxInput); grid.append(ccell);
  }

  function buildActions() {
    actions.innerHTML = "";
    const test = el("button"); test.textContent = "test";
    test.addEventListener("click", async () => {
      test.disabled = true; pill.className = "pstatus testing"; pill.textContent = "testing…";
      try {
        const r = await api(`/providers/${p.name}/test`, "POST");
        pill.className = "pstatus " + (r.ok ? "ok" : "error");
        pill.textContent = r.ok ? "ok" : "error";
        banner(r.ok ? null : `${p.name} test: ${r.error}`);
      } catch (e) { pill.className = "pstatus error"; pill.textContent = "error"; banner(e.message); }
      finally { test.disabled = false; }
    });
    actions.append(test);

    if (localAuth === "api") {
      const refresh = el("button"); refresh.textContent = "refresh models";
      refresh.addEventListener("click", async () => {
        refresh.disabled = true;
        try {
          const { models } = await api(`/providers/${p.name}/models`);
          dl.innerHTML = "";
          models.forEach((m) => { const o = el("option"); o.value = m; dl.append(o); });
          banner(`${p.name}: ${models.length} models — click the model field to pick`);
        } catch (e) {
          banner(`${p.name} models: ${e.message} — type the id manually`);  // fallback to typed id
        } finally { refresh.disabled = false; }
      });
      actions.append(refresh);
    }

    const right = el("span", "right");
    const save = el("button"); save.textContent = "save";
    save.addEventListener("click", async () => {
      const body = { enabled: enabledInput.checked, auth_mode: localAuth,
                     model: modelInput.value.trim(), reasoning: reasoningInput.checked,
                     web_search: websearchInput.checked,
                     context_window: parseInt(ctxInput.value, 10) || 0 };
      if (localAuth === "api") {
        body.base_url = baseInput.value.trim();
        if (keyInput && keyInput.value) body.api_key = keyInput.value;   // ONLY a typed value is a new key
      }   // cli: never sends api_key
      try { await api(`/providers/${p.name}`, "PUT", body); await openProviders(); await refreshParticipants(); banner(null); }
      catch (e) { banner(e.message); }
    });
    const del = el("button", "btn-danger"); del.textContent = "delete";
    del.addEventListener("click", async () => {
      if (!confirm(`Delete provider "${p.name}"? (removes its key too)`)) return;
      try { await api(`/providers/${p.name}`, "DELETE"); await openProviders(); await refreshParticipants(); }
      catch (e) { banner(e.message); }
    });
    right.append(save, del); actions.append(right);
  }

  buildGrid(); buildActions();
  return card;
}

// OR model catalog for the add-a-model dropdown — fetched once per overlay open
// (best-effort; reuses the server-side cached /models). Populates the datalist and
// is consulted on add to seed metadata defaults (window, reasoning).
let _orModels = [];
async function loadOrModels() {
  const dl = $("#add-model-list"); if (!dl) return;
  try {
    const { models } = await api("/or-models");
    _orModels = models || [];
    dl.innerHTML = "";
    _orModels.forEach((m) => {
      const o = el("option"); o.value = m.id;
      const win = m.context_length ? ` · ${fmtTokens(m.context_length)} ctx` : "";
      o.label = m.id + win;                               // shown beside the id where supported
      dl.append(o);
    });
  } catch (e) { _orModels = []; }                          // no OR key → typed id still works
}

async function openProviders() {
  const data = await api("/providers");
  const list = $("#provider-list"); list.innerHTML = "";
  data.providers.forEach((p) => list.append(providerCard(p)));
  loadOrModels();                                          // populate the add-model dropdown (async, non-blocking)
  $("#judge-select").innerHTML = data.providers
    .map((p) => `<option value="${p.name}"${p.name === data.research_judge ? " selected" : ""}>${p.name}</option>`).join("");
  $("#export-dir").value = "";        // empty by default — the stored path is the "current:" line
  renderExportCurrent();
  $("#artifacts-dir").value = "";
  renderArtifactsCurrent();
  renderThemeControls();
  $("#providers-overlay").classList.remove("hidden");
}

function renderArtifactsCurrent() {
  const el = $("#artifacts-current"); if (!el) return;
  const v = (STATE.ui.artifacts_dir || "").trim();
  el.textContent = v ? `current: ${v}` : "current: (off — copy still works)";
}
$("#artifacts-save").addEventListener("click", async () => {
  const v = $("#artifacts-dir").value.trim();
  if (!v) { banner("Paste a folder path to change it — current setting kept."); return; }
  try {
    STATE.ui = await api("/ui", "PUT", { artifacts_dir: v });
    $("#artifacts-dir").value = "";
    renderArtifactsCurrent();
    banner("Artifacts folder saved.");
  } catch (e) { banner(e.message); }
});

// Prefilled directory/name fields: select-all on focus so typing or pasting a new
// value REPLACES it instead of appending onto the old path.
["#export-dir", "#artifacts-dir", "#display-name"].forEach((sel) => {
  const e = $(sel); if (e) e.addEventListener("focus", () => e.select());
});

$("#display-name-save").addEventListener("click", async () => {
  const v = $("#display-name").value.trim();
  STATE.ui.display_name = v;
  render();   // relabel human turns on screen immediately
  try { STATE.ui = await api("/ui", "PUT", { display_name: v }); banner(v ? `The app will call you "${v}".` : "Name reset to “human”."); }
  catch (e) { banner(e.message); }
});

function renderExportCurrent() {
  const el = $("#export-current"); if (!el) return;
  const v = (STATE.ui.export_dir || "").trim();
  el.textContent = v ? `current: ${v}` : "current: (off — no export)";
}

// accent hue swatches — picking one recolours the whole UI and persists to ui.json
const ACCENT_HUES = [233, 255, 290, 330, 25, 75, 145, 190];
function renderAccentSwatches() {
  const box = $("#accent-swatches"); if (!box) return;
  box.innerHTML = "";
  const cur = Number(STATE.ui.accent_hue);
  for (const h of ACCENT_HUES) {
    const b = el("button", "accent-swatch" + (h === cur ? " sel" : ""));
    b.style.background = `oklch(0.6 0.15 ${h})`;
    b.title = `hue ${h}`;
    b.addEventListener("click", async () => {
      STATE.ui.accent_hue = h; currentHue = h; applyAccent(h); renderAccentSwatches();
      try { await api("/ui", "PUT", { accent_hue: h }); } catch (e) { /* non-fatal */ }
    });
    box.append(b);
  }
}

// segmented control: builds buttons for {options}, marks the current, applies + persists
function renderSeg(boxId, options, current, onPick) {
  const box = $(boxId); if (!box) return;
  box.innerHTML = "";
  for (const o of options) {
    const b = el("button", current === o.value ? "sel" : "");
    b.textContent = o.label;
    b.addEventListener("click", () => onPick(o.value));
    box.append(b);
  }
}
function renderThemeControls() {
  renderSeg("#thememode-opts",
    [{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }, { value: "system", label: "System" }],
    STATE.ui.theme_mode || "dark",
    async (v) => { STATE.ui.theme_mode = v; applyThemeMode(v); renderThemeControls();
                   try { await api("/ui", "PUT", { theme_mode: v }); } catch (e) {} });
  renderAccentSwatches();
  renderSeg("#brightness-opts",
    [{ value: "soft", label: "Soft" }, { value: "default", label: "Default" }, { value: "crisp", label: "Crisp" }],
    STATE.ui.text_brightness || "default",
    async (v) => { STATE.ui.text_brightness = v; currentLevel = v; applyBrightness(v); renderThemeControls();
                   try { await api("/ui", "PUT", { text_brightness: v }); } catch (e) {} });
  renderSeg("#fontsize-opts",
    [{ value: "compact", label: "Compact" }, { value: "default", label: "Default" }, { value: "large", label: "Large" },
     { value: "xlarge", label: "XL" }, { value: "huge", label: "XXL" }],
    STATE.ui.font_scale || "default",
    async (v) => { STATE.ui.font_scale = v; applyFontScale(v); renderThemeControls();
                   try { await api("/ui", "PUT", { font_scale: v }); } catch (e) {} });
  $("#display-name").value = STATE.ui.display_name || "";
}

$("#export-save").addEventListener("click", async () => {
  const v = $("#export-dir").value.trim();
  if (!v) { banner("Paste a folder path to change it — current setting kept."); return; }
  try {
    STATE.ui = await api("/ui", "PUT", { export_dir: v });
    $("#export-dir").value = "";              // clear for the next paste; stored value is the current: line
    renderExportCurrent();
    banner("Export folder saved.");
  } catch (e) { banner(e.message); }
});

// settings tabs (Providers / Theme / Data) — view-switching, no new persistence
function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-pane").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== name));
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));

$("#providers-btn").addEventListener("click", () => { switchTab("providers"); openProviders().catch((e) => banner(e.message)); });
$("#providers-close").addEventListener("click", () => $("#providers-overlay").classList.add("hidden"));
$("#judge-select").addEventListener("change", async (e) => {
  try { await api("/research-judge", "PUT", { name: e.target.value }); } catch (err) { banner(err.message); }
});
$("#add-btn").addEventListener("click", async () => {
  const model = $("#add-model").value.trim();
  const body = { name: $("#add-name").value.trim(), base_url: $("#add-base").value.trim(),
                 model, api_key: $("#add-key").value || null };
  // OR-dropdown pick → metadata-seeded defaults (window + reasoning), and default the
  // base_url to OpenRouter when picking an OR model into an empty base.
  const meta = _orModels.find((m) => m.id === model);
  if (meta) {
    if (meta.context_length) body.context_window = meta.context_length;
    body.reasoning = !!meta.reasoning;
    if (!body.base_url) body.base_url = "https://openrouter.ai/api/v1";
  }
  if (!body.name || !body.base_url) { banner("name and base_url required"); return; }
  try {
    await api("/providers", "POST", body);
    ["add-name", "add-base", "add-model", "add-key"].forEach((i) => ($("#" + i).value = ""));
    await openProviders(); await refreshParticipants(); banner(null);
  } catch (e) { banner(e.message); }
});

// ===== Ctrl/Cmd+K room switcher palette (Phase 31.4) =========================
// Keyboard-first jump-to-room. No new endpoint: STATE.rooms already carries title,
// tags, participants and last_ts (recon §5). Reuses the .overlay/.overlay-card skeleton
// and the showPreview rendering vocabulary (participant dots + a relative date).
let _paletteSel = 0, _paletteRooms = [];
function paletteOpen() { const o = $("#palette-overlay"); return !!o && !o.classList.contains("hidden"); }

function paletteMatches(q) {
  const rooms = [...STATE.rooms];                                          // copy: never mutate STATE.rooms
  if (!q) return rooms.sort((a, b) => (b.last_ts || "").localeCompare(a.last_ts || ""));   // recent first
  const needle = q.toLowerCase();
  return rooms.filter((r) =>                                               // title primary, tags + participants secondary
    [r.title || "", ...(r.tags || []), ...(r.participants || [])].join(" ").toLowerCase().includes(needle));
}
function filterPalette() {
  _paletteRooms = paletteMatches($("#palette-input").value.trim());
  if (_paletteSel >= _paletteRooms.length) _paletteSel = Math.max(0, _paletteRooms.length - 1);
  renderPalette();
}
function renderPalette() {
  const list = $("#palette-list"); list.innerHTML = "";
  if (!_paletteRooms.length) {
    const e = el("div", "palette-empty"); e.textContent = STATE.rooms.length ? "no rooms match" : "no rooms yet";
    list.append(e); return;
  }
  _paletteRooms.forEach((r, i) => {
    const row = el("div", "palette-row" + (i === _paletteSel ? " sel" : ""));
    const t = el("span", "palette-title"); t.textContent = r.title || r.id; row.append(t);
    const dots = el("span", "palette-dots");
    (r.participants || []).forEach((k) => { const p = providerOf(k); dots.append(dot(p ? p.color : DOT_DEFAULT)); });
    row.append(dots);
    const when = el("span", "palette-when"); when.textContent = fmtDate(r.last_ts); row.append(when);
    row.addEventListener("mousedown", (e) => { e.preventDefault(); choosePalette(i); });   // fire before backdrop/blur
    row.addEventListener("mouseenter", () => { if (_paletteSel !== i) { _paletteSel = i; renderPalette(); } });
    list.append(row);
  });
}
function movePalette(d) {
  if (!_paletteRooms.length) return;
  _paletteSel = (_paletteSel + d + _paletteRooms.length) % _paletteRooms.length;
  renderPalette();
  const sel = $("#palette-list .palette-row.sel"); if (sel) sel.scrollIntoView({ block: "nearest" });
}
function choosePalette(i) {
  const r = _paletteRooms[i]; if (!r) return;
  closePalette();
  if (!STATE.room || r.id !== STATE.room.id) switchRoom(r.id);   // switchRoom → adopt → focusComposer (31.1)
  else focusComposer();                                         // already here → just land the caret
}
function openPalette() {
  if (paletteOpen()) return;
  const inp = $("#palette-input"); inp.value = ""; _paletteSel = 0;
  $("#palette-overlay").classList.remove("hidden");
  filterPalette();
  inp.focus({ preventScroll: true });
}
function closePalette() { $("#palette-overlay").classList.add("hidden"); }

// One dismissal grammar for EVERY overlay (Phase 31.4): click the backdrop (outside the
// card) or press Esc → close. Introduced with the palette and retrofitted to the two
// existing overlays so the app has one convention, not three. (Full ARIA focus-trap is
// out of scope for a local single-user app — autofocus + Esc is the bar.)
const _overlays = [];
function wireOverlayDismiss(overlaySel, onClose) {
  const ov = $(overlaySel); if (!ov) return;
  ov.addEventListener("mousedown", (e) => { if (e.target === ov) onClose(); });   // backdrop only, not the card
  _overlays.push({ ov, close: onClose });
}
function closeAnyOverlay() {   // Esc closes the open overlay (only one is open in practice)
  for (const o of _overlays) if (!o.ov.classList.contains("hidden")) { o.close(); return true; }
  return false;
}
wireOverlayDismiss("#palette-overlay", closePalette);
wireOverlayDismiss("#room-settings-overlay", () => $("#room-settings-overlay").classList.add("hidden"));
wireOverlayDismiss("#providers-overlay", () => $("#providers-overlay").classList.add("hidden"));

$("#palette-input").addEventListener("input", () => { _paletteSel = 0; filterPalette(); });

// The app's FIRST document-level key binding (recon §4 confirmed no collision). Ctrl/Cmd+K
// toggles the switcher from anywhere (incl. while the composer has focus); Esc closes any
// open overlay; arrows/Enter drive the palette ONLY while it's open — so Enter-to-send is
// untouched when it's closed.
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === "k" || e.key === "K") && !e.isComposing) {
    e.preventDefault(); paletteOpen() ? closePalette() : openPalette(); return;
  }
  if (e.key === "Escape") {
    // deliberate precedence (Phase 33.2): a transient overlay (palette/settings/providers)
    // closes before the persistent viewer pane. The margin stays non-Esc-dismissable.
    if (closeAnyOverlay()) { e.preventDefault(); return; }
    if (STATE.viewerOpen) { e.preventDefault(); closeViewer(); return; }
    return;
  }
  if (!paletteOpen()) return;
  if (e.key === "ArrowDown") { e.preventDefault(); movePalette(1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); movePalette(-1); }
  else if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); choosePalette(_paletteSel); }
});

// ===== boot ==================================================================
(async function boot() {
  syncModeUI();
  if (!libsReady()) banner("Markdown/sanitizer failed to load — rendering as plain text (safe).");
  try {
    STATE.ui = await api("/ui");
    applyUI();
    // reconstruct the theme from the server. Seed the module-scope ramp inputs, then
    // applyThemeMode() is the SINGLE repaint entry — it sets data-theme and re-runs
    // applyAccent + applyBrightness with mode-aware values (don't call them directly
    // here, or mode-aware output would be applied and then clobbered).
    currentHue = Number(STATE.ui.accent_hue) || 233;
    currentLevel = STATE.ui.text_brightness || "default";
    applyFontScale(STATE.ui.font_scale);
    applyThemeMode(STATE.ui.theme_mode || "dark");
    const part = await api("/participants");
    STATE.participants = part.participants || [];
    STATE.globalJudge = part.research_judge || "";
    const rooms = await api("/rooms");
    STATE.rooms = rooms.rooms || [];
    renderSidebar();
    if (rooms.active) {
      adoptRoom(await api(`/rooms/${rooms.active}/activate`, "POST"));
      await refreshRooms();
    } else {
      renderComposerPickers(); render();
    }
    restoreRoomComposer();         // init the disclosure/chip (maps empty → converse + auto, collapsed) (Phase 35)
    focusComposer();               // land the caret in the composer on load (Phase 31.1)
  } catch (e) { banner(`could not reach engine: ${e.message}`); }
})();
