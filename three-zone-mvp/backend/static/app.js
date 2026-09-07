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
  inventory: null,
  hls: null,
  viewSession: null,
  heartbeatTimer: null,
  leaseTimer: null,
  heartbeatSeq: 0,
};

const OPERATOR_ROLES = ["operator", "owner", "admin"];
const OWNER_ROLES = ["owner", "admin"];
const canOperate = (u) => u && OPERATOR_ROLES.includes(u.role);
const canOwn = (u) => u && OWNER_ROLES.includes(u.role);

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
async function login(event) {
  if (event) event.preventDefault();
  const username = $("#login-username").value.trim();
  const password = $("#login-password").value;
  try {
    const res = await api("POST", "/api/auth/login", { username, password });
    state.session = res.session_token;
    state.user = res.user;
    sessionStorage.setItem("tz_session", state.session);
    if (res.home === "/") {
      location.href = "/";
      return;
    }
    afterAuth();
    toast("Signed in as " + res.user.display_name, "ok");
  } catch (e) {
    toast("Sign in failed: " + e.message, "bad");
  }
}

function logout() {
  stopMedia("logout");
  state.session = null;
  state.user = null;
  state.selected = null;
  sessionStorage.removeItem("tz_session");
  closeWs();
  $("#auth-panel").classList.remove("hidden");
  $("#shell").classList.add("hidden");
  $("#who").textContent = "";
  $("#nav-owner").classList.add("hidden");
  $("#print-root").classList.add("hidden");
  $("#events").innerHTML = "";
  $("#player").classList.add("hidden");
  $("#player-empty").classList.remove("hidden");
  $("#op-event-label").textContent = "(select an event)";
  $("#transition-buttons").innerHTML = "";
  state.inventory = null;
  api("POST", "/api/auth/logout").catch(() => {});
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
  if (state.user && !canOperate(state.user)) {
    location.href = "/";
    return;
  }
  $("#auth-panel").classList.add("hidden");
  $("#shell").classList.remove("hidden");
  $("#who").textContent = `${state.user.display_name} · ${state.user.role}`;
  $("#nav-owner").classList.toggle("hidden", !canOwn(state.user));
  $("#nav-operations").classList.toggle("hidden", !canOperate(state.user));
  showPane("catalog");
  loadEvents();
}

function showPane(name) {
  document.querySelectorAll("#app [data-pane]").forEach((pane) => {
    pane.classList.toggle("hidden", pane.getAttribute("data-pane") !== name);
  });
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.getAttribute("data-pane") === name);
  });
  if (name === "audit") {
    refreshAnalytics();
    refreshAudit();
  }
  if (name === "mastery") {
    loadMastery();
  }
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
    if (ev.replay_pending) {
      card.appendChild(el("div", "muted", "Recording pending"));
    }
    const btn = el("button", null, ev.replay_pending ? "Recording pending" : (ev.status === "replay" ? "Watch replay" : "Open"));
    btn.addEventListener("click", () => { showPane("player"); openEvent(ev.event_id); });
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
    stopMedia("rights_revoked");
    loadEvents();
  } else if (m.type === "rights.restored") {
    toast("Rights restored (new version) — re-open to resume", "ok");
    loadEvents();
  } else if (m.type === "lease.status") {
    logSocket("lease renewal: " + (m.allow ? "allowed" : "denied " + m.reason));
  }
}

function stopMedia(reason) {
  if (state.heartbeatTimer) { clearInterval(state.heartbeatTimer); state.heartbeatTimer = null; }
  if (state.leaseTimer) { clearInterval(state.leaseTimer); state.leaseTimer = null; }
  if (state.viewSession) {
    const sid = state.viewSession.session_id;
    state.viewSession = null;
    api("POST", `/api/view-sessions/${sid}/end`, { reason: reason || "pagehide" }).catch(() => {});
  }
  if (state.hls) {
    try { state.hls.destroy(); } catch (_) {}
    state.hls = null;
  }
  const v = $("#video");
  if (v) {
    v.pause();
    v.removeAttribute("src");
    v.load();
  }
}

function attachMedia(url, mediaType) {
  const v = $("#video");
  const isHls = mediaType === "hls" || (url && url.indexOf(".m3u8") !== -1);
  if (isHls && window.Hls && window.Hls.isSupported()) {
    if (state.hls) { try { state.hls.destroy(); } catch (_) {} }
    state.hls = new window.Hls({ enableWorker: false });
    state.hls.loadSource(url);
    state.hls.attachMedia(v);
    v.play().catch(() => {});
    return;
  }
  v.src = url;
  v.play().catch(() => {});
}

