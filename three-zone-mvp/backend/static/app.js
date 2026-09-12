"use strict";

const state = {
  config: null,
  session: sessionStorage.getItem("tz_session") || null,
  user: null,
  events: [],
  zoneFilter: "all",
  schedFilter: { status: "all", zone: "all", category: "all" },
  dashPayload: null,
  selected: null,
  ws: null,
  wsEventId: null,
  inventory: null,
  hls: null,
  viewSession: null,
  heartbeatTimer: null,
  leaseTimer: null,
  heartbeatSeq: 0,
  cameraStream: null,
  cameraPulse: null,
  cameraFileUrl: null,
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
    toast("Sign in failed: " + e.message + (e.code ? " (" + e.code + ")" : ""), "bad");
  }
}

function logout() {
  stopCamera();
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
  try {
    const res = await api("GET", "/api/me");
    state.user = res.user;
    if (res.session_token) {
      state.session = res.session_token;
      sessionStorage.setItem("tz_session", state.session);
    }
    afterAuth();
  } catch (e) {
    if (state.session) {
      state.session = null;
      sessionStorage.removeItem("tz_session");
    }
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
  showPane("dashboard");
  loadEvents();
}


async function loadSportsCheckAssets() {
  const sel = $("#sports-check-asset");
  if (!sel) return;
  try {
    const res = await api("GET", "/api/ops/sports-check/assets");
    sel.innerHTML = "";
    (res.assets || []).forEach((a) => {
      const opt = document.createElement("option");
      opt.value = a.source_asset_id;
      opt.textContent = `${a.source_asset_id} (${a.scenario || "?"}, ${a.input_privacy_class || "?"})`;
      sel.appendChild(opt);
    });
    const summary = $("#sports-check-summary");
    if (summary) {
      summary.textContent = `${(res.assets || []).length} synthetic assets · publish=${res.publish === true} · ${res.note || ""}`;
    }
  } catch (e) {
    toast("Sports-check assets failed: " + (e.code || e.message), "bad");
  }
}

async function runSportsCheck(ev) {
  if (ev) ev.preventDefault();
  const sel = $("#sports-check-asset");
  const out = $("#sports-check-out");
  const summary = $("#sports-check-summary");
  if (!sel || !sel.value) return;
  try {
    const res = await api("POST", "/api/ops/sports-check", { source_asset_id: sel.value });
    const decision = (res.policy && res.policy.decision) || "?";
    const reasons = ((res.policy && res.policy.reason_codes) || []).join(", ") || "—";
    if (summary) {
      summary.innerHTML = `<strong>Decision:</strong> ${decision}<br/><strong>Reasons:</strong> ${reasons}<br/><span class="muted">publish=${res.publish} · treasure_release=${res.treasure_release} · offline_synthetic=${res.allow_offline_synthetic}</span>`;
    }
    if (out) {
      out.classList.remove("hidden");
      out.textContent = JSON.stringify({ policy: res.policy, bundle: res.bundle }, null, 2);
    }
    toast("Sports check complete: " + decision, "ok");
  } catch (e) {
    toast("Sports check failed: " + (e.code || e.message), "bad");
  }
}

const PANE_TITLES = {
  dashboard: ["Home", "Dashboard"],
  catalog: ["Events", "Events"],
  "live-ops": ["Operations", "Live Ops"],
  schedule: ["Operations", "Schedule"],
  network: ["Review", "Verification"],
  treasure: ["Evidence", "Treasure"],
  moten: ["Evidence", "Moten"],
  xrpl: ["Evidence", "XRPL audit"],
  audit: ["Audit", "Activity"],
  health: ["System", "System health"],
  create: ["Tools", "Create event"],
  controls: ["Tools", "Event controls"],
  player: ["Tools", "Player"],
  "sports-check": ["Tools", "Sports check"],
  owner: ["Owner", "Inventory"],
  mastery: ["Owner", "Mastery"],
};

function showPane(name) {
  document.querySelectorAll("#app [data-pane]").forEach((pane) => {
    pane.classList.toggle("hidden", pane.getAttribute("data-pane") !== name);
  });
  if (name === "sports-check") loadSportsCheckAssets();
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.getAttribute("data-pane") === name);
  });
  const titles = PANE_TITLES[name] || ["Admin", name];
  const eye = $("#topbar-eyebrow");
  const title = $("#topbar-title");
  if (eye) eye.textContent = titles[0];
  if (title) title.textContent = titles[1];

  if (name === "dashboard" || name === "health" || name === "treasure") {
    refreshHealthDashboard();
    startHealthAutoRefresh();
  } else {
    stopHealthAutoRefresh();
  }
  if (name === "moten" || name === "xrpl") {
    loadMotenBridge();
  }
  if (name === "xrpl") {
    restoreXrplWallet();
    loadXrplMotenDept();
  }
  if (name === "audit") {
    refreshAnalytics();
    refreshAudit();
  }
  if (name === "mastery") {
    loadMastery();
  }
  if (name === "network") {
    refreshNetwork();
    const evid = $("#network-evidence-form");
    if (evid) evid.classList.toggle("hidden", !canOwn(state.user));
  }
}


// -- XRPL wallet connect (Crossmark / GemWallet, no seed) --------------
const XRPL_WALLET_KEY = "tz_ops_xrpl_wallet_v1";
let _xrplWallet = null; // { address, network, provider }

function _loadScriptOnce(src, id) {
  return new Promise((resolve, reject) => {
    if (id && document.getElementById(id)) {
      resolve();
      return;
    }
    const existing = Array.from(document.scripts).find((s) => s.src === src);
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("script_failed")));
      if (existing.dataset.loaded === "1") resolve();
      return;
    }
    const el = document.createElement("script");
    el.src = src;
    el.async = true;
    if (id) el.id = id;
    el.onload = () => { el.dataset.loaded = "1"; resolve(); };
    el.onerror = () => reject(new Error("script_failed"));
    document.head.appendChild(el);
  });
}

function _saveXrplWallet(state) {
  _xrplWallet = state;
  try {
    if (state) localStorage.setItem(XRPL_WALLET_KEY, JSON.stringify(state));
    else localStorage.removeItem(XRPL_WALLET_KEY);
  } catch (_) {}
}

function _readXrplWallet() {
  try {
    const raw = localStorage.getItem(XRPL_WALLET_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || !parsed.address) return null;
    return parsed;
  } catch (_) {
    return null;
  }
}

