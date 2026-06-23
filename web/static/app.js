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
  staged: [],                // composer-staged files [{filename, content}] (Phase 22)
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
  if (t.meta && t.meta.kind === "file") return renderFileTurn(t);   // attached document (Phase 22)
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

// A non-interactive provenance pill showing the API-reported served_model — glanceable
// (the served id as text, provider/ prefix stripped), not hidden behind a hover. The
// served string is the TRUTH vs the configured header label, so when they disagree the
// pill tints (warning) and spells out both. textContent only — never innerHTML.
function modelPill(t) {
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

function render() {
  $("#title").textContent = STATE.room ? STATE.room.title : "";
  $("#room-settings-btn").disabled = !STATE.room;
  $("#margin-toggle").disabled = !STATE.room;
  renderModelBar();
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
  const opts = (providerOf(k) || {}).effort_options;
  if (!opts || !opts.length) return null;
  const cur = (STATE.room && STATE.room.reasoning_effort && STATE.room.reasoning_effort[k]) || opts[opts.length - 1];
  const c = el("div", "mp-effort");
  const l = el("div", "mp-label"); l.append(boltIcon(), document.createTextNode(" reasoning effort")); c.append(l);
  const seg = el("div", "mp-seg");
  for (const o of opts) {                              // already ascending: left = less
    const b = el("button", o === cur ? "sel" : "");
    b.textContent = o;
    b.addEventListener("click", () => setRoomEffort(k, o));
    seg.append(b);
  }
  c.append(seg); return c;
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
  applyComposerHeight();
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
    reasoning_effort: view.reasoning_effort || {},
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
  STATE.staged = []; renderStagedFiles();   // staged files belong to the room you left
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
    //    panel reads "here's the document, now my question".
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
    // 2. the message turn (+ its model round) — one unified dispatch endpoint
    setStatus(modeStatus(sel), true);
    const data = await api(`/rooms/${roomId}/run`, "POST", sel);
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
  const m = currentMode();
  $("#converse-opts").classList.toggle("hidden", m !== "converse");
  $("#research-opts").classList.toggle("hidden", m !== "fusion" && m !== "mapping");   // shared panel params
  $("#sxs-opts").classList.toggle("hidden", m !== "side_by_side");
  $("#yesand-opts").classList.toggle("hidden", m !== "yes_and");
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
$("#mode").addEventListener("change", syncModeUI);
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
    [{ value: "compact", label: "Compact" }, { value: "default", label: "Default" }, { value: "large", label: "Large" }],
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