async function startViewLoop(eventId, leaseId) {
  const session = await api("POST", `/api/events/${eventId}/view-sessions`, { lease_id: leaseId });
  state.viewSession = session;
  state.heartbeatSeq = 0;
  const interval = ((state.config && state.config.viewer_heartbeat_interval) || 15) * 1000;
  const beat = async () => {
    if (!state.viewSession) return;
    state.heartbeatSeq += 1;
    const v = $("#video");
    try {
      await api("POST", `/api/view-sessions/${state.viewSession.session_id}/heartbeat`, {
        seq: state.heartbeatSeq,
        playing: !!(v && !v.paused && !v.ended),
        page_visible: document.visibilityState === "visible",
        position_seconds: v ? v.currentTime : 0,
      });
    } catch (e) {
      if (e.code === "rights_unavailable" || e.code === "rights_version_changed") {
        stopMedia("rights_revoked");
      }
    }
  };
  state.heartbeatTimer = setInterval(beat, interval);
}

function scheduleLeaseRenew(eventId, ttl) {
  if (state.leaseTimer) clearInterval(state.leaseTimer);
  const wait = Math.max(5000, ((ttl || 60) * 1000) * 0.6);
  state.leaseTimer = setInterval(async () => {
    try {
      const res = await api("POST", `/api/events/${eventId}/playback-session`);
      attachMedia(res.media_url, res.media_type);
    } catch (e) {
      stopMedia("lease_expired");
      $("#player-status").textContent = "Access denied: " + (e.code || e.message);
    }
  }, wait);
}