async function connectCrossmark() {
  await _loadScriptOnce(
    "https://cdn.jsdelivr.net/npm/@crossmarkio/sdk@0.4.0/pack/umd/index.js",
    "tz-crossmark-sdk"
  );
  const sdk = window.default || window.crossmark || window.Crossmark || null;
  if (!sdk) throw new Error("Crossmark SDK did not load");
  const installed = sdk.sync && typeof sdk.sync.isInstalled === "function"
    ? !!(await Promise.resolve(sdk.sync.isInstalled()))
    : true;
  if (!installed) {
    throw new Error("Install the Crossmark extension, then try Connect again");
  }
  if (typeof sdk.signInAndWait === "function") {
    await sdk.signInAndWait();
  } else if (sdk.async && typeof sdk.async.signInAndWait === "function") {
    await sdk.async.signInAndWait();
  } else {
    throw new Error("Crossmark sign-in is unavailable in this browser");
  }
  let address = null;
  if (sdk.sync && typeof sdk.sync.getAddress === "function") {
    address = await Promise.resolve(sdk.sync.getAddress());
  }
  if (!address && sdk.session && sdk.session.address) address = sdk.session.address;
  if (!address) throw new Error("Crossmark did not return an address");
  return { address: String(address), provider: "crossmark" };
}

async function connectGemWallet() {
  await _loadScriptOnce(
    "https://unpkg.com/@gemwallet/api@3.8.0/umd/gemwallet-api.js",
    "tz-gemwallet-api"
  );
  const api = window.GemWalletApi;
  if (!api) throw new Error("GemWallet API did not load");
  const installedResp = await api.isInstalled;
  const installed = !!(installedResp && installedResp.result && installedResp.result.isInstalled);
  if (!installed) {
    throw new Error("Install the GemWallet extension, then try Connect again");
  }
  const addrResp = await api.getAddress;
  const address = addrResp && addrResp.result && addrResp.result.address;
  if (!address) throw new Error("GemWallet did not share an address (or request was rejected)");
  return { address: String(address), provider: "gemwallet" };
}

async function refreshXrplAccountView() {
  const status = $("#xrpl-wallet-status");
  const summary = $("#xrpl-wallet-summary");
  const body = $("#xrpl-tx-body");
  const disconnectBtn = $("#xrpl-disconnect");
  if (!_xrplWallet || !_xrplWallet.address) {
    if (status) status.textContent = "Not connected";
    if (summary) { summary.classList.add("hidden"); summary.innerHTML = ""; }
    if (disconnectBtn) disconnectBtn.classList.add("hidden");
    if (body) {
      body.innerHTML = "";
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 5;
      td.className = "muted";
      td.textContent = "Connect a wallet to load every recent transaction.";
      tr.appendChild(td);
      body.appendChild(tr);
    }
    return;
  }
  if (disconnectBtn) disconnectBtn.classList.remove("hidden");
  const network = ($("#xrpl-network") && $("#xrpl-network").value) || _xrplWallet.network || "testnet";
  _xrplWallet.network = network;
  _saveXrplWallet(_xrplWallet);
  if (status) {
    status.textContent = "Connected · " + _xrplWallet.provider + " · " + network + " · loading ledger…";
  }
  try {
    const q = "/api/ops/xrpl/account?address=" + encodeURIComponent(_xrplWallet.address)
      + "&network=" + encodeURIComponent(network) + "&limit=50";
    const data = await api("GET", q);
    if (status) {
      status.textContent = "Connected · " + _xrplWallet.provider + " · " + network;
    }
    if (summary) {
      summary.classList.remove("hidden");
      const bal = data.balance_xrp != null ? (data.balance_xrp + " XRP") : "unfunded / not found";
      summary.innerHTML = "";
      const lines = [
        ["Address", data.address],
        ["Balance", bal],
        ["Sequence", data.sequence != null ? String(data.sequence) : "—"],
        ["Owner count", data.owner_count != null ? String(data.owner_count) : "—"],
      ];
      lines.forEach(([k, v]) => {
        const row = document.createElement("div");
        const strong = document.createElement("strong");
        strong.textContent = k + ": ";
        const code = document.createElement("code");
        code.textContent = v;
        row.appendChild(strong);
        row.appendChild(code);
        summary.appendChild(row);
      });
      if (data.honesty && data.honesty.note) {
        const note = document.createElement("p");
        note.className = "muted";
        note.textContent = data.honesty.note;
        summary.appendChild(note);
      }
    }
    if (body) {
      body.innerHTML = "";
      const txs = data.transactions || [];
      if (!txs.length) {
        const tr = document.createElement("tr");
        const td = document.createElement("td");
        td.colSpan = 5;
        td.className = "muted";
        td.textContent = data.account_found
          ? "No transactions returned for this account yet."
          : "Account not funded on this network yet — connect worked; fund testnet to see txs.";
        tr.appendChild(td);
        body.appendChild(tr);
      } else {
        txs.forEach((tx) => {
          const tr = document.createElement("tr");
          const cells = [
            tx.transaction_type || "—",
            (tx.hash || "—").slice(0, 12) + (tx.hash && tx.hash.length > 12 ? "…" : ""),
            tx.result || "—",
            tx.amount_xrp != null ? (tx.amount_xrp + " XRP") : "—",
            tx.ledger_index != null ? String(tx.ledger_index) : "—",
          ];
          cells.forEach((val, idx) => {
            const td = document.createElement("td");
            if (idx === 1 && tx.hash) {
              const code = document.createElement("code");
              code.title = tx.hash;
              code.textContent = val;
              td.appendChild(code);
            } else {
              td.textContent = val;
            }
            tr.appendChild(td);
          });
          body.appendChild(tr);
        });
      }
    }
  } catch (e) {
    if (status) status.textContent = "Connected, but ledger read failed: " + (e.code || e.message);
    toast("XRPL account read failed: " + (e.code || e.message), "bad");
  }
  // Moten bind + dept are best-effort alongside ledger refresh
  try {
    await saveXrplAuditAccount({ quiet: true });
  } catch (_) {}
  try {
    await loadXrplMotenDept();
  } catch (_) {}
}

async function onXrplConnect(provider) {
  const status = $("#xrpl-wallet-status");
  if (status) status.textContent = "Waiting for " + provider + " approval…";
  try {
    const connected = provider === "gemwallet"
      ? await connectGemWallet()
      : await connectCrossmark();
    const network = ($("#xrpl-network") && $("#xrpl-network").value) || "testnet";
    _saveXrplWallet({
      address: connected.address,
      provider: connected.provider,
      network,
      connected_at: Date.now(),
    });
    toast("Wallet connected", "ok");
    await refreshXrplAccountView();
  } catch (e) {
    if (status) status.textContent = "Connect failed: " + (e.message || e);
    toast(String(e.message || e), "bad");
  }
}

function disconnectXrplWallet() {
  _saveXrplWallet(null);
  refreshXrplAccountView();
  toast("Wallet disconnected", "ok");
}

function restoreXrplWallet() {
  const saved = _readXrplWallet();
  if (saved && saved.address) {
    _xrplWallet = saved;
    const net = $("#xrpl-network");
    if (net && saved.network) net.value = saved.network;
  }
  refreshXrplAccountView();
}

