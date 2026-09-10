"use strict";
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const api = async (method, path, body) => {
  const headers = {};
  const token = sessionStorage.getItem("tz_session");
  if (token) headers.Authorization = "Bearer " + token;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method, credentials: "include", headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) {
    const err = Error(data.error || "Request failed");
    err.code = data.code;
    throw err;
  }
  return data;
};
const toast = text => {
  $("#toast").textContent = text; $("#toast").classList.remove("hidden");
  setTimeout(() => $("#toast").classList.add("hidden"), 3000);
};
const escapeText = value => {
  const node = document.createElement("div");
  node.textContent = value == null ? "" : String(value);
  return node.innerHTML;
};
const STAFF = new Set(["operator", "owner", "admin"]);
const PAGE_VIEWS = new Set(["about", "support", "privacy", "terms"]);
const MEMBER_VIEWS = new Set(["feed", "live", "watch", "inbox", "profile"]);
const HASH_ALIAS = { schedules: "watch", archives: "watch" };
const state = { profile: null, signedIn: false, mode: "for_you", sport: "", kind: "photo", tab: "posts" };

function pendingPlayback() {
  const params = new URLSearchParams(location.search || "");
  const eventId = params.get("event");
  const archiveId = params.get("archive");
  if (archiveId) return { kind: "archive", id: archiveId };
  if (eventId) return { kind: "event", id: eventId };
  return null;
}

function clearPendingPlayback() {
  const next = (location.hash || "") || "#live";
  history.replaceState(null, "", location.pathname + next);
}

const player = {
  config: null,
  hls: null,
  ws: null,
  viewSession: null,
  heartbeatTimer: null,
  leaseTimer: null,
  seq: 0,
  eventId: null,
};

function stopPortalMedia(reason) {
  if (player.heartbeatTimer) { clearInterval(player.heartbeatTimer); player.heartbeatTimer = null; }
  if (player.leaseTimer) { clearInterval(player.leaseTimer); player.leaseTimer = null; }
  if (player.viewSession) {
    const sid = player.viewSession.session_id;
    player.viewSession = null;
    api("POST", `/api/view-sessions/${sid}/end`, { reason: reason || "pagehide" }).catch(() => {});
  }
  if (player.hls) { try { player.hls.destroy(); } catch (_) {} player.hls = null; }
  if (player.ws) { try { player.ws.close(); } catch (_) {} player.ws = null; }
  const v = $("#video");
  if (v) { v.pause(); v.removeAttribute("src"); v.load(); }
}

function attachPortalMedia(url, mediaType) {
  const v = $("#video");
  const isHls = mediaType === "hls" || (url && url.indexOf(".m3u8") !== -1);
  if (isHls && window.Hls && window.Hls.isSupported()) {
    if (player.hls) { try { player.hls.destroy(); } catch (_) {} }
    player.hls = new window.Hls({ enableWorker: false });
    player.hls.loadSource(url);
    player.hls.attachMedia(v);
    v.play().catch(() => {});
    return;
  }
  v.src = url;
  v.play().catch(() => {});
}

function connectEventSocket(eventId) {
  if (!player.config || !player.config.ws_enabled || !player.config.ws_url_base) return;
  if (!sessionStorage.getItem("tz_session")) return;
  if (player.ws) { try { player.ws.close(); } catch (_) {} }
  const url = player.config.ws_url_base + eventId;
  let ws;
  try { ws = new WebSocket(url, ["tz-session", sessionStorage.getItem("tz_session")]); }
  catch (_) { return; }
  player.ws = ws;
  ws.onmessage = (msg) => {
    let m; try { m = JSON.parse(msg.data); } catch (_) { return; }
    if (m.type === "rights.revoked") {
      toast("Playback stopped — rights revoked");
      $("#player-state").textContent = "Rights revoked";
      stopPortalMedia("rights_revoked");
    } else if (m.type === "event.state" && m.snapshot && m.snapshot.replay_pending) {
      $("#player-state").textContent = "Recording pending";
    }
  };
}

