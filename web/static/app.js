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
const FONT_SCALE = { compact: 0.92, default: 1.0, large: 1.12 };
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

// ===== API ===================================================================
async function api(path, method, body) {
  const opts = { method: method || "GET" };
  if (body !== undefined) { opts.headers = { "Content-Type": "application/json" }; opts.body = JSON.stringify(body); }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `${res.status} ${res.statusText}`);
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
  const div = document.createElement("div");
  div.className = "turn" + (t.role === "human" ? " human" : "");
  const isHuman = t.role === "human";
  const fromMargin = t.meta && t.meta.from_margin;
  const extra = (fromMargin ? "from margin" : "") || (t.meta && t.meta.model) || "";
  // label uses the display name for human turns; dot colour stays keyed on "human"
  div.appendChild(whoLine(isHuman ? displayName() : t.speaker, colorOf(isHuman ? "human" : t.speaker), extra));
  const body = document.createElement("div"); body.className = "body";
  renderMd(body, t.text); div.appendChild(body);
  appendTurnFooter(div, t);                 // thinking + model pills, reasoning body below
  const ac = artifactControls(t); if (ac) div.appendChild(ac);
  return div;
}

function plainPreview(text, n = 160) { return (text || "").replace(/\s+/g, " ").trim().slice(0, n); }

// A non-interactive "model" pill: the API-reported served_model, revealed on hover
// via the native title attribute (attribute/textContent only — never innerHTML, so
// no parse of an untrusted string). Absent when served_model is. If it disagrees with
// the header's configured meta.model, a subtle warning tint flags the mismatch.
function modelPill(t) {
  const served = t.meta && t.meta.served_model;
  if (!served) return null;
  const pill = el("span", "model-pill");
  pill.textContent = "model";
  pill.title = served;                                   // hover reveals; safe (attribute)
  const configured = t.meta && t.meta.model;
  if (configured && configured !== served) pill.classList.add("mismatch");
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

function turnFooterParts(t) {
  const meta = t.meta || {};
  const hasReasoning = !!meta.reasoning;
  const served = meta.served_model;
  const sources = sourcesOf(meta);
  const trunc = truncBadge(meta);
  if (!hasReasoning && !served && !sources.length && !trunc) return null;
  const footer = el("div", "turn-footer");
  const bodies = [];
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
    footer.append(btn); bodies.push(body);               // thinking first…
  }
  if (served) footer.append(modelPill(t));               // …then model…
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
function artifactControls(t) {
  const blocks = extractMdBlocks(t.text);
  if (!blocks.length) return null;
  const wrap = el("div", "artifacts");
  blocks.forEach((content, i) => {
    const row = el("div", "artifact");
    const lab = el("span", "artifact-label");
    lab.textContent = `📄 markdown artifact${blocks.length > 1 ? " " + (i + 1) : ""}`;
    const copy = el("button", "artifact-btn"); copy.textContent = "copy";
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(content); copy.textContent = "copied ✓";
            setTimeout(() => (copy.textContent = "copy"), 1200); }
      catch (e) { banner("copy failed: " + e.message); }
    });
    const save = el("button", "artifact-btn"); save.textContent = "save";
    save.addEventListener("click", async () => {
      if (!STATE.room) return;
      try { const r = await api(`/rooms/${STATE.room.id}/artifact`, "POST", { content }); banner(`Saved ${r.path}`); }
      catch (e) { banner(e.message); }
    });
    row.append(lab, copy, save); wrap.append(row);
  });
  return wrap;
}