function _xrplEmptyRow(tbody, cols, msg) {
  if (!tbody) return;
  tbody.innerHTML = "";
  const tr = document.createElement("tr");
  const td = document.createElement("td");
  td.colSpan = cols;
  td.className = "muted";
  td.textContent = msg;
  tr.appendChild(td);
  tbody.appendChild(tr);
}

function _shortHash(h) {
  const s = String(h || "");
  if (!s) return "—";
  return s.length > 14 ? s.slice(0, 12) + "…" : s;
}

async function saveXrplAuditAccount(opts) {
  const quiet = !!(opts && opts.quiet);
  const bind = $("#xrpl-audit-bind-status");
  if (!_xrplWallet || !_xrplWallet.address) {
    if (bind) bind.textContent = "Moten audit account not bound yet — connect a wallet first.";
    if (!quiet) toast("Connect a wallet first", "bad");
    return null;
  }
  const network = ($("#xrpl-network") && $("#xrpl-network").value) || _xrplWallet.network || "testnet";
  if (bind) bind.textContent = "Saving Moten audit account…";
  try {
    const res = await api("POST", "/api/ops/xrpl/audit-account", {
      address: _xrplWallet.address,
      network,
      provider: _xrplWallet.provider || "unknown",
    });
    const profile = (res.moten && res.moten.signing_profile) || (res.moten && res.moten) || {};
    const acct = profile.account || res.address || _xrplWallet.address;
    const net = profile.network || res.network || network;
    if (bind) {
      bind.textContent = "Saved as Moten audit account · " + acct + " · " + net
        + (profile.status ? (" · " + profile.status) : "");
    }
    if (!quiet) toast("Moten audit account saved", "ok");
    return res;
  } catch (e) {
    if (bind) bind.textContent = "Moten bind failed: " + (e.code || e.message);
    if (!quiet) toast("Moten audit bind failed: " + (e.code || e.message), "bad");
    throw e;
  }
}

async function loadXrplMotenDept() {
  const honestyEl = $("#xrpl-moten-honesty");
  const pubsBody = $("#xrpl-moten-pubs-body");
  const receiptsBody = $("#xrpl-moten-receipts-body");
  const reconcileEl = $("#xrpl-reconcile-summary");
  const address = _xrplWallet && _xrplWallet.address;
  const q = address
    ? ("/api/ops/xrpl/moten?address=" + encodeURIComponent(address))
    : "/api/ops/xrpl/moten";
  let data;
  try {
    data = await api("GET", q);
  } catch (e) {
    if (honestyEl) {
      honestyEl.textContent = "Moten dept unavailable: " + (e.code || e.message)
        + " · Treasure verify is simulated; ledger publish is wallet-signed AccountSet+Memo.";
    }
    _xrplEmptyRow(pubsBody, 4, "Moten publications unavailable.");
    _xrplEmptyRow(receiptsBody, 3, "Moten receipts unavailable.");
    if (reconcileEl) reconcileEl.textContent = "Reconcile unavailable: " + (e.code || e.message);
    return null;
  }
  if (!data.configured) {
    if (honestyEl) {
      honestyEl.textContent = "Moten on-chain not configured (set TZ_MOTEN_ONCHAIN_URL). "
        + "Treasure verify is simulated; ledger publish is wallet-signed AccountSet+Memo.";
    }
    _xrplEmptyRow(pubsBody, 4, "Configure TZ_MOTEN_ONCHAIN_URL to load Moten publications.");
    _xrplEmptyRow(receiptsBody, 3, "Configure TZ_MOTEN_ONCHAIN_URL to load Moten receipts.");
    if (reconcileEl) reconcileEl.textContent = "Reconcile: Moten on-chain URL not configured.";
    return data;
  }
  const h = data.honesty || {};
  const health = data.health || {};
  const bits = [];
  bits.push("mode=" + (h.xrpl_mode || health.xrpl_mode || "unknown"));
  bits.push("network=" + (h.network || health.network || "unknown"));
  if (h.xrpl_label || health.xrpl) bits.push(String(h.xrpl_label || health.xrpl));
  bits.push(h.treasure || "Treasure verify is simulated");
  bits.push(h.publish || "Ledger publish is wallet-signed AccountSet+Memo");
  if (h.mode_note) bits.push(h.mode_note);
  if (h.wallet_signed_publication_supported || health.wallet_signed_publication_supported) {
    bits.push("wallet-signed path supported");
  }
  if (honestyEl) honestyEl.textContent = bits.join(" · ");

  const pubs = data.publications || [];
  if (pubsBody) {
    pubsBody.innerHTML = "";
    if (!pubs.length) {
      _xrplEmptyRow(pubsBody, 4, "No Moten publications yet.");
    } else {
      pubs.forEach((p) => {
        const tr = document.createElement("tr");
        [p.request_id || "—", p.event_id || "—", p.status || "—", p.network || "—"].forEach((val) => {
          const td = document.createElement("td");
          const code = document.createElement("code");
          code.textContent = String(val);
          td.appendChild(code);
          tr.appendChild(td);
        });
        pubsBody.appendChild(tr);
      });
    }
  }

  const receipts = data.receipts || [];
  if (receiptsBody) {
    receiptsBody.innerHTML = "";
    if (!receipts.length) {
      _xrplEmptyRow(receiptsBody, 3, "No Moten receipts yet.");
    } else {
      receipts.forEach((r) => {
        const tr = document.createElement("tr");
        const cells = [r.status || "—", _shortHash(r.transaction_hash), r.event_id || "—"];
        cells.forEach((val, idx) => {
          const td = document.createElement("td");
          if (idx === 1 && r.transaction_hash) {
            const code = document.createElement("code");
            code.title = r.transaction_hash;
            code.textContent = val;
            td.appendChild(code);
          } else {
            const code = document.createElement("code");
            code.textContent = String(val);
            td.appendChild(code);
          }
          tr.appendChild(td);
        });
        receiptsBody.appendChild(tr);
      });
    }
  }

  const match = data.match || {};
  const rec = data.reconciliation || {};
  const matched = match.matched || [];
  if (reconcileEl) {
    reconcileEl.textContent = "Reconcile · matched " + matched.length
      + " · unmatched Moten receipts " + (match.unmatched_receipt_count != null ? match.unmatched_receipt_count : "—")
      + " · wallet txs " + (match.wallet_tx_count != null ? match.wallet_tx_count : "—")
      + (rec.status ? (" · Moten run " + rec.status) : "")
      + (rec.error ? (" · " + rec.error) : "");
  }

  const bind = $("#xrpl-audit-bind-status");
  const profile = data.signing_profile || {};
  if (bind && profile.account) {
    bind.textContent = "Moten audit account · " + profile.account
      + " · " + (profile.network || "")
      + (profile.status ? (" · " + profile.status) : "");
  }
  return data;
}