function showSignedIn(member, profile) {
  state.signedIn = true;
  $("#auth").classList.add("hidden");
  $("#portal").classList.remove("hidden");
  $("#section-nav").classList.remove("hidden");
  $("#signout").classList.remove("hidden");
  $("#create-btn").classList.remove("hidden");
  $("#member-name").textContent = member.display_name;
  $("#member-handle").textContent = profile ? "@" + profile.handle : "";
  $("#ops-link").classList.toggle("hidden", !STAFF.has(member.role));
  state.profile = profile;
}

function setView(name) {
  $$(".view").forEach(el => el.classList.toggle("hidden", el.id !== "view-" + name));
}

function routeName() {
  const raw = (location.hash || "").replace(/^#/, "").split("/")[0];
  return HASH_ALIAS[raw] || raw || "";
}

function applyRoute() {
  const view = routeName();
  if (PAGE_VIEWS.has(view)) {
    $("#auth").classList.add("hidden");
    $("#portal").classList.add("hidden");
    setView(view);
    return;
  }
  if (state.signedIn) {
    $("#auth").classList.add("hidden");
    $("#portal").classList.remove("hidden");
    const name = MEMBER_VIEWS.has(view) ? view : "live";
    setView(name);
    if (name === "feed") loadFeed();
    if (name === "live" || name === "watch") loadCatalog();
    if ((location.hash || "").replace(/^#/, "") === "archives") {
      const archives = $("#archives");
      if (archives) archives.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    if (name === "inbox") loadInbox();
    if (name === "profile") loadProfileTab();
    return;
  }
  $("#auth").classList.remove("hidden");
  $("#portal").classList.add("hidden");
  $$(".page-view").forEach(el => el.classList.add("hidden"));
}

function mediaTag(item) {
  const id = item.derived_media_asset_id || item.media_asset_id || item.source_media_asset_id;
  if (!id) return "<div class='media-ph'>No media</div>";
  if (item.clip_id || item.start_seconds != null || item.game_id || (item.provenance && item.provenance.source_type === "game_clip")) {
    return `<video src="/api/network/media/${id}" controls playsinline muted></video>`;
  }
  const photo = !item.clip_id && item.provenance && item.provenance.source_type === "member_upload";
  return photo
    ? `<img alt="" src="/api/network/media/${id}" />`
    : `<video src="/api/network/media/${id}" controls playsinline muted></video>`;
}

function postCard(item) {
  const badge = item.author && item.author.verification_badge
    ? `<span class="pill">${escapeText(item.author.verification_badge.replaceAll("_", " "))}</span>` : "";
  const provenance = item.provenance
    ? `<p class="prov">${escapeText(item.provenance.label)}</p>` : "";
  const watch = item.watch_full_game && item.watch_full_game.authorized
    ? `<button type="button" class="quiet" data-open-game="${item.watch_full_game.game_id}">Watch Full Game</button>`
    : item.watch_full_game
      ? `<p class="sub">${escapeText(item.watch_full_game.label)}</p>` : "";
  return `<article class="post-card">
    <header><strong>${escapeText(item.author.display_name)}</strong>
      <span class="sub">@${escapeText(item.author.handle)} · ${escapeText(item.author.profile_type)}</span>
      ${badge}</header>
    ${mediaTag(item)}
    <p>${escapeText(item.caption)}</p>
    <p class="sub">${escapeText(item.sport)}</p>
    ${provenance}${watch}
    <div class="actions">
      <button type="button" data-like="post:${item.post_id}">Like ${item.like_count || 0}</button>
      <button type="button" data-save="post:${item.post_id}">Save</button>
      <button type="button" data-send="post:${item.post_id}">Send</button>
      <button type="button" class="quiet" data-report="post:${item.post_id}">Report</button>
    </div>
    <form class="comment-form" data-subject="post:${item.post_id}">
      <label>Comment <input name="body" maxlength="500" /></label>
      <button type="submit">Comment</button>
    </form>
  </article>`;
}

async function loadFeed() {
  const sport = state.sport ? `&sport=${encodeURIComponent(state.sport)}` : "";
  const data = await api("GET", `/api/network/feed?mode=${state.mode}${sport}`);
  const root = $("#feed-list");
  if (!data.items.length) {
    root.innerHTML = "<p class='empty'>No posts in this feed yet.</p>";
    return;
  }
  root.innerHTML = data.items.map(postCard).join("");
  bindCards(root);
}

async function loadPublicFeed() {
  try {
    const data = await api("GET", "/api/network/feed?mode=for_you");
    $("#public-feed").innerHTML = data.items.length
      ? data.items.map(postCard).join("")
      : "<p class='sub'>Public sports posts will appear here.</p>";
    bindCards($("#public-feed"));
  } catch (_) { /* unsigned feed is best-effort */ }
}

function bindCards(root) {
  root.querySelectorAll("[data-like]").forEach(btn => btn.onclick = async () => {
    const [type, id] = btn.dataset.like.split(":");
    try {
      const res = await api("POST", "/api/network/react", { subject_type: type, subject_id: id, kind: "like" });
      btn.textContent = "Like " + res.like_count;
    } catch (error) { toast(error.message); }
  });
  root.querySelectorAll("[data-save]").forEach(btn => btn.onclick = async () => {
    const [type, id] = btn.dataset.save.split(":");
    try { await api("POST", "/api/network/saves", { subject_type: type, subject_id: id }); toast("Saved"); }
    catch (error) { toast(error.message); }
  });
  root.querySelectorAll("[data-send]").forEach(btn => btn.onclick = () => {
    const [type, id] = btn.dataset.send.split(":");
    $("#send-form").subject_type.value = type;
    $("#send-form").subject_id.value = id;
    $("#send-dialog").showModal();
  });
  root.querySelectorAll("[data-report]").forEach(btn => btn.onclick = async () => {
    const [type, id] = btn.dataset.report.split(":");
    try {
      await api("POST", "/api/network/reports", { subject_type: type, subject_id: id, reason: "needs review" });
      toast("Reported for review");
    } catch (error) { toast(error.message); }
  });
  root.querySelectorAll("[data-open-game]").forEach(btn => btn.onclick = () => openGame(btn.dataset.openGame));
  root.querySelectorAll(".comment-form").forEach(form => form.onsubmit = async event => {
    event.preventDefault();
    const [type, id] = form.dataset.subject.split(":");
    try {
      await api("POST", "/api/network/comments", { subject_type: type, subject_id: id, body: form.body.value });
      form.body.value = "";
      toast("Comment added");
    } catch (error) { toast(error.message); }
  });
}

function liveCard(event) {
  const rightsHold = !event.rights || event.rights.revoked;
  let pill = "UPCOMING";
  let action = "<p class='sub'>Cleared to go live. Watch live unlocks when the game starts.</p>";
  if (rightsHold) {
    pill = "RIGHTS HOLD";
    action = "<p class='sub'>Playback is held until rights are restored.</p>";
  } else if (event.status === "live") {
    pill = "LIVE";
    action = `<button data-event="${escapeText(event.event_id)}" type="button">Watch live</button>`;
  }
  return `<article><span class="pill">${pill}</span><h3>${escapeText(event.title)}</h3>${action}</article>`;
}

async function loadCatalog() {
  try {
    const live = await api("GET", "/api/member/live");
    $("#live-list").innerHTML = live.events.map(liveCard).join("")
      || "<p class='empty'>No live or upcoming games in your zone.</p>";
    $$("#live-list [data-event]").forEach(button => button.onclick = () => {
      playMedia(`/api/member/events/${button.dataset.event}/playback`, button.closest("article").querySelector("h3").textContent, "Authorized playback lease issued");
    });
  } catch (error) { toast(error.message); }
  try {
    const schedules = await api("GET", "/api/member/schedules");
    $("#schedule-list").innerHTML = schedules.schedules.map(s =>
      `<div class="schedule-row"><b>${escapeText(s.team)}</b><span>${escapeText(s.opponent)}</span>
       <span>${new Date(s.start_at * 1000).toLocaleDateString()}</span><small>${escapeText(s.location)}</small></div>`
    ).join("") || "<p class='empty'>No upcoming fixtures.</p>";
  } catch (error) { toast(error.message); }
  try {
    const archives = await api("GET", "/api/member/archives");
    $("#archive-list").innerHTML = archives.archives.map(a =>
      `<article><span class="pill">ARCHIVED</span><h3>${escapeText(a.title)}</h3>
       <p>${escapeText(a.school)} · ${escapeText(a.team)}<br>${escapeText(a.season)} · ${escapeText(a.kind)}</p>
       <button data-archive="${escapeText(a.archive_id)}" type="button">Watch archive</button></article>`
    ).join("") || "<p class='empty'>No archives available.</p>";
    $$("#archive-list [data-archive]").forEach(button => button.onclick = () => {
      playMedia(`/api/member/archive/${button.dataset.archive}/playback`, button.closest("article").querySelector("h3").textContent, "Authorized archive playback");
    });
  } catch (error) { toast(error.message); }
}

async function loadInbox() {
  const data = await api("GET", "/api/network/inbox");
  $("#inbox-list").innerHTML = data.items.length ? data.items.map(item =>
    `<article class="post-card"><strong>${escapeText(item.sender.display_name)}</strong>
     <p>${escapeText(item.message || "Shared a " + item.subject_type)}</p>
     <button type="button" data-read="${item.share_id}">Mark read</button></article>`
  ).join("") : "<p class='empty'>No shared media yet.</p>";
  $$("#inbox-list [data-read]").forEach(btn => btn.onclick = async () => {
    await api("POST", `/api/network/inbox/${btn.dataset.read}/read`);
    loadInbox();
  });
}

async function loadProfileTab() {
  if (!state.profile) return;
  const data = await api("GET", `/api/network/profiles/${state.profile.handle}/${state.tab}`);
  $("#profile-name").textContent = data.profile.display_name;
  $("#profile-meta").textContent = `@${data.profile.handle} · ${data.profile.profile_type} · ${data.profile.market}`;
  const form = $("#profile-form");
  form.display_name.value = data.profile.display_name;
  form.handle.value = data.profile.handle;
  form.bio.value = data.profile.bio;
  form.profile_type.value = data.profile.profile_type;
  if (!data.items.length) {
    $("#profile-list").innerHTML = "<p class='empty'>Nothing here yet.</p>";
    return;
  }
  $("#profile-list").innerHTML = data.items.map(item => {
    if (item.post_id) return postCard(item);
    if (item.game_id) {
      return `<article class="post-card"><span class="pill">${escapeText(item.processing_status)}</span>
        <h3>${escapeText(item.home_team_name)} vs ${escapeText(item.away_team_name)}</h3>
        <p class="sub">${escapeText(item.game_number)} · ${escapeText(item.sport)}</p>
        <button type="button" data-open-game="${item.game_id}">Open game</button></article>`;
    }
    return `<article class="post-card"><p class="prov">${escapeText((item.provenance || {}).label || "Clip")}</p>
      <p>${escapeText(item.caption || "")}</p></article>`;
  }).join("");
  bindCards($("#profile-list"));
}

async function openGame(gameId) {
  const data = await api("GET", `/api/network/games/${gameId}`);
  const game = data.game;
  setView("profile");
  $("#player-wrap").classList.remove("hidden");
  $("#player-title").textContent = `${game.home_team_name} vs ${game.away_team_name}`;
  $("#player-state").textContent = game.can_watch ? "Authorized source game" : "Not authorized";
  if (game.can_watch && game.source_media_asset_id) {
    try {
      const play = await api("POST", `/api/network/games/${gameId}/playback`);
      $("#video").src = play.media_url;
      $("#video").play().catch(() => {});
    } catch (error) { toast(error.message); }
  }
  $("#studio-form").game_id.value = gameId;
  $("#studio-status").textContent = game.can_create_clip ? "Ready to clip" : "Game not ready";
  if (game.source_media_asset_id) $("#studio-video").src = `/api/network/media/${game.source_media_asset_id}`;
  $("#studio-dialog").showModal();
}

async function loadPortal() {
  const me = await api("GET", "/api/member/me");
  showSignedIn(me.member, me.profile);
  await Promise.all([loadFeed(), loadCatalog()]);
  const pending = pendingPlayback();
  if (pending) {
    clearPendingPlayback();
    if (pending.kind === "archive") {
      location.hash = "watch";
      await playMedia(`/api/member/archive/${pending.id}/playback`, "Archive playback", "Authorized archive playback");
    } else {
      location.hash = "live";
      await playMedia(`/api/member/events/${pending.id}/playback`, "Live playback", "Authorized playback lease issued");
    }
  }
  applyRoute();
}

async function submitAuth(path, body) {
  const result = await api("POST", path, body);
  if (result.session_token) sessionStorage.setItem("tz_session", result.session_token);
  if (result.home === "/ops" && !pendingPlayback()) { location.href = "/ops"; return; }
  await loadPortal();
}

$("#login-form").addEventListener("submit", async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target).entries());
  try { await submitAuth("/api/auth/login", data); }
  catch (error) { toast(error.message); }
});
$("#register-form").addEventListener("submit", async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target).entries());
  try { await submitAuth("/api/auth/register", data); }
  catch (error) { toast(error.message); }
});
async function playMedia(path, title, stateText) {
  try {
    stopPortalMedia("pagehide");
    if (!player.config) player.config = await api("GET", "/api/config");
    const result = await api("POST", path);
    $("#player-wrap").classList.remove("hidden");
    $("#player-title").textContent = title || "Now playing";
    const leased = result.media_type === "hls"
      ? "Authorized HLS lease issued"
      : (stateText || "Authorized playback lease issued");
    $("#player-state").textContent = leased;
    attachPortalMedia(result.media_url, result.media_type);
    $("#player-wrap").scrollIntoView({ behavior: "smooth", block: "nearest" });
    const eventMatch = path.match(/\/events\/(evt_[A-Za-z0-9_]+)\//);
    if (eventMatch && result.lease_id) {
      player.eventId = eventMatch[1];
      const session = await api("POST", `/api/events/${player.eventId}/view-sessions`, { lease_id: result.lease_id });
      player.viewSession = session;
      player.seq = 0;
      const interval = ((player.config && player.config.viewer_heartbeat_interval) || 15) * 1000;
      player.heartbeatTimer = setInterval(async () => {
        if (!player.viewSession) return;
        player.seq += 1;
        const v = $("#video");
        try {
          await api("POST", `/api/view-sessions/${player.viewSession.session_id}/heartbeat`, {
            seq: player.seq,
            playing: !!(v && !v.paused && !v.ended),
            page_visible: document.visibilityState === "visible",
            position_seconds: v ? v.currentTime : 0,
          });
        } catch (e) {
          if (e.code === "rights_unavailable" || e.code === "rights_version_changed") {
            stopPortalMedia("rights_revoked");
          }
        }
      }, interval);
      const wait = Math.max(5000, ((result.lease_ttl || 60) * 1000) * 0.6);
      player.leaseTimer = setInterval(async () => {
        try {
          const renewed = await api("POST", path);
          attachPortalMedia(renewed.media_url, renewed.media_type);
        } catch (_) { stopPortalMedia("lease_expired"); }
      }, wait);
      connectEventSocket(player.eventId);
    }
  } catch (error) {
    toast((error && error.message) || "This game is not currently available with your access.");
  }
}
$("#signout").onclick = async () => {
  stopPortalMedia("logout");
  sessionStorage.removeItem("tz_session");
  await api("POST", "/api/auth/logout");
  location.reload();
};
window.addEventListener("hashchange", applyRoute);
window.addEventListener("pagehide", () => stopPortalMedia("pagehide"));
$$("#section-nav a").forEach(link => link.onclick = event => {
  event.preventDefault();
  const href = (link.getAttribute("href") || "").replace(/^#/, "");
  location.hash = href || link.dataset.view;
});
$$("[data-mode]").forEach(btn => btn.onclick = () => {
  state.mode = btn.dataset.mode;
  $$("[data-mode]").forEach(b => b.classList.toggle("active", b === btn));
  loadFeed();
});
$$("[data-sport]").forEach(btn => btn.onclick = () => {
  state.sport = btn.dataset.sport;
  $$("[data-sport]").forEach(b => b.classList.toggle("active", b === btn));
  loadFeed();
});
$$("[data-tab]").forEach(btn => btn.onclick = () => {
  state.tab = btn.dataset.tab;
  $$("[data-tab]").forEach(b => b.classList.toggle("active", b === btn));
  loadProfileTab();
});
$("#create-btn").onclick = () => {
  $("#composer").classList.add("hidden");
  $("#create-dialog").showModal();
};
$$(".create-choices [data-kind]").forEach(btn => btn.onclick = () => {
  state.kind = btn.dataset.kind;
  $("#composer").classList.remove("hidden");
  $("#composer-kind").textContent = btn.dataset.kind === "game" ? "Full Game" : btn.dataset.kind === "clip" ? "Clip" : "Photo";
  $("#game-fields").classList.toggle("hidden", state.kind !== "game");
  $("#game-fields").querySelector("[name=rights_attestation]").required = state.kind === "game";
});
$("#composer-file").onchange = () => {
  const file = $("#composer-file").files[0];
  const preview = $("#composer-preview");
  if (file && file.type.startsWith("video/")) {
    preview.src = URL.createObjectURL(file);
    preview.classList.remove("hidden");
  } else {
    preview.classList.add("hidden");
  }
};
$("#composer").onsubmit = async event => {
  event.preventDefault();
  const form = event.target;
  const status = $("#upload-status");
  try {
    if (state.kind === "game") {
      if (!form.rights_attestation.checked) throw Error("Rights attestation is required");
      status.textContent = "Requesting direct upload…";
      const game = await api("POST", "/api/network/games", {
        sport: form.sport.value, visibility: form.visibility.value,
        home_team_name: form.home_team_name.value, away_team_name: form.away_team_name.value,
        venue: form.venue.value, season: form.season.value, level: form.level.value,
        event_id: form.event_id.value || undefined, rights_attestation: true,
      });
      status.textContent = "Uploading to media provider…";
      await api("POST", game.game.upload.upload_url, { duration_seconds: 120, filename: ($("#composer-file").files[0] || {}).name });
      status.textContent = "Processing video…";
      let ready = false;
      for (let i = 0; i < 8 && !ready; i += 1) {
        const detail = await api("GET", `/api/network/games/${game.game.game_id}`);
        ready = detail.game.processing_status === "ready";
        status.textContent = ready ? "Game ready" : "Processing video…";
      }
      if (!ready) throw Error("Game is still processing");
      toast("Game ready — open Studio from your Games tab");
      $("#create-dialog").close();
      return;
    }
    status.textContent = "Requesting direct upload…";
    const upload = await api("POST", "/api/network/uploads", { kind: state.kind });
    const file = $("#composer-file").files[0];
    if (state.kind === "photo") {
      status.textContent = "Uploading photo to object storage…";
      const url = String(upload.upload_url || "");
      const localFake = url.includes("photos.test") || url.startsWith("/");
      if (file && upload.upload_method === "put" && !localFake) {
        await fetch(url, { method: "PUT", body: file });
      }
      const token = url.split("?")[0].split("/").pop();
      await api("POST", `/api/network/provider/fake/upload/${token}`, {
        filename: file && file.name,
        byte_size: file && file.size,
      });
    } else {
      status.textContent = "Uploading clip…";
      await api("POST", upload.upload_url, {
        duration_seconds: 20,
        filename: file && file.name,
      });
    }
    const published = await api("POST", "/api/network/posts", {
      upload_job_id: upload.upload_job_id,
      caption: form.caption.value,
      sport: form.sport.value,
      visibility: form.visibility.value,
    });
    status.textContent = "";
    toast("Published");
    $("#create-dialog").close();
    loadFeed();
    return published;
  } catch (error) {
    status.textContent = error.message;
    toast(error.message);
  }
};
$("#studio-form").onsubmit = async event => {
  event.preventDefault();
  const form = event.target;
  $("#studio-status").textContent = "Creating clip definition…";
  try {
    const clip = await api("POST", "/api/network/clips", {
      source_game_id: form.game_id.value,
      start_seconds: Number(form.start_seconds.value),
      end_seconds: Number(form.end_seconds.value),
      caption: form.caption.value,
      visibility: form.visibility.value,
    });
    $("#studio-status").textContent = "Rendering derived clip…";
    await api("POST", `/api/network/clips/${clip.clip.clip_id}/render`);
    $("#studio-status").textContent = "Publishing…";
    await api("POST", `/api/network/clips/${clip.clip.clip_id}/publish`, {
      caption: form.caption.value, visibility: form.visibility.value,
    });
    $("#studio-status").textContent = "Clip ready";
    toast("Clip published");
    $("#studio-dialog").close();
    loadFeed();
  } catch (error) {
    $("#studio-status").textContent = error.message;
    toast(error.message);
  }
};
$("#send-form").onsubmit = async event => {
  event.preventDefault();
  const form = event.target;
  try {
    await api("POST", "/api/network/shares", {
      subject_type: form.subject_type.value, subject_id: form.subject_id.value,
      recipient_handle: form.recipient_handle.value, message: form.message.value,
    });
    toast("Sent");
    $("#send-dialog").close();
  } catch (error) { toast(error.message); }
};
$("#profile-form").onsubmit = async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target).entries());
  try {
    const res = await api("POST", "/api/network/me/profile", data);
    state.profile = res.profile;
    toast("Profile saved");
    loadProfileTab();
  } catch (error) { toast(error.message); }
};
async function openSearchItem(item) {
  $("#search-results").classList.add("hidden");
  if (item.kind === "archive") {
    location.hash = "watch";
    await playMedia(`/api/member/archive/${item.id}/playback`, item.name, "Authorized archive playback");
    return;
  }
  if (item.kind === "game" && item.status === "live") {
    location.hash = "live";
    await playMedia(`/api/member/events/${item.id}/playback`, item.name, "Authorized playback lease issued");
    return;
  }
  if (item.kind === "game" && item.status === "archive") {
    location.hash = "archives";
    await playMedia(`/api/member/events/${item.id}/playback`, item.name, "Authorized archive playback");
    return;
  }
  location.hash = item.kind === "game" ? "live" : "watch";
}

