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

// ===== state (no browser storage — the transcript is the single source) ======
let STATE = { participants: [], turns: [], active: false, title: "", path: "" };

function colorOf(s) {
  const p = STATE.participants.find((x) => x.name === s);
  if (p) return p.color;
  if (s === "human") return "#6ee7b7";
  if (s === "judge") return "#f0abfc";
  return "#9aa3b2";
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
  if (extra) { const e = document.createElement("span"); e.style.color = "var(--muted)"; e.textContent = " · " + extra; d.appendChild(e); }
  return d;
}
function $(s) { return document.querySelector(s); }

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

// ===== rendering =============================================================
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
  const who = t.role === "human" ? "human" : t.speaker;
  div.appendChild(whoLine(who, colorOf(who), (t.meta && t.meta.model) || ""));
  const body = document.createElement("div"); body.className = "body";
  renderMd(body, t.text); div.appendChild(body);
  return div;
}

function plainPreview(text, n = 160) { return (text || "").replace(/\s+/g, " ").trim().slice(0, n); }

function renderRound(b) {
  const div = document.createElement("div"); div.className = "round";
  if (b.prompt) {
    const pr = document.createElement("div"); pr.className = "prompt";
    pr.appendChild(whoLine("human", colorOf("human"), "research"));
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
      grid.appendChild(card);
    }
    div.appendChild(grid);
  }
  if (b.judge) {
    const syn = document.createElement("div"); syn.className = "synthesis";
    const n = b.panels.length;
    syn.appendChild(whoLine(b.judge.speaker, colorOf(b.judge.speaker), `synthesis · ${n} panelist${n === 1 ? "" : "s"}`));
    const body = document.createElement("div"); renderMd(body, b.judge.text); syn.appendChild(body);
    div.appendChild(syn);
  }
  return div;
}

function render() {
  $("#title").textContent = STATE.active ? STATE.title : "";
  const main = $("#stream"); main.innerHTML = "";
  if (!STATE.active) { main.innerHTML = '<div class="empty">No active transcript. Click <b>+ new</b> to start one.</div>'; return; }
  if (!STATE.turns.length) main.innerHTML = '<div class="empty">Empty room — send the first message.</div>';
  for (const b of groupTurns(STATE.turns)) main.appendChild(b.type === "round" ? renderRound(b) : renderConverse(b.turn));
  main.scrollTop = main.scrollHeight;
}

function renderAddressee() {
  const sel = $("#addressee");
  sel.innerHTML = '<option value="">auto (last AI)</option>' +
    STATE.participants.filter((p) => p.enabled).map((p) => `<option value="${p.name}">@${p.name}</option>`).join("");
}

async function refreshTranscriptList() {
  const { transcripts } = await api("/transcripts");
  const sel = $("#transcripts");
  if (!transcripts.length) { sel.innerHTML = "<option>— no transcripts —</option>"; return; }
  sel.innerHTML = transcripts.map((t) => `<option value="${t.path}"${t.path === STATE.path ? " selected" : ""}>${t.title}</option>`).join("");
}

function adoptTranscript(tr) {
  STATE.active = tr.active;
  STATE.title = tr.title || ""; STATE.path = tr.path || ""; STATE.turns = tr.turns || [];
  render();
}

// ===== compose ===============================================================
function currentMode() { return document.querySelector('input[name="mode"]:checked').value; }

async function send() {
  const input = $("#input"); const text = input.value.trim();
  if (!text) return;
  if (!STATE.active) { banner("Create a transcript first (+ new)."); return; }
  const mode = currentMode();
  $("#send-btn").disabled = true; banner(null);
  try {
    let data;
    if (mode === "research") {
      const n = STATE.participants.filter((p) => p.enabled).length;
      setStatus(`research: ${n} models thinking + judge… (can take a while)`, true);
      data = await api("/research", "POST", { prompt: text, effort: $("#effort").value });
    } else {
      const addressed_to = $("#addressee").value || null;
      setStatus(`converse: ${addressed_to ? "@" + addressed_to : "(last AI)"} thinking…`, true);
      data = await api("/converse", "POST", { prompt: text, addressed_to });
    }
    input.value = "";
    adoptTranscript(data.transcript);   // pure view: re-render from returned turns
    setStatus("");
  } catch (e) {
    setStatus(""); banner(`${mode} failed: ${e.message}`);
  } finally {
    $("#send-btn").disabled = false;
  }
}

function syncModeUI() {
  const research = currentMode() === "research";
  $("#research-opts").classList.toggle("hidden", !research);
  $("#converse-opts").classList.toggle("hidden", research);
}

// ===== wiring ================================================================
$("#send-btn").addEventListener("click", send);
$("#input").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); } });
document.querySelectorAll('input[name="mode"]').forEach((r) => r.addEventListener("change", syncModeUI));
$("#new-btn").addEventListener("click", async () => {
  const title = prompt("transcript title:"); if (!title) return;
  try { adoptTranscript(await api("/transcript", "POST", { title })); await refreshTranscriptList(); banner(null); }
  catch (e) { banner(e.message); }
});
$("#transcripts").addEventListener("change", async (e) => {
  try { adoptTranscript(await api("/transcript/select", "POST", { path: e.target.value })); banner(null); }
  catch (err) { banner(err.message); }
});

// ===== model-management panel (Phase 7) =====================================
function el(tag, cls) { const e = document.createElement(tag); if (cls) e.className = cls; return e; }
function lbl(t) { const e = el("label"); e.textContent = t; return e; }

async function refreshParticipants() {
  const part = await api("/participants");
  STATE.participants = part.participants || [];
  renderAddressee(); render();
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
  let baseInput, modelInput, keyInput, enabledInput;

  function buildGrid() {
    grid.innerHTML = "";
    // mode toggle — checking it makes the row structurally keyless (cli)
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
      const body = { enabled: enabledInput.checked, auth_mode: localAuth, model: modelInput.value.trim() };
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
  $("#providers-overlay").classList.remove("hidden");
}

$("#providers-btn").addEventListener("click", () => openProviders().catch((e) => banner(e.message)));
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
    const part = await api("/participants");
    STATE.participants = part.participants || [];
    renderAddressee();
    adoptTranscript(await api("/transcript"));
    await refreshTranscriptList();
  } catch (e) { banner(`could not reach engine: ${e.message}`); }
})();