function _extractTxHash(resp) {
  if (!resp) return null;
  if (typeof resp === "string" && resp.length >= 16) return resp;
  const candidates = [
    resp.hash,
    resp.transaction_hash,
    resp.tx_hash,
    resp.result && resp.result.hash,
    resp.result && resp.result.transaction_hash,
    resp.response && resp.response.txid,
    resp.response && resp.response.hash,
    resp.response && resp.response.data && resp.response.data.hash,
    resp.response && resp.response.data && resp.response.data.resp && resp.response.data.resp.hash,
    resp.data && resp.data.hash,
    resp.tx_json && resp.tx_json.hash,
    resp.engine_result && resp.tx_json && resp.tx_json.hash,
  ];
  for (const c of candidates) {
    if (typeof c === "string" && c.length >= 16) return c;
  }
  // nested Crossmark pack shapes
  try {
    const raw = JSON.stringify(resp);
    const m = raw.match(/"hash"\s*:\s*"([A-F0-9]{64})"/i);
    if (m) return m[1];
  } catch (_) {}
  return null;
}

async function _signSubmitCrossmark(unsignedTx) {
  await _loadScriptOnce(
    "https://cdn.jsdelivr.net/npm/@crossmarkio/sdk@0.4.0/pack/umd/index.js",
    "tz-crossmark-sdk"
  );
  const sdk = window.default || window.crossmark || window.Crossmark || null;
  if (!sdk) throw new Error("Crossmark SDK did not load");
  let resp;
  if (typeof sdk.signAndSubmitAndWait === "function") {
    resp = await sdk.signAndSubmitAndWait(unsignedTx);
  } else if (sdk.async && typeof sdk.async.signAndSubmitAndWait === "function") {
    resp = await sdk.async.signAndSubmitAndWait(unsignedTx);
  } else if (typeof sdk.signAndSubmit === "function") {
    resp = await sdk.signAndSubmit(unsignedTx);
  } else {
    throw new Error("Crossmark sign+submit is unavailable in this browser");
  }
  const hash = _extractTxHash(resp);
  if (!hash) throw new Error("Crossmark did not return a transaction hash");
  return hash;
}

async function _signSubmitGemWallet(unsignedTx) {
  await _loadScriptOnce(
    "https://unpkg.com/@gemwallet/api@3.8.0/umd/gemwallet-api.js",
    "tz-gemwallet-api"
  );
  const apiGw = window.GemWalletApi;
  if (!apiGw) throw new Error("GemWallet API did not load");
  const resp = await apiGw.signAndSubmit({ transaction: unsignedTx });
  const hash = _extractTxHash(resp)
    || (resp && resp.result && resp.result.hash)
    || null;
  if (!hash) throw new Error("GemWallet did not return a transaction hash (or request was rejected)");
  return hash;
}

async function publishTestAudit() {
  if (!_xrplWallet || !_xrplWallet.address) {
    toast("Connect a wallet first", "bad");
    return;
  }
  const network = ($("#xrpl-network") && $("#xrpl-network").value) || _xrplWallet.network || "testnet";
  const status = $("#xrpl-wallet-status");
  try {
    if (status) status.textContent = "Preparing Moten test publish…";
    toast("Treasure verify is simulated; ledger publish is wallet-signed AccountSet+Memo", "ok");
    const prepared = await api("POST", "/api/ops/xrpl/test-publish/prepare", {
      address: _xrplWallet.address,
      network,
    });
    const unsigned = prepared.unsigned_tx;
    const requestId = prepared.request_id;
    if (!unsigned || !requestId) throw new Error("prepare did not return unsigned_tx/request_id");
    if (status) status.textContent = "Approve AccountSet+Memo in " + (_xrplWallet.provider || "wallet") + "…";
    let txHash;
    if (_xrplWallet.provider === "gemwallet") {
      txHash = await _signSubmitGemWallet(unsigned);
    } else {
      txHash = await _signSubmitCrossmark(unsigned);
    }
    if (status) status.textContent = "Confirming Moten receipt…";
    await api("POST", "/api/ops/xrpl/test-publish/confirm", {
      request_id: requestId,
      transaction_hash: txHash,
      address: _xrplWallet.address,
      network,
    });
    toast("Test audit hash published · " + _shortHash(txHash), "ok");
    await refreshXrplAccountView();
    await loadXrplMotenDept();
  } catch (e) {
    if (status) status.textContent = "Publish failed: " + (e.code || e.message);
    toast("Publish failed: " + (e.code || e.message || e), "bad");
  }
}

// -- Moten / XRPL department panes (merged into /ops) -------------------
let _motenBridge = null;

async function loadMotenBridge() {
  const motenStatus = $("#moten-status");
  const xrplStatus = $("#xrpl-status");
  const motenFrame = $("#moten-frame");
  const xrplFrame = $("#xrpl-frame");
  const motenMiss = $("#moten-unconfigured");
  const xrplMiss = $("#xrpl-unconfigured");
  try {
    _motenBridge = await api("GET", "/api/ops/moten-bridge");
  } catch (e) {
    const msg = "Moten bridge failed: " + (e.code || e.message);
    if (motenStatus) motenStatus.textContent = msg;
    if (xrplStatus) xrplStatus.textContent = msg;
    toast(msg, "bad");
    return;
  }
  const honesty = (_motenBridge && _motenBridge.honesty) || {};
  const control = (_motenBridge && _motenBridge.control_plane) || {};
  const onchain = (_motenBridge && _motenBridge.onchain_audit) || {};

  function describe(label, block) {
    const health = (block && block.health) || {};
    if (!health.configured) return label + ": not configured";
    if (!health.reachable) return label + ": unreachable (" + (health.error || "error") + ")";
    const st = health.status || {};
    const bits = [label + ": reachable"];
    if (st.status) bits.push(String(st.status));
    if (st.xrpl) bits.push(String(st.xrpl));
    if (st.service) bits.push(String(st.service));
    if (honesty.intake) bits.push("intake=" + honesty.intake);
    return bits.join(" · ");
  }

  if (motenStatus) motenStatus.textContent = describe("Moten", control);
  if (xrplStatus) xrplStatus.textContent = describe("XRPL", onchain);

  if (control.embed_url && motenFrame) {
    if (motenMiss) motenMiss.classList.add("hidden");
    motenFrame.classList.remove("hidden");
    if (motenFrame.getAttribute("src") !== control.embed_url) {
      motenFrame.setAttribute("src", control.embed_url);
    }
  } else {
    if (motenFrame) {
      motenFrame.classList.add("hidden");
      motenFrame.removeAttribute("src");
    }
    if (motenMiss) motenMiss.classList.remove("hidden");
  }

  if (onchain.embed_url && xrplFrame) {
    if (xrplMiss) xrplMiss.classList.add("hidden");
    xrplFrame.classList.remove("hidden");
    if (xrplFrame.getAttribute("src") !== onchain.embed_url) {
      xrplFrame.setAttribute("src", onchain.embed_url);
    }
  } else {
    if (xrplFrame) {
      xrplFrame.classList.add("hidden");
      xrplFrame.removeAttribute("src");
    }
    if (xrplMiss) xrplMiss.classList.remove("hidden");
  }
}