$("#search").oninput = async event => {
  const query = event.target.value.trim();
  const panel = $("#search-results");
  if (query.length < 2) {
    panel.classList.add("hidden");
    panel.innerHTML = "";
    return;
  }
  try {
    const result = await api("GET", "/api/member/search?q=" + encodeURIComponent(query));
    if (!result.results.length) {
      panel.innerHTML = "<p class='empty'>No authorized results</p>";
      panel.classList.remove("hidden");
      return;
    }
    panel.innerHTML = result.results.map((item, index) =>
      `<button type="button" role="option" data-index="${index}">
        ${escapeText(item.name)}<span class="sub">${escapeText(item.kind)}${item.status ? " · " + item.status : ""}</span>
      </button>`
    ).join("");
    panel.classList.remove("hidden");
    panel.querySelectorAll("button").forEach(button => {
      button.onclick = () => openSearchItem(result.results[Number(button.dataset.index)]);
    });
  } catch (error) { toast(error.message); }
};
document.addEventListener("click", event => {
  if (!$("#search-wrap") || $("#search-wrap").contains(event.target)) return;
  $("#search-results").classList.add("hidden");
});
(async () => {
  try { player.config = await api("GET", "/api/config"); } catch (_) {}
  try { await loadPortal(); }
  catch (_) {
    loadPublicFeed();
    applyRoute();
  }
})();