function renderRound(b) {
  const div = document.createElement("div"); div.className = "round";
  if (b.prompt) {
    const pr = document.createElement("div"); pr.className = "prompt";
    pr.appendChild(whoLine(displayName(), colorOf("human"), "research"));
    const body = document.createElement("div"); body.className = "body"; renderMd(body, b.prompt.text);
    pr.appendChild(body); div.appendChild(pr);
  }
  if (b.panels.length) {
    const grid = document.createElement("div"); grid.className = "panels";
    for (const p of b.panels) {
      const c = colorOf(p.speaker);
      const card = document.createElement("div"); card.className = "panel";
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
  if (b.judge) {
    const syn = document.createElement("div"); syn.className = "synthesis";
    const n = b.panels.length;
    const ff = b.judge.meta && b.judge.meta.judge_fallback_from;
    const extra = `synthesis · ${n} panelist${n === 1 ? "" : "s"}` + (ff ? ` · judge fell back from ${ff}` : "");
    syn.appendChild(whoLine(b.judge.speaker, colorOf(b.judge.speaker), extra));
    const body = document.createElement("div"); renderMd(body, b.judge.text); syn.appendChild(body);
    appendTurnFooter(syn, b.judge);         // synthesis provenance: thinking + model
    const ac = artifactControls(b.judge); if (ac) syn.appendChild(ac);
    div.appendChild(syn);
  }
  return div;
}

function render() {
  $("#title").textContent = STATE.room ? STATE.room.title : "";
  $("#room-settings-btn").disabled = !STATE.room;
  $("#margin-toggle").disabled = !STATE.room;
  renderTokenBar();
  const main = $("#stream"); main.innerHTML = "";
  if (!STATE.room) {
    main.innerHTML = '<div class="empty">No room yet. Click <b>+ new room</b> to start one.</div>';
    return;
  }
  if (!STATE.turns.length) {
    const roster = (STATE.room.participants || []).length;
    main.innerHTML = roster
      ? '<div class="empty">Empty room — send the first message.</div>'
      : '<div class="empty">Empty room. Pick this room\'s models with <b>models</b> (top-right) to begin.</div>';
    return;
  }
  for (const b of groupTurns(STATE.turns)) main.appendChild(b.type === "round" ? renderRound(b) : renderConverse(b.turn));
  main.scrollTop = main.scrollHeight;
}

// ===== composer pickers (scoped to the ACTIVE ROOM's roster) =================
function roomRoster() { return (STATE.room && STATE.room.participants) || []; }
function providerOf(key) { return STATE.participants.find((p) => p.name === key); }

function renderAddressee() {
  const sel = $("#addressee");
  const opts = roomRoster().map((k) => `<option value="${k}">@${k}</option>`).join("");
  sel.innerHTML = '<option value="">auto (last AI)</option>' + opts;
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

function renderComposerPickers() { renderAddressee(); renderPanelPick(); renderJudgePick(); }

// ===== token / context indicator =============================================
function fmtTokens(n) {
  if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M";
  if (n >= 1000) return Math.round(n / 1000) + "k";
  return "" + n;
}
// pre-send fill estimate: the synthesis-only forward view, ~chars/4 — same method
// for every provider, so it's a fill gauge, not a billing figure (hence the ~).
function estimateContextTokens() {
  let chars = 0;
  for (const t of STATE.turns) if (!(t.meta && t.meta.is_panelist_raw)) chars += (t.text || "").length;
  return Math.round(chars / 4);
}
// per-model spend share over the room's stored usage (Grok estimate-only → ~).
function modelPercents() {
  const per = {}; let total = 0, approx = false;
  for (const t of STATE.turns) {
    const u = t.meta && t.meta.usage;
    if (!u || t.role === "human") continue;        // model turns only carry usage
    const tok = (u.input || 0) + (u.output || 0);
    per[t.speaker] = (per[t.speaker] || 0) + tok; total += tok;
    if (!u.exact) approx = true;
  }
  return { per, total, approx };
}
function renderTokenBar() {
  const bar = $("#token-bar"); if (!bar) return;
  bar.innerHTML = "";
  if (!STATE.room || !roomRoster().length) return;
  const showTok = STATE.ui.show_token_estimate !== false;   // default on
  const showPct = !!STATE.ui.show_model_pct;                 // default off
  const fill = estimateContextTokens();
  const { per, total, approx } = modelPercents();
  for (const k of roomRoster()) {
    const p = providerOf(k);
    const win = p && p.context_window ? p.context_window : 0;
    const chip = el("span", "tchip");
    chip.append(dot(p ? p.color : DOT_DEFAULT));
    let txt = k;
    if (showTok) txt += ` ~${fmtTokens(fill)}${win ? " / " + fmtTokens(win) : ""}`;
    if (showPct) txt += ` ${approx ? "~" : ""}${total ? Math.round((per[k] || 0) / total * 100) : 0}%`;
    const s = el("span"); s.textContent = txt; chip.append(s); bar.append(chip);
  }
  // session total: real usage where the API gave it, estimate otherwise (~).
  let tot = 0, approx2 = false, any = false;
  for (const t of STATE.turns) {
    const u = t.meta && t.meta.usage;
    if (!u) continue;
    any = true; tot += (u.input || 0) + (u.output || 0);
    if (!u.exact) approx2 = true;
  }
  if (any) {
    const s = el("span", "tchip total");
    s.textContent = `session ${approx2 ? "~" : ""}${fmtTokens(tot)} tok`;
    bar.append(s);
  }
}

// ===== sidebar ===============================================================
function applyUI() {
  const sb = $("#sidebar");
  sb.style.width = (STATE.ui.sidebar_width || 260) + "px";
  sb.classList.toggle("collapsed", !!STATE.ui.sidebar_collapsed);
  $("#sidebar-expand").classList.toggle("hidden", !STATE.ui.sidebar_collapsed);
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
    if (r.unread && !(STATE.room && r.id === STATE.room.id)) row.append(el("span", "unread-dot"));
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
  STATE.room = {
    id: view.id, title: view.title,
    participants: view.participants || [], judge: view.judge || null,
    margin_model: view.margin_model || null,
    splitter_width: view.splitter_width || null,
    tags: view.tags || [],
  };
  STATE.turns = view.turns || [];
  if (view.margin_turns !== undefined) STATE.marginTurns = view.margin_turns || [];
  renderComposerPickers();
  render();
  renderMargin();                       // show THIS room's own margin
  if (STATE.marginOpen) applyMarginWidth();
}

async function markRead(id, count) {
  try { await api(`/rooms/${id}`, "PUT", { last_read_pos: count }); } catch (e) { /* non-fatal */ }
}

async function switchRoom(id) {
  banner(null); setStatus("");   // a background round's status must not bleed across rooms
  try {
    const view = await api(`/rooms/${id}/activate`, "POST");   // sets active + marks read
    adoptRoom(view);
    await refreshRooms();
  } catch (e) { banner(e.message); }
}

async function newRoom() {
  const title = prompt("room title:");
  if (!title) return;
  try {
    const data = await api("/rooms", "POST", { title });   // EMPTY room — forced decision
    adoptRoom(data.room);
    await refreshRooms();
    banner("New room — choose its models and judge in “models” (top-right) before researching.");
  } catch (e) { banner(e.message); }
}

// ===== compose ===============================================================
function currentMode() { return document.querySelector('input[name="mode"]:checked').value; }

async function send() {
  const input = $("#input"); const text = input.value.trim();
  if (!text) return;
  if (!STATE.room) { banner("Create a room first (+ new room)."); return; }
  const mode = currentMode();
  const roomId = STATE.room.id;            // the room this message belongs to
  banner(null);
  // Note: the send button is deliberately NOT globally disabled. A round may be
  // in flight in room A while the user switches to B and sends there; each send
  // captures its own roomId and the server serializes per-room. Disabling here
  // would defeat multi-room concurrency.
  try {
    let data;
    if (mode === "research") {
      const panel = pickedPanel();
      if (!panel.length) { banner("select at least one model for the research panel (or set the room's models)"); return; }
      const judge = $("#judge-pick").value;
      if (!judge) { banner("select a judge for this round (or set one in “models”)"); return; }
      setStatus(`research: ${panel.length} model${panel.length === 1 ? "" : "s"} working + ${judge} synthesizes…`, true);
      data = await api(`/rooms/${roomId}/research`, "POST", { prompt: text, effort: $("#effort").value, panel, judge });
    } else {
      const addressed_to = $("#addressee").value || null;
      setStatus(`converse: ${addressed_to ? "@" + addressed_to : "(last AI)"} responding…`, true);
      data = await api(`/rooms/${roomId}/converse`, "POST", { prompt: text, addressed_to });
    }
    input.value = "";
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
    setStatus(""); banner(`${mode} failed: ${e.message}`);
  }
}

function syncModeUI() {
  const research = currentMode() === "research";
  $("#research-opts").classList.toggle("hidden", !research);
  $("#converse-opts").classList.toggle("hidden", research);
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
  try {
    await api(`/rooms/${STATE.room.id}`, "PUT", { participants, judge, tags });
    STATE.room.participants = participants; STATE.room.judge = judge; STATE.room.tags = tags;
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

function applyMarginWidth() {
  const w = STATE.room && STATE.room.splitter_width;
  if (w) $("#margin").style.width = w + "px";
}

function openMargin() {
  if (!STATE.room) return;
  STATE.marginOpen = true;
  $("#margin").classList.remove("hidden");
  $("#margin-splitter").classList.remove("hidden");
  applyMarginWidth(); renderMargin();
}
function closeMargin() {
  STATE.marginOpen = false;
  $("#margin").classList.add("hidden");
  $("#margin-splitter").classList.add("hidden");
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
    // Concurrency: only paint into the margin if we're still in that room.
    if (STATE.room && STATE.room.id === data.room_id) {
      STATE.marginTurns = data.margin_turns || [];
      renderMargin(); marginStatus("");
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

// ===== wiring ================================================================
$("#send-btn").addEventListener("click", send);
$("#margin-toggle").addEventListener("click", () => (STATE.marginOpen ? closeMargin() : openMargin()));
$("#margin-close").addEventListener("click", closeMargin);
$("#margin-send").addEventListener("click", marginSend);
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
    const w = Math.max(240, Math.min(640, window.innerWidth - e.clientX));
    if (STATE.room) STATE.room.splitter_width = w;
    $("#margin").style.width = w + "px";
  });
  window.addEventListener("mouseup", () => {
    if (!dragging) return; dragging = false;
    if (STATE.room) api(`/rooms/${STATE.room.id}`, "PUT", { splitter_width: STATE.room.splitter_width }).catch(() => {});
  });
})();
$("#input").addEventListener("keydown", (e) => {
  // Enter sends; Shift+Enter inserts a newline. isComposing guard: don't swallow
  // an IME candidate-commit (also pressed via Enter) as a send.
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
});
document.querySelectorAll('input[name="mode"]').forEach((r) => r.addEventListener("change", syncModeUI));
$("#new-room-btn").addEventListener("click", newRoom);
$("#room-settings-btn").addEventListener("click", openRoomSettings);
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
    api("/ui", "PUT", { sidebar_width: STATE.ui.sidebar_width }).catch(() => {});
  });
})();