// -- health / back portal ----------------------------------------------
let _healthTimer = null;

function stopHealthAutoRefresh() {
  if (_healthTimer) {
    clearInterval(_healthTimer);
    _healthTimer = null;
  }
}

function startHealthAutoRefresh() {
  stopHealthAutoRefresh();
  _healthTimer = setInterval(() => {
    const dash = document.querySelector('#app [data-pane="dashboard"]');
    const health = document.querySelector('#app [data-pane="health"]');
    const treasure = document.querySelector('#app [data-pane="treasure"]');
    const visible = [dash, health, treasure].some((p) => p && !p.classList.contains("hidden"));
    if (visible) {
      refreshHealthDashboard({ silent: true });
    } else {
      stopHealthAutoRefresh();
    }
  }, 15000);
}

function _pill(label, tone) {
  const wrap = el("span", "health-pill " + (tone || ""));
  wrap.appendChild(el("span", "dot", ""));
  wrap.appendChild(document.createTextNode(label));
  return wrap;
}

function _kv(box, rows) {
  if (!box) return;
  box.innerHTML = "";
  box.classList.remove("muted");
  rows.forEach(([k, v]) => {
    const row = el("div", "kv-row");
    row.appendChild(el("span", null, k));
    row.appendChild(el("span", null, String(v)));
    box.appendChild(row);
  });
}

function _fmtTs(ts) {
  if (ts == null || ts === "") return "—";
  const n = Number(ts);
  if (!Number.isFinite(n)) return String(ts);
  try {
    return new Date(n * 1000).toLocaleString();
  } catch (_) {
    return String(ts);
  }
}

async function refreshHealthDashboard(opts) {
  const silent = opts && opts.silent;
  try {
    const data = await api("GET", "/api/ops/dashboard");
    renderHealthDashboard(data);
  } catch (e) {
    if (!silent) toast("Health dashboard failed: " + (e.code || e.message), "bad");
  }
}