async function openEvent(eventId) {
  stopMedia("pagehide");
  state.selected = eventId;
  const ev = state.events.find((e) => e.event_id === eventId);
  $("#player-title").textContent = ev ? ev.title : eventId;
  if (canOperate(state.user)) {
    renderOperatorControls(eventId);
  }
  try {
    const res = await api("POST", `/api/events/${eventId}/playback-session`);
    $("#player-empty").classList.add("hidden");
    $("#player").classList.remove("hidden");
    $("#player-mode").textContent = res.mode;
    let statusLine = "Status: " + (ev ? ev.status : res.mode);
    if (ev && ev.replay_pending) statusLine = "Status: recording pending";
    $("#player-status").textContent = statusLine;
    attachMedia(res.media_url, res.media_type);
    await startViewLoop(eventId, res.lease_id);
    scheduleLeaseRenew(eventId, res.lease_ttl);
    connectWs(eventId);
  } catch (e) {
    $("#player-empty").classList.add("hidden");
    $("#player").classList.remove("hidden");
    $("#player-mode").textContent = "denied";
    $("#player-status").textContent = "Access denied: " + (e.code || e.message);
    stopMedia();
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

async function provisionMedia() {
  if (!state.selected) return toast("Select an event first", "bad");
  try {
    const res = await api("POST", `/api/events/${state.selected}/media/provision`);
    const out = $("#ingest-out");
    out.textContent = `Provisioned input=${res.input_id}\ningest_url=${res.ingest_url}\nstream_key=${res.stream_key}\n(shown once; not stored)`;
    out.classList.remove("hidden");
    toast("Live input provisioned", "ok");
    await loadEvents();
  } catch (e) { toast("Provision failed: " + (e.code || e.message), "bad"); }
}

async function rotateMediaKey() {
  if (!state.selected) return toast("Select an event first", "bad");
  try {
    const res = await api("POST", `/api/events/${state.selected}/media/rotate-key`);
    const out = $("#ingest-out");
    out.textContent = `Rotated input=${res.input_id}\ningest_url=${res.ingest_url}\nstream_key=${res.stream_key}\n(shown once; not stored)`;
    out.classList.remove("hidden");
    toast("Ingest key rotated", "ok");
  } catch (e) { toast("Rotate failed: " + (e.code || e.message), "bad"); }
}

async function syncMedia() {
  if (!state.selected) return toast("Select an event first", "bad");
  try {
    const res = await api("POST", `/api/events/${state.selected}/media/sync`);
    toast(res.replay_pending ? "Recording pending" : ("Synced: " + (res.status || res.provider_state)), "ok");
    await loadEvents();
  } catch (e) { toast("Sync failed: " + (e.code || e.message), "bad"); }
}

async function endStream() {
  if (!state.selected) return toast("Select an event first", "bad");
  try {
    const res = await api("POST", `/api/events/${state.selected}/media/end`);
    toast(res.event && res.event.replay_pending ? "Stream ended — recording pending" : "Stream ended", "ok");
    await loadEvents();
    renderOperatorControls(state.selected);
  } catch (e) { toast("End stream failed: " + (e.code || e.message), "bad"); }
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

// -- owner back portal -------------------------------------------------
function fmtTs(ts) {
  if (!ts) return "-";
  try { return new Date(ts * 1000).toLocaleString(); } catch (_) { return String(ts); }
}

async function loadInventory() {
  const res = await api("GET", "/api/owner/inventory");
  state.inventory = res;
  renderInventoryReport(res);
  const t = res.totals || {};
  $("#owner-summary").textContent =
    `Loaded: ${t.users} users · ${t.events} events · ${t.rights_versions} rights versions · ${t.audit_entries} audit entries.`;
  return res;
}

function reportSection(title) {
  const wrap = el("section", "report-section");
  wrap.appendChild(el("h2", null, title));
  return wrap;
}

function tableFrom(headers, rows) {
  const table = el("table", "report-table");
  const thead = el("thead");
  const htr = el("tr");
  headers.forEach((h) => htr.appendChild(el("th", null, h)));
  thead.appendChild(htr);
  table.appendChild(thead);
  const tbody = el("tbody");
  rows.forEach((cells) => {
    const tr = el("tr");
    cells.forEach((c) => tr.appendChild(el("td", null, c === null || c === undefined ? "" : String(c))));
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  return table;
}

function renderInventoryReport(data) {
  const root = $("#print-root");
  root.innerHTML = "";

  const head = el("div", "report-head");
  head.appendChild(el("h1", null, "Three-Zone Control Plane — Full Site Inventory"));
  head.appendChild(el("div", "muted",
    `Environment: ${data.environment.env} · Generated: ${fmtTs(data.generated_at)}`));
  const t = data.totals || {};
  head.appendChild(el("div", "muted",
    `${t.users} users · ${t.events} events · ${t.rights_versions} rights versions · ${t.audit_entries} audit entries`));
  root.appendChild(head);

  // Tiers / capability map
  const tiers = reportSection("Access tiers & capabilities");
  (data.tiers || []).forEach((tier) => {
    const block = el("div", "tier-block");
    block.appendChild(el("h3", null, `${tier.label}  (role: ${tier.role}, account: ${tier.demo_account})`));
    block.appendChild(el("div", "muted", tier.description));
    const ul = el("ul");
    (tier.capabilities || []).forEach((c) => ul.appendChild(el("li", null, c)));
    block.appendChild(ul);
    tiers.appendChild(block);
  });
  root.appendChild(tiers);

  // Route map
  const routes = reportSection("Every route on this website");
  routes.appendChild(tableFrom(
    ["Method", "Path", "Access tier", "Purpose"],
    (data.routes || []).map((r) => [r.method, r.path, r.tier, r.purpose])
  ));
  root.appendChild(routes);

  // Users
  const users = reportSection("Users");
  users.appendChild(tableFrom(
    ["User", "Name", "Role", "Account", "Subscription", "Zones", "Packages", "Destinations"],
    (data.users || []).map((u) => [
      u.user_id, u.display_name, u.role, u.account_state, u.subscription,
      (u.zones || []).join(", "), (u.packages || []).join(", "), (u.destinations || []).join(", "),
    ])
  ));
  root.appendChild(users);

  // Events + full rights history
  const events = reportSection("Events & rights history");
  (data.events || []).forEach((ev) => {
    const block = el("div", "event-block");
    block.appendChild(el("h3", null, `${ev.title}  [${ev.zone} · ${ev.status}]`));
    block.appendChild(el("div", "muted",
      `${ev.event_id} · category ${ev.category} · mode ${ev.production_mode} · ` +
      `source ${ev.active_source} (${ev.feed_healthy ? "healthy" : "degraded"}) · ` +
      `start ${fmtTs(ev.scheduled_start)} · replay ${ev.replay_available ? "available" : "no"}`));
    const rv = ev.rights_versions || [];
    if (rv.length) {
      block.appendChild(tableFrom(
        ["v", "Territory", "Dest", "Package", "Active", "Revoked", "Reason", "Live window", "Replay window", "Authority", "Retention(d)"],
        rv.map((r) => [
          r.version, r.territory, r.destination, r.package,
          r.active ? "yes" : "no", r.revoked ? "yes" : "no", r.revocation_reason || "",
          `${fmtTs(r.live_window[0])} → ${fmtTs(r.live_window[1])}`,
          `${fmtTs(r.replay_window[0])} → ${fmtTs(r.replay_window[1])}`,
          r.authority, r.archive_retention_days,
        ])
      ));
    } else {
      block.appendChild(el("div", "muted", "no rights versions"));
    }
    events.appendChild(block);
  });
  root.appendChild(events);

  // Analytics
  const analytics = reportSection("Analytics snapshot");
  const pre = el("pre", "code");
  pre.textContent = JSON.stringify(data.analytics, null, 2);
  analytics.appendChild(pre);
  root.appendChild(analytics);

  // Audit log (full)
  const audit = reportSection(`Audit log (${(data.audit || []).length} entries)`);
  audit.appendChild(tableFrom(
    ["#", "When", "Actor", "Action", "Event", "Detail"],
    (data.audit || []).map((a) => [
      a.id, fmtTs(a.ts), a.actor, a.action, a.event_id || "-", JSON.stringify(a.detail),
    ])
  ));
  root.appendChild(audit);

  root.classList.remove("hidden");
}

async function ownerLoad() {
  try {
    await loadInventory();
    toast("Full inventory loaded", "ok");
  } catch (e) {
    toast("Inventory failed: " + (e.code || e.message), "bad");
  }
}

async function ownerPrint() {
  try {
    if (!state.inventory) await loadInventory();
    document.body.classList.add("printing");
    const cleanup = () => { document.body.classList.remove("printing"); window.removeEventListener("afterprint", cleanup); };
    window.addEventListener("afterprint", cleanup);
    window.print();
  } catch (e) {
    document.body.classList.remove("printing");
    toast("Print failed: " + (e.code || e.message), "bad");
  }
}

async function ownerExport() {
  try {
    const data = state.inventory || await loadInventory();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    a.href = url;
    a.download = `three-zone-inventory-${stamp}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast("Export downloaded", "ok");
  } catch (e) {
    toast("Export failed: " + (e.code || e.message), "bad");
  }
}

async function loadMastery() {
  const article = $("#mastery-article");
  if (article.dataset.loaded === "1") return;
  try {
    const res = await api("GET", "/api/owner/mastery");
    article.innerHTML = res.html || "";
    article.dataset.loaded = "1";
  } catch (e) {
    article.textContent = "Could not load Three Zone Mastery: " + (e.code || e.message);
    toast("Mastery failed: " + (e.code || e.message), "bad");
  }
}

function printMastery() {
  document.body.classList.add("printing-mastery");
  const cleanup = () => {
    document.body.classList.remove("printing-mastery");
    window.removeEventListener("afterprint", cleanup);
  };
  window.addEventListener("afterprint", cleanup);
  window.print();
}

// -- init --------------------------------------------------------------
async function init() {
  try {
    state.config = await api("GET", "/api/config");
  } catch (e) {
    toast("Could not load config", "bad");
    return;
  }
  $("#login-form").addEventListener("submit", login);
  $("#logout-btn").addEventListener("click", logout);
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => showPane(item.getAttribute("data-pane")));
  });
  $("#create-form").addEventListener("submit", (e) => { e.preventDefault(); createEvent(e.target); });
  $("#score-form").addEventListener("submit", (e) => { e.preventDefault(); updateScore(e.target); });
  $("#revoke-btn").addEventListener("click", revokeRights);
  $("#restore-btn").addEventListener("click", restoreRights);
  $("#ingest-btn").addEventListener("click", issueIngest);
  const provisionBtn = $("#provision-btn");
  if (provisionBtn) provisionBtn.addEventListener("click", provisionMedia);
  const rotateBtn = $("#rotate-key-btn");
  if (rotateBtn) rotateBtn.addEventListener("click", rotateMediaKey);
  const syncBtn = $("#sync-btn");
  if (syncBtn) syncBtn.addEventListener("click", syncMedia);
  const endBtn = $("#end-stream-btn");
  if (endBtn) endBtn.addEventListener("click", endStream);
  window.addEventListener("pagehide", () => stopMedia("pagehide"));
  $("#analytics-btn").addEventListener("click", refreshAnalytics);
  $("#audit-btn").addEventListener("click", refreshAudit);
  $("#owner-load-btn").addEventListener("click", ownerLoad);
  $("#owner-print-btn").addEventListener("click", ownerPrint);
  $("#owner-export-btn").addEventListener("click", ownerExport);
  $("#mastery-print-btn").addEventListener("click", async () => {
    await loadMastery();
    printMastery();
  });
  const scheduleForm = $("#schedule-form");
  if (scheduleForm) {
    scheduleForm.addEventListener("submit", (e) => {
      e.preventDefault();
      uploadSchedule(e.target);
    });
  }
  await restoreSession();
}

async function uploadSchedule(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  try {
    const res = await api("POST", "/api/admin/schedules/upload", data);
    const out = $("#schedule-out");
    out.textContent = JSON.stringify(res, null, 2);
    out.classList.remove("hidden");
    toast(res.accepted ? "Schedule version " + res.version + " stored" : "Schedule rows rejected", res.accepted ? "ok" : "bad");
  } catch (e) {
    toast("Schedule upload failed: " + (e.code || e.message), "bad");
  }
}

document.addEventListener("DOMContentLoaded", init);