// ===== model-management panel (Phase 7; unchanged behaviour) =================
async function refreshParticipants() {
  const part = await api("/participants");
  STATE.participants = part.participants || [];
  STATE.globalJudge = part.research_judge || STATE.globalJudge;
  renderComposerPickers(); render();
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

async function openProviders() {
  const data = await api("/providers");
  const list = $("#provider-list"); list.innerHTML = "";
  data.providers.forEach((p) => list.append(providerCard(p)));
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

$("#chip-tokens").addEventListener("change", (e) => _chipToggle("show_token_estimate", e.target.checked));
$("#chip-pct").addEventListener("change", (e) => _chipToggle("show_model_pct", e.target.checked));
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
    [{ value: "compact", label: "Compact" }, { value: "default", label: "Default" }, { value: "large", label: "Large" }],
    STATE.ui.font_scale || "default",
    async (v) => { STATE.ui.font_scale = v; applyFontScale(v); renderThemeControls();
                   try { await api("/ui", "PUT", { font_scale: v }); } catch (e) {} });
  $("#display-name").value = STATE.ui.display_name || "";
  $("#chip-tokens").checked = STATE.ui.show_token_estimate !== false;
  $("#chip-pct").checked = !!STATE.ui.show_model_pct;
}

async function _chipToggle(key, checked) {
  STATE.ui[key] = checked; renderTokenBar();
  try { await api("/ui", "PUT", { [key]: checked }); } catch (e) { /* non-fatal */ }
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
  const body = { name: $("#add-name").value.trim(), base_url: $("#add-base").value.trim(),
                 model: $("#add-model").value.trim(), api_key: $("#add-key").value || null };
  if (!body.name || !body.base_url) { banner("name and base_url required"); return; }
  try {
    await api("/providers", "POST", body);
    ["add-name", "add-base", "add-model", "add-key"].forEach((i) => ($("#" + i).value = ""));
    await openProviders(); await refreshParticipants(); banner(null);
  } catch (e) { banner(e.message); }
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
  } catch (e) { banner(`could not reach engine: ${e.message}`); }
})();