function renderHealthDashboard(data) {
  const gen = $("#health-generated");
  if (gen) {
    const when = data.generated_at != null ? _fmtTs(data.generated_at) : "";
    gen.textContent = when ? ("Updated " + when) : "";
  }
  if (data && (data.kpis || data.concept === "A" || data.today_schedule)) {
    renderConceptAHome(data);
  }

  const strip = $("#health-status-strip");
  if (strip) {
    strip.innerHTML = "";
    const healthOk = data.health && data.health.ok;
    const ready = data.live_readiness || {};
    const blockers = (ready.blockers || []).length;
    const warnings = (ready.warnings || []).length;
    let liveTone = "ok";
    let liveLabel = "Live ready";
    if (!ready.ready_to_publish_live || blockers) {
      liveTone = "bad";
      liveLabel = "Live blocked (" + blockers + ")";
    } else if (warnings) {
      liveTone = "warn";
      liveLabel = "Live ready · " + warnings + " warn";
    }
    const flags = data.flags || {};
    const aiOn = !!flags.AI;
    const moten = data.moten || {};
    const outbox = moten.outbox || {};
    const failed = Number(outbox.failed || outbox.error || 0);
    let motenTone = moten.enabled ? "ok" : "warn";
    let motenLabel = moten.enabled ? "Moten on" : "Moten off";
    if (failed) { motenTone = "bad"; motenLabel = "Moten · " + failed + " failed"; }
    strip.appendChild(_pill(healthOk ? "App ok" : "App down", healthOk ? "ok" : "bad"));
    strip.appendChild(_pill(liveLabel, liveTone));
    strip.appendChild(_pill(aiOn ? "AI on" : "AI off", aiOn ? "warn" : "ok"));
    strip.appendChild(_pill(motenLabel, motenTone));
  }

  const ev = data.events || {};
  const byStatus = ev.by_status || {};
  const byZone = ev.by_zone || {};
  _kv($("#health-events"), [
    ["Total", ev.total != null ? ev.total : "—"],
    ...Object.keys(byStatus).sort().map((k) => ["status · " + k, byStatus[k]]),
    ...Object.keys(byZone).sort().map((k) => ["zone · " + k, byZone[k]]),
  ]);

  const rights = data.rights || {};
  _kv($("#health-rights"), [
    ["Active", rights.active != null ? rights.active : "—"],
    ["Revoked", rights.revoked != null ? rights.revoked : "—"],
    ["Total versions", rights.total_versions != null ? rights.total_versions : "—"],
  ]);

  const media = data.media || {};
  const flags = data.flags || {};
  const mediaBox = $("#health-media-flags");
  if (mediaBox) {
    mediaBox.innerHTML = "";
    mediaBox.classList.remove("muted");
    [
      ["Live provider", media.live_provider || "—"],
      ["UGC provider", media.ugc_provider || "—"],
      ["Photo storage", media.photo_storage || "—"],
    ].forEach(([k, v]) => {
      const row = el("div", "kv-row");
      row.appendChild(el("span", null, k));
      row.appendChild(el("span", null, String(v)));
      mediaBox.appendChild(row);
    });
    const flagRow = el("div", null);
    flagRow.style.marginTop = "8px";
    Object.keys(flags).sort().forEach((name) => {
      const on = !!flags[name];
      flagRow.appendChild(el("span", "flag-chip " + (on ? "on" : "off"), name + (on ? "·ON" : "·off")));
    });
    mediaBox.appendChild(flagRow);
  }

  const net = data.network || {};
  _kv($("#health-network"), Object.keys(net).sort().map((k) => [k, net[k]]));

  const socks = data.sockets || {};
  _kv($("#health-sockets"), [
    ["Connections", socks.connections != null ? socks.connections : "—"],
    ["Metrics fresh", socks.metrics_fresh ? "yes" : "no"],
  ]);

  const moten = data.moten || {};
  const outbox = moten.outbox || {};
  const motenRows = [["Enabled", moten.enabled ? "yes" : "no"]];
  Object.keys(outbox).sort().forEach((k) => motenRows.push([k, outbox[k]]));
  if (Object.keys(outbox).length === 0) motenRows.push(["outbox", "empty"]);
  _kv($("#health-moten"), motenRows);

  const ls = data.live_sessions || {};
  const counts = ls.by_session_state || {};
  const countsEl = $("#health-sessions-counts");
  if (countsEl) {
    const parts = Object.keys(counts).sort().map((k) => k + "=" + counts[k]);
    countsEl.textContent = parts.length
      ? ("By state: " + parts.join(" · ") + " · total " + (ls.total != null ? ls.total : "—"))
      : "No live sessions yet.";
  }
  const tbody = document.querySelector("#health-sessions-table tbody");
  if (tbody) {
    tbody.innerHTML = "";
    (ls.recent || []).forEach((row) => {
      const tr = document.createElement("tr");
      [row.id, row.actor_id, row.event_id || "—", row.session_state,
       row.public_state, row.distribution_state, row.safety_state,
       _fmtTs(row.updated_at)].forEach((val) => {
        const td = document.createElement("td");
        td.textContent = val == null ? "—" : String(val);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    if (!(ls.recent || []).length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 8;
      td.className = "muted";
      td.textContent = "No recent sessions.";
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
  }

  const auditBody = document.querySelector("#health-audit-table tbody");
  if (auditBody) {
    auditBody.innerHTML = "";
    (data.audit_recent || []).forEach((row) => {
      const tr = document.createElement("tr");
      [row.id, _fmtTs(row.ts), row.actor, row.action, row.event_id || "—"].forEach((val) => {
        const td = document.createElement("td");
        td.textContent = val == null ? "—" : String(val);
        tr.appendChild(td);
      });
      auditBody.appendChild(tr);
    });
    if (!(data.audit_recent || []).length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 5;
      td.className = "muted";
      td.textContent = "No audit rows.";
      tr.appendChild(td);
      auditBody.appendChild(tr);
    }
  }

  const readyOut = $("#health-readiness-out");
  if (readyOut) {
    readyOut.textContent = JSON.stringify(data.live_readiness || {}, null, 2);
  }
}


// -- Concept A dashboard home ------------------------------------------
function renderConceptAHome(data) {
  state.dashPayload = data;
  const kpis = data.kpis || {};
  const setKpi = (id, val) => {
    const n = $(id);
    if (n) n.textContent = val == null ? "—" : String(val);
  };
  setKpi("#kpi-active-games", kpis.active_games);
  setKpi("#kpi-streams-verifying", kpis.streams_verifying);
  setKpi("#kpi-pending-treasure", kpis.pending_treasure);

  const strip = $("#dash-status-strip");
  if (strip) {
    strip.innerHTML = "";
    const healthOk = data.health && data.health.ok;
    const ready = data.live_readiness || {};
    const blockers = (ready.blockers || []).length;
    const warnings = (ready.warnings || []).length;
    let liveTone = "ok";
    let liveLabel = "Live ready";
    if (!ready.ready_to_publish_live || blockers) {
      liveTone = "bad";
      liveLabel = "Live blocked (" + blockers + ")";
    } else if (warnings) {
      liveTone = "warn";
      liveLabel = "Live ready · " + warnings + " warn";
    }
    const moten = data.moten || {};
    const outbox = moten.outbox || {};
    const failed = Number(outbox.failed || outbox.error || 0);
    let motenTone = moten.enabled ? "ok" : "warn";
    let motenLabel = moten.enabled ? "Moten on" : "Moten off";
    if (failed) { motenTone = "bad"; motenLabel = "Moten · " + failed + " failed"; }
    strip.appendChild(_pill(healthOk ? "App ok" : "App down", healthOk ? "ok" : "bad"));
    strip.appendChild(_pill(liveLabel, liveTone));
    strip.appendChild(_pill(motenLabel, motenTone));
    strip.appendChild(_pill("Concept A", "ok"));
  }

  renderTodaySchedule(data.today_schedule || {});
  renderVerificationQueue(data.verification_queue || []);
  renderTreasureSnapshot(data.treasure_review || {});
  renderActivityFeed(data.activity || data.audit_recent || []);
}

function _schedTime(ts) {
  if (ts == null || ts === "") return "—";
  const n = Number(ts);
  if (!Number.isFinite(n)) return String(ts);
  try {
    return new Date(n * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch (_) {
    return String(ts);
  }
}

function renderTodaySchedule(sched) {
  const dateEl = $("#sched-date");
  if (dateEl) {
    dateEl.textContent = sched.date
      ? (sched.date + (sched.timezone ? " · " + sched.timezone : ""))
      : "";
  }
  const filters = sched.filters || {};
  const box = $("#sched-filters");
  if (box) {
    box.innerHTML = "";
    const groups = [
      ["status", filters.status || ["all"]],
      ["zone", filters.zones || ["all"]],
      ["category", filters.categories || ["all"]],
    ];
    groups.forEach(([key, values]) => {
      values.forEach((v) => {
        const btn = el("button", "pill-btn" + (state.schedFilter[key] === v ? " active" : ""), v);
        btn.type = "button";
        btn.addEventListener("click", () => {
          state.schedFilter[key] = v;
          renderTodaySchedule((state.dashPayload && state.dashPayload.today_schedule) || sched);
        });
        box.appendChild(btn);
      });
    });
  }
  let items = sched.items || [];
  if (state.schedFilter.status !== "all") {
    items = items.filter((i) => i.status === state.schedFilter.status);
  }
  if (state.schedFilter.zone !== "all") {
    items = items.filter((i) => i.zone === state.schedFilter.zone);
  }
  if (state.schedFilter.category !== "all") {
    items = items.filter((i) => i.category === state.schedFilter.category);
  }
  const list = $("#sched-list");
  if (!list) return;
  list.innerHTML = "";
  if (!items.length) {
    list.appendChild(el("div", "empty-row", "No games on today’s live schedule for these filters."));
    return;
  }
  items.forEach((item) => {
    const row = el("div", "sched-row");
    row.appendChild(el("div", "sched-time", _schedTime(item.scheduled_start)));
    const mid = el("div", null);
    mid.appendChild(el("div", "sched-title", item.title || item.event_id));
    mid.appendChild(el("div", "sched-meta",
      [item.zone, item.category, item.production_mode].filter(Boolean).join(" · ")));
    row.appendChild(mid);
    row.appendChild(statusBadge(item.status || "scheduled"));
    const open = el("button", "ghost small", "Open");
    open.type = "button";
    open.addEventListener("click", () => {
      state.selected = item.event_id;
      showPane("controls");
      loadEvents().then(() => {
        renderOperatorControls(item.event_id);
      }).catch(() => {
        renderOperatorControls(item.event_id);
      });
    });
    row.appendChild(open);
    list.appendChild(row);
  });
}

function renderVerificationQueue(rows) {
  const list = $("#vq-list");
  if (!list) return;
  list.innerHTML = "";
  if (!rows.length) {
    list.appendChild(el("div", "empty-row", "Queue clear — no streams verifying."));
    return;
  }
  rows.forEach((row) => {
    const wrap = el("div", "queue-row");
    const main = el("div", "queue-main");
    const title = row.kind === "live_session"
      ? ("Session " + (row.id || "—"))
      : ("Game " + (row.id || "—"));
    main.appendChild(el("div", "queue-title", title));
    main.appendChild(el("div", "queue-meta",
      [row.kind, row.event_id, row.state, row.actor_id].filter(Boolean).join(" · ")));
    wrap.appendChild(main);
    const tone = (row.state || "").toLowerCase().includes("fail") ? "bad" : "ok";
    wrap.appendChild(el("span", "pill " + (tone === "bad" ? "bad" : ""), row.state || "pending"));
    list.appendChild(wrap);
  });
}

function renderTreasureSnapshot(tr) {
  const note = $("#treasure-note");
  if (note) note.textContent = tr.note || "";
  const cta = $("#treasure-cta");
  if (cta && tr.pending != null) cta.textContent = "Review (" + tr.pending + ")";
  const renderInto = (sel) => {
    const list = $(sel);
    if (!list) return;
    list.innerHTML = "";
    const items = tr.items || [];
    if (!items.length) {
      list.appendChild(el("div", "empty-row",
        tr.pending ? (tr.pending + " pending — open Treasure pane") : "No pending Treasure outbox items."));
      return;
    }
    items.forEach((item) => {
      const wrap = el("div", "queue-row");
      const main = el("div", "queue-main");
      main.appendChild(el("div", "queue-title", item.action || ("outbox #" + item.outbox_id)));
      main.appendChild(el("div", "queue-meta",
        ["audit " + (item.audit_id || "—"), item.event_id, item.actor, _fmtTs(item.created_at)]
          .filter(Boolean).join(" · ")));
      wrap.appendChild(main);
      wrap.appendChild(el("span", "pill", "pending"));
      list.appendChild(wrap);
    });
  };
  renderInto("#treasure-snap");
  renderInto("#treasure-panel-body");
}

function renderActivityFeed(rows) {
  const list = $("#activity-list");
  if (!list) return;
  list.innerHTML = "";
  if (!rows.length) {
    list.appendChild(el("div", "empty-row", "No recent Moten / audit activity."));
    return;
  }
  rows.slice(0, 12).forEach((row) => {
    const wrap = el("div", "activity-row");
    wrap.appendChild(el("div", "activity-id", "#" + (row.id != null ? row.id : "—")));
    const main = el("div", "activity-main");
    const strong = document.createElement("strong");
    strong.textContent = row.action || "event";
    main.appendChild(strong);
    main.appendChild(document.createTextNode(" · " + (row.actor || "—")));
    if (row.event_id) main.appendChild(document.createTextNode(" · " + row.event_id));
    wrap.appendChild(main);
    wrap.appendChild(el("div", "muted", _fmtTs(row.ts)));
    list.appendChild(wrap);
  });
}

function selectEvent(ev) {
  if (!ev) return;
  state.selected = ev.event_id;
  renderOperatorControls(ev.event_id);
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
    state.selected = res.event.event_id;
    showPane("controls");
    renderOperatorControls(state.selected);
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
    const out = $("#ingest-out");
    out.textContent = `Encoder token for ${res.event_id} (${res.source}, ${res.expires_in}s). Prefer Start camera on this page. Advanced: python scripts/ingest_heartbeat.py --event ${res.event_id} --source ${res.source} --token ${res.ingest_token} --once`;
    out.classList.remove("hidden");
    toast("Ingest token issued", "ok");
  } catch (e) { toast("Ingest token failed: " + (e.code || e.message), "bad"); }
}

function stopCameraPulse() {
  if (state.cameraPulse) {
    clearInterval(state.cameraPulse);
    state.cameraPulse = null;
  }
}

function stopCamera() {
  stopCameraPulse();
  if (state.cameraStream) {
    state.cameraStream.getTracks().forEach((track) => track.stop());
    state.cameraStream = null;
  }
  if (state.cameraFileUrl) {
    URL.revokeObjectURL(state.cameraFileUrl);
    state.cameraFileUrl = null;
  }
  const video = $("#camera-preview");
  if (video) {
    video.srcObject = null;
    video.removeAttribute("src");
    video.classList.remove("on");
    video.load();
  }
  const status = $("#camera-status");
  if (status) status.textContent = "Camera stopped. Hook it again to go live.";
}

function startCameraPulse() {
  stopCameraPulse();
  const beat = async () => {
    if (!state.selected) return;
    try {
      await api("POST", `/api/events/${state.selected}/camera/attach`, { go_live: false });
    } catch (_) {}
  };
  beat();
  state.cameraPulse = setInterval(beat, 5000);
}

async function startCamera() {
  if (!state.selected) return toast("Select an event first", "bad");
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    $("#camera-status").textContent = "This browser cannot open a camera. Pick a video file instead.";
    return;
  }
  try {
    stopCamera();
    state.cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: true,
    });
    const video = $("#camera-preview");
    video.srcObject = state.cameraStream;
    video.classList.add("on");
    $("#camera-status").textContent = "Camera is on this station. Tap Go live with this camera.";
    startCameraPulse();
    toast("Camera attached", "ok");
  } catch (e) {
    $("#camera-status").textContent = "Could not open camera. Allow camera access, or pick a video file.";
    toast("Camera blocked: " + (e.message || e), "bad");
  }
}

function useCameraFile(input) {
  const file = input && input.files && input.files[0];
  if (!file) return;
  if (!state.selected) return toast("Select an event first", "bad");
  stopCamera();
  state.cameraFileUrl = URL.createObjectURL(file);
  const video = $("#camera-preview");
  video.srcObject = null;
  video.src = state.cameraFileUrl;
  video.classList.add("on");
  video.play().catch(() => {});
  $("#camera-status").textContent = "Video file attached as this station camera. Tap Go live with this camera.";
  startCameraPulse();
  toast("Video file attached", "ok");
}

async function goLiveWithCamera() {
  if (!state.selected) return toast("Select an event first", "bad");
  if (!state.cameraStream && !state.cameraFileUrl) {
    await startCamera();
    if (!state.cameraStream && !state.cameraFileUrl) return;
  }
  try {
    const res = await api("POST", `/api/events/${state.selected}/camera/attach`, {
      go_live: true,
      source: $("#ingest-source") ? $("#ingest-source").value : "primary",
    });
    const title = res.event && res.event.title ? res.event.title : state.selected;
    toast("Live: " + title, "ok");
    $("#camera-status").textContent = "This camera is live. Keep this page open so the heartbeat stays fresh.";
    await loadEvents();
    renderOperatorControls(state.selected);
    startCameraPulse();
  } catch (e) {
    toast("Go live failed: " + (e.code || e.message), "bad");
  }
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

async function issueStaff(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  try {
    const res = await api("POST", "/api/owner/staff", {
      username: data.username,
      password: data.password,
      display_name: data.display_name,
      role: data.role,
    });
    form.reset();
    toast("Issued " + res.user.role + " account " + res.user.user_id, "ok");
  } catch (e) {
    toast("Could not issue staff: " + e.message + (e.code ? " (" + e.code + ")" : ""), "bad");
  }
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
  const demoHint = $("#demo-hint");
  if (demoHint && state.config && state.config.simulation) {
    demoHint.textContent = "Local demo: demo-owner / change-me-owner-local";
    demoHint.classList.remove("hidden");
  }
  $("#login-form").addEventListener("submit", login);
  $("#logout-btn").addEventListener("click", logout);
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => {
      if (item.disabled) return;
      const pane = item.getAttribute("data-pane");
      if (pane) showPane(pane);
    });
  });
  const sportsForm = $("#sports-check-form");
  if (sportsForm) sportsForm.addEventListener("submit", runSportsCheck);
  const sportsRefresh = $("#sports-check-refresh-btn");
  if (sportsRefresh) sportsRefresh.addEventListener("click", loadSportsCheckAssets);

  $("#create-form").addEventListener("submit", (e) => { e.preventDefault(); createEvent(e.target); });
  $("#score-form").addEventListener("submit", (e) => { e.preventDefault(); updateScore(e.target); });
  $("#revoke-btn").addEventListener("click", revokeRights);
  $("#restore-btn").addEventListener("click", restoreRights);
  $("#ingest-btn").addEventListener("click", issueIngest);
  const startCam = $("#start-camera-btn");
  if (startCam) startCam.addEventListener("click", startCamera);
  const goLiveCam = $("#go-live-camera-btn");
  if (goLiveCam) goLiveCam.addEventListener("click", goLiveWithCamera);
  const stopCam = $("#stop-camera-btn");
  if (stopCam) stopCam.addEventListener("click", stopCamera);
  const camFile = $("#camera-file");
  if (camFile) camFile.addEventListener("change", () => useCameraFile(camFile));
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
  const healthRefresh = $("#health-refresh-btn");
  if (healthRefresh) healthRefresh.addEventListener("click", () => refreshHealthDashboard());
  const treasureRefresh = $("#treasure-refresh-btn");
  if (treasureRefresh) treasureRefresh.addEventListener("click", () => refreshHealthDashboard());
  const motenRefresh = $("#moten-refresh-btn");
  if (motenRefresh) motenRefresh.addEventListener("click", () => loadMotenBridge());
  const xrplRefresh = $("#xrpl-refresh-btn");
  if (xrplRefresh) xrplRefresh.addEventListener("click", () => {
    loadMotenBridge();
    refreshXrplAccountView();
    loadXrplMotenDept();
  });
  const xrplCrossmark = $("#xrpl-connect-crossmark");
  if (xrplCrossmark) xrplCrossmark.addEventListener("click", () => onXrplConnect("crossmark"));
  const xrplGem = $("#xrpl-connect-gemwallet");
  if (xrplGem) xrplGem.addEventListener("click", () => onXrplConnect("gemwallet"));
  const xrplDisconnect = $("#xrpl-disconnect");
  if (xrplDisconnect) xrplDisconnect.addEventListener("click", disconnectXrplWallet);
  const xrplNetwork = $("#xrpl-network");
  if (xrplNetwork) xrplNetwork.addEventListener("change", () => {
    if (_xrplWallet) refreshXrplAccountView();
  });
  const xrplSaveAudit = $("#xrpl-save-audit");
  if (xrplSaveAudit) xrplSaveAudit.addEventListener("click", () => {
    saveXrplAuditAccount({ quiet: false }).then(() => loadXrplMotenDept()).catch(() => {});
  });
  const xrplTestPublish = $("#xrpl-test-publish");
  if (xrplTestPublish) xrplTestPublish.addEventListener("click", () => publishTestAudit());
  const xrplMotenRefresh = $("#xrpl-moten-refresh");
  if (xrplMotenRefresh) xrplMotenRefresh.addEventListener("click", () => loadXrplMotenDept());
  document.querySelectorAll("[data-goto]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const pane = btn.getAttribute("data-goto");
      if (pane) showPane(pane);
    });
  });
  $("#owner-load-btn").addEventListener("click", ownerLoad);
  $("#owner-print-btn").addEventListener("click", ownerPrint);
  $("#owner-export-btn").addEventListener("click", ownerExport);
  const staffForm = $("#staff-form");
  if (staffForm) {
    staffForm.addEventListener("submit", (e) => { e.preventDefault(); issueStaff(e.target); });
  }
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
  const netRefresh = $("#network-refresh-btn");
  if (netRefresh) netRefresh.addEventListener("click", refreshNetwork);
  const gameForm = $("#network-game-form");
  if (gameForm) gameForm.addEventListener("submit", (e) => { e.preventDefault(); decideNetworkGame(e.target); });
  const caseForm = $("#network-case-form");
  if (caseForm) caseForm.addEventListener("submit", (e) => { e.preventDefault(); decideNetworkCase(e.target); });
  const evForm = $("#network-evidence-form");
  if (evForm) evForm.addEventListener("submit", (e) => { e.preventDefault(); loadEvidence(e.target); });
  await restoreSession();
}

