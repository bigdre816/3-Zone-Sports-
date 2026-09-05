"use strict";

const state = {
  config: null,
  session: sessionStorage.getItem("tz_session") || null,
  user: null,
  events: [],
  zoneFilter: "all",
  selected: null,
  ws: null,
  wsEventId: null,
};

const LIFECYCLE_NEXT = {
  scheduled: ["gray"], gray: ["yellow"], yellow: ["green"],
  green: ["live"], live: ["replay"], replay: ["archive"], archive: [],
};

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

function toast(msg, kind) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast " + (kind || "");
  setTimeout(() => t.classList.add("hidden"), 3200);
}

async function api(method, path, body) {
  const headers = {};
  if (state.session) headers["Authorization"] = "Bearer " + state.session;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const resp = await fetch(path, {
    method,
    headers,
    credentials: "include",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await resp.text();
  const data = text ? JSON.parse(text) : {};
  if (!resp.ok) {
    const err = new Error(data.error || resp.statusText);
    err.code = data.code;
    err.status = resp.status;
    throw err;
  }
  return data;
}

// -- auth --------------------------------------------------------------
async function login() {
  const account = $("#account").value;
  try {
    const res = await api("POST", "/api/auth/demo-login", { account });
    state.session = res.session_token;
    state.user = res.user;
    sessionStorage.setItem("tz_session", state.session);
    afterAuth();
    toast("Signed in as " + res.user.display_name, "ok");
  } catch (e) {
    toast("Sign in failed: " + e.message, "bad");
  }
}

function logout() {
  state.session = null;
  state.user = null;
  sessionStorage.removeItem("tz_session");
  closeWs();
  $("#logout-btn").classList.add("hidden");
  $("#login-btn").classList.remove("hidden");
  $("#who").textContent = "";
  $("#operator").classList.add("hidden");
  $("#events").innerHTML = "";
  $("#player").classList.add("hidden");
  $("#player-empty").classList.remove("hidden");
}

async function restoreSession() {
  if (!state.session) return;
  try {
    const res = await api("GET", "/api/me");
    state.user = res.user;
    afterAuth();
  } catch (e) {
    logout();
  }
}

function afterAuth() {
  $("#login-btn").classList.add("hidden");
  $("#logout-btn").classList.remove("hidden");
  $("#who").textContent = `${state.user.display_name} · ${state.user.role}`;
  const isOp = state.user.role === "operator" || state.user.role === "admin";
  $("#operator").classList.toggle("hidden", !isOp);
  loadEvents();
}

// -- catalog -----------------------------------------------------------
function renderZoneFilters() {
  const box = $("#zone-filters");
  box.innerHTML = "";
  const zones = ["all"].concat(state.config.zones || []);
  zones.forEach((z) => {
    const chip = el("span", "chip" + (state.zoneFilter === z ? " active" : ""), z);
    chip.addEventListener("click", () => { state.zoneFilter = z; renderCatalog(); });
    box.appendChild(chip);
  });
}

async function loadEvents() {
  try {
    const res = await api("GET", "/api/events");
    state.events = res.events;
    renderZoneFilters();
    renderCatalog();
  } catch (e) {
    toast("Could not load events: " + e.message, "bad");
  }
}

function statusBadge(status) {
  const b = el("span", "badge st-" + status, status);
  return b;
}

function renderCatalog() {
  const box = $("#events");
  box.innerHTML = "";
  let events = state.events;
  if (state.zoneFilter !== "all") events = events.filter((e) => e.zone === state.zoneFilter);
  const order = { live: 0, green: 1, yellow: 2, gray: 3, scheduled: 4, replay: 5, archive: 6 };
  events = events.slice().sort((a, b) => (order[a.status] - order[b.status]));
  if (!events.length) { box.appendChild(el("div", "empty", "No events in this zone.")); return; }
  events.forEach((ev) => {
    const card = el("div", "card");
    const h = el("div", "row");
    h.appendChild(el("h3", null, ev.title));
    h.appendChild(statusBadge(ev.status));
    card.appendChild(h);
    const meta = el("div", "row");
    meta.appendChild(el("span", "muted zone", ev.zone + " · " + ev.category));
    const feed = el("span", "pill " + (ev.feed_healthy ? "ok" : "bad"),
      ev.active_source + (ev.feed_healthy ? " ✓" : " ⚠"));
    meta.appendChild(feed);
    card.appendChild(meta);
    const sb = ev.scoreboard || {};
    if (sb.home !== undefined) {
      card.appendChild(el("div", "muted", `Score ${sb.home}-${sb.away} · ${sb.period || ""} ${sb.clock || ""}`));
    }
    const btn = el("button", null, ev.status === "replay" ? "Watch replay" : "Open");
    btn.addEventListener("click", () => openEvent(ev.event_id));
    card.appendChild(btn);
    box.appendChild(card);
  });
}

// -- player + socket ---------------------------------------------------
function logSocket(line) {
  const box = $("#socket-log");
  const stamp = new Date().toLocaleTimeString();
  box.textContent += `[${stamp}] ${line}\n`;
  box.scrollTop = box.scrollHeight;
}

function closeWs() {
  if (state.ws) {
    try { state.ws.close(); } catch (_) {}
    state.ws = null;
    state.wsEventId = null;
  }
}

function connectWs(eventId) {
  if (!state.config || !state.session) return;
  closeWs();
  const url = state.config.ws_url_base + eventId;
  let ws;
  try {
    ws = new WebSocket(url, ["tz-session", state.session]);
  } catch (e) {
    logSocket("socket error: " + e.message);
    return;
  }
  state.ws = ws;
  state.wsEventId = eventId;
  ws.onopen = () => logSocket("socket open " + eventId);
  ws.onclose = (e) => logSocket("socket closed " + (e.reason || e.code));
  ws.onerror = () => logSocket("socket error");
  ws.onmessage = (msg) => onSocketMessage(eventId, msg.data);
}

function onSocketMessage(eventId, raw) {
  let m;
  try { m = JSON.parse(raw); } catch (_) { return; }
  logSocket(m.type + " " + JSON.stringify(Object.fromEntries(
    Object.entries(m).filter(([k]) => !["type", "event_id"].includes(k)))));
  if (m.type === "event.state") {
    const snap = m.snapshot || m;
    if (snap.status) $("#player-status").textContent = "Status: " + snap.status;
    if (snap.scoreboard && snap.scoreboard.home !== undefined) {
      $("#player-score").textContent =
        `Score ${snap.scoreboard.home}-${snap.scoreboard.away} · ${snap.scoreboard.period || ""} ${snap.scoreboard.clock || ""}`;
    }
    if (snap.active_source) $("#player-feed").textContent =
      `Feed: ${snap.active_source} ${snap.feed_healthy ? "healthy" : "degraded"}`;
    loadEvents();
  } else if (m.type === "score.update") {
    const s = m.scoreboard || {};
    $("#player-score").textContent = `Score ${s.home}-${s.away} · ${s.period || ""} ${s.clock || ""}`;
  } else if (m.type === "feed.heartbeat") {
    $("#player-feed").textContent = `Feed: ${m.active_source} ${m.feed_healthy ? "healthy" : "degraded"}`;
    loadEvents();
  } else if (m.type === "rights.revoked") {
    toast("Rights revoked — playback stopped", "bad");
    $("#player-status").textContent = "Status: rights revoked";
    const v = $("#video");
    v.pause();
    v.removeAttribute("src");
    v.load();
    loadEvents();
  } else if (m.type === "rights.restored") {
    toast("Rights restored (new version) — re-open to resume", "ok");
    loadEvents();
  } else if (m.type === "lease.status") {
    logSocket("lease renewal: " + (m.allow ? "allowed" : "denied " + m.reason));
  }
}

async function openEvent(eventId) {
  state.selected = eventId;
  const ev = state.events.find((e) => e.event_id === eventId);
  $("#player-title").textContent = ev ? ev.title : eventId;
  if (state.user && (state.user.role === "admin" || state.user.role === "operator")) {
    renderOperatorControls(eventId);
  }
  try {
    const res = await api("POST", `/api/events/${eventId}/playback-session`);
    $("#player-empty").classList.add("hidden");
    $("#player").classList.remove("hidden");
    $("#player-mode").textContent = res.mode;
    $("#player-status").textContent = "Status: " + (ev ? ev.status : res.mode);
    const v = $("#video");
    v.src = res.media_url + "?v=" + res.lease_id; // cache-bust; auth is the HttpOnly cookie
    v.play().catch(() => {});
    connectWs(eventId);
  } catch (e) {
    $("#player-empty").classList.add("hidden");
    $("#player").classList.remove("hidden");
    $("#player-mode").textContent = "denied";
    $("#player-status").textContent = "Access denied: " + (e.code || e.message);
    const v = $("#video"); v.removeAttribute("src"); v.load();
    connectWs(eventId); // still observe state if the zone allows
    toast("Playback denied: " + (e.code || e.message), "bad");
  }
}

// -- operator ----------------------------------------------------------
function renderOperatorControls(eventId) {
  const ev = state.events.find((e) => e.event_id === eventId);
  $("#op-event-label").textContent = ev ? `${ev.title} (${ev.status})` : eventId;
  const box = $("#transition-buttons");
  box.innerHTML = "";
  const nexts = ev ? (LIFECYCLE_NEXT[ev.status] || []) : [];
  if (!nexts.length) box.appendChild(el("span", "muted", "no forward transition"));
  nexts.forEach((target) => {
    const b = el("button", null, "→ " + target);
    b.addEventListener("click", () => doTransition(eventId, target));
    box.appendChild(b);
  });
}

async function doTransition(eventId, target) {
  try {
    await api("POST", `/api/events/${eventId}/transition`, { target });
    toast(`Moved to ${target}`, "ok");
    await loadEvents();
    renderOperatorControls(eventId);
  } catch (e) {
    toast("Transition blocked: " + (e.code || e.message), "bad");
  }
}

async function createEvent(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  try {
    const res = await api("POST", "/api/events", data);
    toast("Created " + res.event.title, "ok");
    form.reset();
    await loadEvents();
  } catch (e) {
    toast("Create failed: " + (e.code || e.message), "bad");
  }
}

async function revokeRights() {
  if (!state.selected) return toast("Select an event first", "bad");
  const reason = prompt("Reason for emergency revocation?", "rights dispute");
  if (reason === null) return;
  try {
    await api("POST", `/api/events/${state.selected}/rights/revoke`, { reason });
    toast("Rights revoked", "ok");
    await loadEvents();
    renderOperatorControls(state.selected);
  } catch (e) { toast("Revoke failed: " + (e.code || e.message), "bad"); }
}

async function restoreRights() {
  if (!state.selected) return toast("Select an event first", "bad");
  try {
    const res = await api("POST", `/api/events/${state.selected}/rights/restore`);
    toast("Rights restored v" + res.event.rights.version, "ok");
    await loadEvents();
    renderOperatorControls(state.selected);
  } catch (e) { toast("Restore failed: " + (e.code || e.message), "bad"); }
}

async function updateScore(form) {
  if (!state.selected) return toast("Select an event first", "bad");
  const raw = Object.fromEntries(new FormData(form).entries());
  const scoreboard = {
    home: Number(raw.home || 0), away: Number(raw.away || 0),
    period: raw.period || "", clock: raw.clock || "",
  };
  try {
    await api("POST", `/api/events/${state.selected}/score`, { scoreboard });
    toast("Score updated", "ok");
  } catch (e) { toast("Score failed: " + (e.code || e.message), "bad"); }
}

async function issueIngest() {
  if (!state.selected) return toast("Select an event first", "bad");
  const source = $("#ingest-source").value;
  try {
    const res = await api("POST", `/api/events/${state.selected}/ingest-token`, { source });
    const cmd = `python scripts/ingest_heartbeat.py \\\n  --event ${res.event_id} --source ${res.source} \\\n  --token ${res.ingest_token} --once`;
    const out = $("#ingest-out");
    out.textContent = `Scoped to event=${res.event_id} source=${res.source} (expires_in=${res.expires_in}s)\n\n${cmd}`;
    out.classList.remove("hidden");
    toast("Ingest token issued", "ok");
  } catch (e) { toast("Ingest token failed: " + (e.code || e.message), "bad"); }
}

async function refreshAnalytics() {
  try {
    const res = await api("GET", "/api/analytics");
    $("#analytics-out").textContent = JSON.stringify(res, null, 2);
  } catch (e) { toast("Analytics failed: " + e.message, "bad"); }
}

async function refreshAudit() {
  try {
    const res = await api("GET", "/api/audit");
    const box = $("#audit-out");
    box.innerHTML = "";
    res.audit.forEach((a) => {
      const row = el("div", "a");
      row.appendChild(el("span", "act", a.action));
      row.appendChild(el("span", "who", a.actor));
      row.appendChild(el("span", "muted", (a.event_id || "-") + " " + JSON.stringify(a.detail)));
      box.appendChild(row);
    });
  } catch (e) { toast("Audit failed: " + e.message, "bad"); }
}

// -- init --------------------------------------------------------------
async function init() {
  try {
    state.config = await api("GET", "/api/config");
  } catch (e) {
    toast("Could not load config", "bad");
    return;
  }
  $("#login-btn").addEventListener("click", login);
  $("#logout-btn").addEventListener("click", logout);
  $("#create-form").addEventListener("submit", (e) => { e.preventDefault(); createEvent(e.target); });
  $("#score-form").addEventListener("submit", (e) => { e.preventDefault(); updateScore(e.target); });
  $("#revoke-btn").addEventListener("click", revokeRights);
  $("#restore-btn").addEventListener("click", restoreRights);
  $("#ingest-btn").addEventListener("click", issueIngest);
  $("#analytics-btn").addEventListener("click", refreshAnalytics);
  $("#audit-btn").addEventListener("click", refreshAudit);
  await restoreSession();
}

document.addEventListener("DOMContentLoaded", init);