async function refreshNetwork() {
  try {
    const data = await api("GET", "/api/network/review");
    const box = $("#network-queue");
    box.innerHTML = "";
    const add = (title, rows, fmt) => {
      const h = el("h3", "", title);
      box.appendChild(h);
      if (!rows.length) { box.appendChild(el("p", "muted", "None")); return; }
      rows.forEach((row) => box.appendChild(el("pre", "code", fmt(row))));
    };
    add("Pending games", data.games, (g) => `${g.game_id} ${g.game_number} ${g.verification_status} ${g.processing_status}`);
    add("Uploads", data.uploads, (u) => `${u.upload_job_id} ${u.intended_type} ${u.status} ${u.error_code || ""}`);
    add("Open cases", data.cases, (c) => `${c.case_id} ${c.subject_type} ${c.subject_id} ${c.classifier_result}`);
    add("Reports", data.reports, (r) => `${r.report_id} ${r.subject_type} ${r.reason}`);
  } catch (e) {
    toast("Network queue failed: " + e.message, "bad");
  }
}

async function decideNetworkGame(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  try {
    const res = await api("POST", `/api/network/review/games/${data.game_id}`, {
      action: data.action, reason: data.reason,
    });
    $("#network-out").textContent = JSON.stringify(res, null, 2);
    $("#network-out").classList.remove("hidden");
    refreshNetwork();
    toast("Game decision recorded", "ok");
  } catch (e) {
    toast("Game decision failed: " + e.message, "bad");
  }
}

async function decideNetworkCase(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  try {
    const res = await api("POST", `/api/network/review/cases/${data.case_id}`, {
      action: data.action, reason: data.reason,
    });
    $("#network-out").textContent = JSON.stringify(res, null, 2);
    $("#network-out").classList.remove("hidden");
    refreshNetwork();
    toast("Moderation decision recorded", "ok");
  } catch (e) {
    toast("Moderation failed: " + e.message, "bad");
  }
}

async function loadEvidence(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  try {
    const res = await api("GET", `/api/network/evidence/${data.subject_type}/${data.subject_id}`);
    $("#network-out").textContent = JSON.stringify(res, null, 2);
    $("#network-out").classList.remove("hidden");
    const link = $("#evidence-html");
    link.href = `/api/network/evidence/${data.subject_type}/${data.subject_id}.html`;
    link.classList.remove("hidden");
    toast("Evidence loaded", "ok");
  } catch (e) {
    toast("Evidence failed: " + e.message, "bad");
  }
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
