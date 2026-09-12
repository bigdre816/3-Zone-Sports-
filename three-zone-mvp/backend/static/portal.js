"use strict";
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const toast = text => {
  $("#toast").textContent = text; $("#toast").classList.remove("hidden");
  setTimeout(() => $("#toast").classList.add("hidden"), 3000);
};
const escapeText = value => {
  const node = document.createElement("div");
  node.textContent = value == null ? "" : String(value);
  return node.innerHTML;
};
const parseList = value => (value || "").split(",").map(part => part.trim()).filter(Boolean);
const STAFF = new Set(["operator", "owner", "admin"]);
const PAGE_VIEWS = new Set(["about", "support", "privacy", "terms", "notifications"]);
const MEMBER_VIEWS = new Set(["huddle", "feed", "live", "watch", "saved", "studio", "inbox", "profile", "game"]);
const HASH_ALIAS = { schedules: "live", archives: "live", feed: "huddle", watch: "live" };
const state = {
  profile: null, signedIn: false, mode: "for_you", sport: "", kind: "photo", tab: "posts",
  maxClipSeconds: 60, minClipSeconds: 5, studioDuration: 90, previewing: false, gameId: null,
  lastClipId: null, lastPostId: null, heroEventId: null, notifyTimer: null,
};

function pendingPlayback() {
  const params = new URLSearchParams(location.search || "");
  const eventId = params.get("event");
  const archiveId = params.get("archive");
  if (archiveId) return { kind: "archive", id: archiveId };
  if (eventId) return { kind: "event", id: eventId };
  return null;
}

function clearPendingPlayback() {
  const next = (location.hash || "") || "#huddle";
  history.replaceState(null, "", location.pathname + next);
}

const player = {
  config: null, hls: null, ws: null, viewSession: null,
  heartbeatTimer: null, leaseTimer: null, seq: 0, eventId: null,
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
  if (player.ws) { try { player.ws.close(); } catch (_) {} }
  const url = player.config.ws_url_base + eventId;
  let ws;
  try { ws = new WebSocket(url, ["tz-session"]); }
  catch (_) { return; }
  player.ws = ws;
  ws.onmessage = (msg) => {
    let m; try { m = JSON.parse(msg.data); } catch (_) { return; }
    if (m.type === "rights.revoked") {
      toast("Playback stopped — rights revoked");
      $("#player-state").textContent = "Rights revoked";
      stopPortalMedia("rights_revoked");
    } else if (m.type === "moment.published") {
      loadLiveMoments(eventId);
    } else if (m.type === "event.state" && m.snapshot && m.snapshot.replay_pending) {
      $("#player-state").textContent = "Recording pending";
    }
  };
}

function connectPartySocket(partyId) {
  if (!player.config || !player.config.ws_enabled || !player.config.ws_url_base) return;
  const url = player.config.ws_url_base.replace("/ws/events/", "/ws/watch-parties/") + partyId;
  let ws;
  try { ws = new WebSocket(url, ["tz-session"]); }
  catch (_) { return; }
  ws.onmessage = (msg) => {
    let m; try { m = JSON.parse(msg.data); } catch (_) { return; }
    if (m.type === "rights.revoked") {
      toast("Game rights revoked. Chat stays up; video uses the playback lease.");
    } else if (m.type === "comment.created" || m.type === "reaction.created") {
      toast("Watch-party update");
    } else if (m.type === "moment.published") {
      if (state.heroEventId) loadLiveMoments(state.heroEventId);
    }
  };
}

function showSignedIn(member, profile) {
  state.signedIn = true;
  $("#auth").classList.add("hidden");
  $("#portal").classList.remove("hidden");
  $("#section-nav").classList.remove("hidden");
  $("#search-wrap").classList.remove("hidden");
  $("#signout").classList.remove("hidden");
  $("#create-btn").classList.remove("hidden");
  $("#notify-btn").classList.remove("hidden");
  $("#avatar-chip").classList.remove("hidden");
  $("#bottom-nav").hidden = false;
  const first = member.greeting_name || (member.display_name || "Member").split(" ")[0];
  $("#greeting-eyebrow").textContent = "GOOD TO HAVE YOU COURTSIDE, " + first.toUpperCase();
  $("#member-name").textContent = member.display_name;
  $("#member-handle").textContent = profile ? "@" + profile.handle : "";
  $("#avatar-chip").textContent = (first.slice(0, 2) || "TZ").toUpperCase();
  $("#ops-link").classList.toggle("hidden", !STAFF.has(member.role));
  state.profile = profile;
}

function setView(name) {
  const mapped = name === "feed" ? "huddle" : name === "watch" ? "live" : name;
  $$(".view").forEach(el => el.classList.toggle("hidden", el.id !== "view-" + mapped && el.id !== "view-" + name));
  if (mapped === "game") $("#player-wrap").classList.add("hidden");
  $$("#section-nav a, #bottom-nav a").forEach(a => {
    a.classList.toggle("active", a.dataset.view === mapped);
  });
}

function mediaUnavailable(reason) {
  return `<div class="media-ph"><span>${escapeText(reason || "This moment is no longer available.")}</span></div>`;
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
    if (view === "notifications") loadNotifications();
    return;
  }
  if (state.signedIn) {
    $("#auth").classList.add("hidden");
    $("#portal").classList.remove("hidden");
    const name = MEMBER_VIEWS.has(view) ? view : "huddle";
    setView(name);
    if (name === "huddle" || name === "feed") { loadFeed(); loadFriends(); }
    if (name === "live" || name === "watch") loadCatalog();
    if ((location.hash || "").replace(/^#/, "") === "archives") {
      const archives = $("#archives");
      if (archives) archives.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    if (name === "inbox") loadInbox();
    if (name === "profile") loadProfileTab();
    if (name === "saved") loadSaved();
    if (name === "studio") loadStudioSources();
    return;
  }
  $("#auth").classList.remove("hidden");
  $("#portal").classList.add("hidden");
  $$(".page-view").forEach(el => el.classList.add("hidden"));
}

function mediaTag(item) {
  if (item.content_state === "unavailable") {
    return mediaUnavailable("This moment is no longer available.");
  }
  if (item.content_state === "restricted" || item.publication_status === "restricted") {
    return mediaUnavailable("This post is restricted");
  }
  if (item.content_state === "removed" || item.publication_status === "removed") {
    return mediaUnavailable("This post was removed");
  }
  const url = (item.media && item.media.playback_url) || null;
  const id = item.derived_media_asset_id || item.media_asset_id || item.source_media_asset_id;
  if (!url && !id) return mediaUnavailable("This moment is no longer available.");
  const src = url || `/api/network/media/${id}`;
  if (item.clip_id || (item.media && item.media.kind === "clip") || (item.provenance && item.provenance.source_type === "game_clip")) {
    return `<video src="${src}" controls playsinline muted></video>`;
  }
  const photo = item.media && item.media.kind === "photo";
  return photo
    ? `<img alt="Community sports moment" src="${src}" />`
    : `<video src="${src}" controls playsinline muted></video>`;
}

function postCard(item) {
  const badge = item.author && item.author.verification_badge
    ? `<span class="pill">${escapeText(item.author.verification_badge.replaceAll("_", " "))}</span>` : "";
  const provenance = item.provenance
    ? `<span class="prov">${escapeText(item.provenance.label)}</span>` : "";
  const watch = item.watch_full_game && item.watch_full_game.authorized
    ? `<button type="button" class="quiet" data-open-game="${item.watch_full_game.game_id}">Watch Full Game</button>`
    : item.watch_full_game
      ? `<p class="post-whisper">${escapeText(item.watch_full_game.label)}</p>` : "";
  const tags = (item.athlete_tags || []).map(tag =>
    `@${escapeText(tag.handle)}`
  ).join(" · ");
  const blocked = item.content_state === "restricted" || item.content_state === "removed" || item.content_state === "unavailable";
  const liked = item.viewer_liked || (item.engagement && item.engagement.liked_by_me);
  const likeCount = (item.engagement && item.engagement.likes) || item.like_count || 0;
  const canDelete = item.viewer_can_delete || (
    state.profile && item.author && state.profile.profile_id === item.author.profile_id
  );
  const deleteBtn = canDelete
    ? `<button type="button" class="icon-action danger" data-delete-post="${item.post_id}" aria-label="Delete"><span class="ia-icon" aria-hidden="true">⌫</span></button>`
    : "";
  const whisperParts = [item.sport, tags, provenance].filter(Boolean);
  const whisper = whisperParts.length
    ? `<p class="post-whisper">${item.sport ? escapeText(item.sport) : ""}${tags ? (item.sport ? " · " : "") + tags : ""}${provenance ? ((item.sport || tags) ? " · " : "") + provenance : ""}</p>`
    : "";
  const actions = blocked ? "" : `<div class="actions icon-row" role="group" aria-label="Post actions">
      <button type="button" class="icon-action ${liked ? "liked" : ""}" data-like="post:${item.post_id}" aria-label="Like">
        <span class="ia-icon" aria-hidden="true">♥</span><span class="ia-count">${likeCount}</span>
      </button>
      <button type="button" class="icon-action" data-save="post:${item.post_id}" aria-label="Save">
        <span class="ia-icon" aria-hidden="true">🔖</span>
      </button>
      <button type="button" class="icon-action" data-share="post:${item.post_id}" aria-label="Share">
        <span class="ia-icon" aria-hidden="true">↗</span>
      </button>
      <button type="button" class="icon-action" data-send="post:${item.post_id}" aria-label="Send">
        <span class="ia-icon" aria-hidden="true">➤</span>
      </button>
      ${deleteBtn}
    </div>
    <div class="actions-more">
      <button type="button" class="quiet" data-follow="${escapeText(item.author.handle)}">Follow</button>
      <button type="button" class="quiet" data-report="post:${item.post_id}">Report</button>
      <button type="button" class="quiet" data-block="${escapeText(item.author.handle)}">Block</button>
    </div>
    <div class="comments" data-comments="post:${item.post_id}"></div>
    <form class="comment-form" data-subject="post:${item.post_id}">
      <label>Comment <input name="body" maxlength="500" placeholder="Add a quiet note" /></label>
      <button type="submit">Comment</button>
    </form>`;
  const caption = item.caption
    ? `<p class="post-caption">${escapeText(item.caption)}</p>`
    : "";
  return `<article class="post-card">
    <div class="post-media">${mediaTag(item)}</div>
    <div class="post-body">
      <header class="post-meta"><strong>${escapeText(item.author.display_name)}</strong>
        <span class="sub">@${escapeText(item.author.handle)}</span>
        ${badge}</header>
      ${caption}
      ${whisper}${watch}
      ${actions}
    </div>
  </article>`;
}

async function loadComments(root) {
  root.querySelectorAll("[data-comments]").forEach(async el => {
    const [type, id] = el.dataset.comments.split(":");
    try {
      const data = await api("GET", `/api/network/comments?subject_type=${type}&subject_id=${id}`);
      el.innerHTML = (data.comments || []).slice(-3).map(c =>
        `<p><strong>${escapeText(c.author.display_name)}</strong> ${escapeText(c.body)}</p>`
      ).join("") || "";
    } catch (_) { /* keep empty */ }
  });
}

function bindMediaErrors(root) {
  root.querySelectorAll("video, img").forEach(el => {
    el.addEventListener("error", () => {
      const ph = document.createElement("div");
      ph.className = "media-ph";
      ph.textContent = "This moment is no longer available.";
      el.replaceWith(ph);
    });
  });
}

function bindCards(root) {
  bindMediaErrors(root);
  loadComments(root);
  root.querySelectorAll("[data-like]").forEach(btn => btn.onclick = async () => {
    const [type, id] = btn.dataset.like.split(":");
    const countEl = btn.querySelector(".ia-count");
    const prevCount = countEl ? countEl.textContent : btn.textContent;
    const prevHtml = btn.innerHTML;
    if (countEl) countEl.textContent = "…";
    else btn.textContent = "Like …";
    try {
      const liked = btn.classList.contains("liked");
      const res = liked
        ? await api("POST", `/api/member/posts/${id}/unlike`)
        : await api("PUT", `/api/member/posts/${id}/like`);
      if (countEl) countEl.textContent = String(res.like_count);
      else btn.textContent = "Like " + res.like_count;
      btn.classList.toggle("liked", res.liked);
    } catch (error) {
      if (countEl) countEl.textContent = prevCount;
      else btn.innerHTML = prevHtml;
      toast(error.message);
    }
  });
  root.querySelectorAll("[data-save]").forEach(btn => btn.onclick = async () => {
    const [type, id] = btn.dataset.save.split(":");
    try { await api("POST", "/api/network/saves", { subject_type: type, subject_id: id }); toast("Saved"); }
    catch (error) { toast(error.message); }
  });
  root.querySelectorAll("[data-share]").forEach(btn => btn.onclick = async () => {
    const [type, id] = btn.dataset.share.split(":");
    try {
      const res = await api("POST", `/api/member/posts/${id}/share`, { destination: "copy_link" });
      await navigator.clipboard.writeText(res.url);
      toast("Copied " + res.url);
    } catch (error) { toast(error.message); }
  });
  root.querySelectorAll("[data-send]").forEach(btn => btn.onclick = () => {
    const [type, id] = btn.dataset.send.split(":");
    $("#send-form").subject_type.value = type;
    $("#send-form").subject_id.value = id;
    $("#send-dialog").showModal();
  });
  root.querySelectorAll("[data-follow]").forEach(btn => btn.onclick = async () => {
    try {
      await api("POST", `/api/network/profiles/${btn.dataset.follow}/follow`);
      toast("Following");
    } catch (error) { toast(error.message); }
  });
  root.querySelectorAll("[data-block]").forEach(btn => btn.onclick = async () => {
    try {
      await api("POST", `/api/member/blocks/${btn.dataset.block}`);
      toast("Blocked");
      loadFeed();
    } catch (error) { toast(error.message); }
  });
  root.querySelectorAll("[data-report]").forEach(btn => btn.onclick = async () => {
    const [type, id] = btn.dataset.report.split(":");
    try {
      await api("POST", "/api/network/reports", { subject_type: type, subject_id: id, reason: "needs review" });
      toast("Reported for review");
    } catch (error) { toast(error.message); }
  });
  root.querySelectorAll("[data-delete-post]").forEach(btn => btn.onclick = async () => {
    const id = btn.dataset.deletePost;
    if (!window.confirm("Delete this photo post?")) return;
    try {
      await api("POST", `/api/network/posts/${id}/delete`);
      toast("Post deleted");
      loadFeed();
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
      loadComments(form.parentElement);
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
    action = `<button data-event="${escapeText(event.event_id)}" type="button">Watch live</button>
      <button class="quiet" data-party="${escapeText(event.event_id)}" type="button">Watch with friends</button>`;
  }
  const board = event.scoreboard || {};
  const score = board.home != null
    ? `<p class="sub">${escapeText(board.period || "")} ${escapeText(board.clock || "")} · ${board.home}–${board.away}</p>`
    : "";
  return `<article><span class="pill">${pill}</span><h3>${escapeText(event.title)}</h3>${score}${action}</article>`;
}

async function loadLiveMoments(eventId) {
  if (!eventId) return;
  try {
    const data = await api("GET", `/api/member/events/${eventId}/moments`);
    $("#live-moments").innerHTML = (data.moments || []).map(m =>
      `<div class="moment-row"><span class="sub">${escapeText(m.type)}</span>
       <div><strong>${escapeText(m.label)}</strong></div></div>`
    ).join("") || "<p class='empty'>Moments appear when the authorized scoreboard changes.</p>";
  } catch (_) {
    $("#live-moments").innerHTML = "<p class='empty'>Moments unavailable.</p>";
  }
}

async function loadCatalog() {
  try {
    const live = await api("GET", "/api/member/live");
    const events = live.events || [];
    const hero = events.find(e => e.status === "live") || events[0];
    if (hero) {
      state.heroEventId = hero.event_id;
      const board = hero.scoreboard || {};
      $("#live-hero").innerHTML = `<div class="live-hero">
        <span class="pill">${escapeText((hero.status || "").toUpperCase())}</span>
        <h3>${escapeText(hero.title)}</h3>
        <div class="scoreboard"><span>${board.home ?? "—"}</span><small>${escapeText(board.period || "")} ${escapeText(board.clock || "")}</small><span>${board.away ?? "—"}</span></div>
        ${hero.status === "live" ? `<button type="button" data-event="${hero.event_id}">Watch live</button>` : "<p class='sub'>Watch live unlocks when the game starts.</p>"}
        <p class="post-whisper">Community theater — the gym, the field, the stands.</p>
      </div>`;
      loadLiveMoments(hero.event_id);
    } else {
      $("#live-hero").innerHTML = "";
      $("#live-moments").innerHTML = "";
    }
    $("#live-list").innerHTML = events.map(liveCard).join("")
      || "<p class='empty'>No live or upcoming games in your zone.</p>";
    $$("#live-list [data-event], #live-hero [data-event]").forEach(button => button.onclick = () => {
      playMedia(`/api/member/events/${button.dataset.event}/playback`, button.closest("article, .live-hero").querySelector("h3").textContent, "Authorized playback lease issued");
    });
    $$("#live-list [data-party]").forEach(button => button.onclick = () => startWatchParty(button.dataset.party));
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
  ).join("") : "<div class='empty-frame'><span class='empty-kicker'>Inbox</span><p class='empty'>No shared media yet. When someone sends a moment from the stands, it shows up here.</p></div>";
  $$("#inbox-list [data-read]").forEach(btn => btn.onclick = async () => {
    await api("POST", `/api/network/inbox/${btn.dataset.read}/read`);
    loadInbox();
  });
}

async function loadSaved() {
  try {
    const data = await api("GET", "/api/member/saved");
    $("#saved-list").innerHTML = data.items && data.items.length
      ? data.items.map(item => item.post_id ? postCard(item) : `<article class="post-card"><div class="post-body"><p class="post-caption">${escapeText(item.caption || item.game_id || "Saved")}</p></div></article>`).join("")
      : "<div class='empty-frame'><span class='empty-kicker'>Saved</span><p class='empty'>Keep a muddy-cleats moment or a packed-gym clip. It waits here.</p></div>";
    bindCards($("#saved-list"));
  } catch (error) { toast(error.message); }
}

async function loadFriends() {
  try {
    const data = await api("GET", "/api/member/friends/activity");
    const row = $("#friends-row");
    if (!data.items || !data.items.length) { row.classList.add("hidden"); row.innerHTML = ""; return; }
    row.classList.remove("hidden");
    row.innerHTML = data.items.map(item =>
      `<div class="friend-chip"><span class="avatar">${escapeText((item.display_name || "?").slice(0, 1))}</span>
       ${escapeText(item.display_name)}<small>${escapeText(item.activity)}</small></div>`
    ).join("");
  } catch (_) { $("#friends-row").classList.add("hidden"); }
}

async function loadNotifications() {
  try {
    const data = await api("GET", "/api/member/notifications");
    const badge = $("#notify-badge");
    if (data.unread_count) { badge.textContent = data.unread_count; badge.classList.remove("hidden"); }
    else badge.classList.add("hidden");
    if ($("#notify-list")) {
      $("#notify-list").innerHTML = (data.items || []).map(n =>
        `<article class="post-card"><p><strong>${escapeText(n.type)}</strong> ${escapeText((n.actor && n.actor.display_name) || "")}</p>
         ${n.read_at ? "" : `<button type="button" data-nread="${n.notification_id}">Mark read</button>`}</article>`
      ).join("") || "<p class='empty'>No notifications.</p>";
      $$("#notify-list [data-nread]").forEach(btn => btn.onclick = async () => {
        await api("POST", `/api/member/notifications/${btn.dataset.nread}/read`);
        loadNotifications();
      });
    }
  } catch (_) { /* ignore */ }
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
    $("#profile-list").innerHTML = "<div class='empty-frame'><span class='empty-kicker'>Profile</span><p class='empty'>Nothing here yet. Your community moments will frame this space.</p></div>";
    return;
  }
  $("#profile-list").innerHTML = data.items.map(item => {
    if (item.post_id) return postCard(item);
    if (item.game_id) {
      const status = item.verification_status || item.processing_status;
      return `<article class="post-card"><span class="pill">${escapeText(status)}</span>
        <h3>${escapeText(item.home_team_name)} vs ${escapeText(item.away_team_name)}</h3>
        <p class="sub">${escapeText(item.game_number)} · ${escapeText(item.sport)}</p>
        <button type="button" data-open-game="${item.game_id}">Open game</button></article>`;
    }
    return `<article class="post-card"><p class="prov">${escapeText((item.provenance || {}).label || "Clip")}</p>
      <p>${escapeText(item.caption || "")}</p></article>`;
  }).join("");
  bindCards($("#profile-list"));
}

function clampStudio(start, end) {
  const duration = state.studioDuration || 0;
  const maxClip = state.maxClipSeconds || 60;
  const minClip = state.minClipSeconds || 5;
  start = Math.max(0, Number(start) || 0);
  end = Number(end);
  if (!(end > start)) end = start + minClip;
  if (duration > 0) end = Math.min(end, duration);
  if (end - start > maxClip) end = start + maxClip;
  if (end - start < minClip && duration >= minClip) end = Math.min(duration, start + minClip);
  if (duration > 0 && end > duration) {
    end = duration;
    start = Math.max(0, end - maxClip);
  }
  return [Math.round(start * 10) / 10, Math.round(end * 10) / 10];
}

function syncStudio(fromRange) {
  const form = $("#studio-form");
  const startRange = $("#studio-start-range");
  const endRange = $("#studio-end-range");
  let start = fromRange ? Number(startRange.value) : Number(form.start_seconds.value);
  let end = fromRange ? Number(endRange.value) : Number(form.end_seconds.value);
  [start, end] = clampStudio(start, end);
  form.start_seconds.value = start;
  form.end_seconds.value = end;
  const max = String(state.studioDuration || state.maxClipSeconds);
  startRange.max = max;
  endRange.max = max;
  startRange.value = String(start);
  endRange.value = String(end);
  const pct = value => state.studioDuration ? (value / state.studioDuration) * 100 : 0;
  $("#studio-fill").style.left = pct(start) + "%";
  $("#studio-fill").style.width = Math.max(0, pct(end) - pct(start)) + "%";
  $("#studio-range-text").textContent = `${start}–${end}s`;
}

function bindStudio() {
  const video = $("#studio-video");
  video.onloadedmetadata = () => {
    state.studioDuration = video.duration || state.maxClipSeconds;
    const form = $("#studio-form");
    if (!form.start_seconds.value) form.start_seconds.value = "0";
    if (!form.end_seconds.value) {
      form.end_seconds.value = String(Math.min(20, state.studioDuration, state.maxClipSeconds));
    }
    syncStudio(false);
  };
  video.ontimeupdate = () => {
    if (!state.previewing) return;
    const end = Number($("#studio-form").end_seconds.value);
    if (video.currentTime >= end - 0.05) {
      video.pause();
      state.previewing = false;
    }
  };
  $("#studio-start-range").oninput = () => syncStudio(true);
  $("#studio-end-range").oninput = () => syncStudio(true);
  $("#studio-form").start_seconds.oninput = () => syncStudio(false);
  $("#studio-form").end_seconds.oninput = () => syncStudio(false);
  $("#studio-preview").onclick = () => {
    syncStudio(false);
    const start = Number($("#studio-form").start_seconds.value);
    state.previewing = true;
    video.currentTime = start;
    video.play().catch(() => {});
  };
}

async function loadStudioSources() {
  try {
    const data = await api("GET", "/api/member/studio/sources");
    const select = $("#studio-source");
    select.innerHTML = (data.games || []).map(g =>
      `<option value="${g.game_id}" data-event="${g.event_id || ""}" data-asset="${g.source_media_asset_id}">${escapeText(g.title)} · ${escapeText(g.sport)}</option>`
    ).join("") || "<option value=''>No entitled source games</option>";
    if (data.games && data.games[0]) await selectStudioGame(data.games[0].game_id);
  } catch (error) { toast(error.message); }
}

async function selectStudioGame(gameId) {
  if (!gameId) return;
  await openStudio(gameId, false);
}

async function openStudio(gameId, switchView = true) {
  const data = await api("GET", `/api/network/games/${gameId}`);
  const game = data.game;
  $("#studio-form").game_id.value = gameId;
  $("#studio-form").start_seconds.value = "0";
  $("#studio-form").end_seconds.value = "";
  $("#studio-status").textContent = game.can_create_clip ? "Ready to clip" : "Game not ready";
  $("#studio-publish").disabled = !game.can_create_clip;
  $("#studio-save").disabled = !game.can_create_clip;
  if (game.source_media_asset_id) {
    $("#studio-video").src = `/api/network/media/${game.source_media_asset_id}`;
  }
  if (game.event_id) {
    try {
      const tl = await api("GET", `/api/member/events/${game.event_id}/timeline`);
      const dur = (tl.duration_ms || (game.duration_seconds || 1) * 1000);
      $("#studio-markers").innerHTML = (tl.moments || []).map(m => {
        const left = dur ? (m.start_ms / dur) * 100 : 0;
        return `<span title="${escapeText(m.label)}" style="left:${left}%"></span>`;
      }).join("");
    } catch (_) { $("#studio-markers").innerHTML = ""; }
  }
  if (switchView) {
    location.hash = "studio";
    setView("studio");
  }
}

async function openGame(gameId) {
  state.gameId = gameId;
  let data;
  try {
    data = await api("GET", `/api/network/games/${gameId}`);
  } catch (error) {
    setView("game");
    $("#game-title").textContent = "Game unavailable";
    $("#game-meta").textContent = "";
    $("#game-state").textContent = error.message || "Not authorized";
    $("#game-video").classList.add("hidden");
    $("#game-unavailable").classList.remove("hidden");
    $("#create-clip-btn").disabled = true;
    return;
  }
  const game = data.game;
  setView("game");
  $("#game-title").textContent = `${game.home_team_name} vs ${game.away_team_name}`;
  $("#game-meta").textContent = [
    game.game_number, game.sport, game.season, game.level, game.venue,
  ].filter(Boolean).join(" · ");
  const restricted = game.verification_status === "rights_restricted" || game.verification_status === "rejected";
  $("#game-state").textContent = restricted
    ? "This game is restricted or rejected."
    : game.can_watch ? "Authorized source game" : "Not authorized to watch this game";
  $("#create-clip-btn").disabled = !game.can_create_clip;
  $("#create-clip-btn").dataset.gameId = gameId;
  if (game.can_watch && game.source_media_asset_id) {
    $("#game-unavailable").classList.add("hidden");
    $("#game-video").classList.remove("hidden");
    try {
      const play = await api("POST", `/api/network/games/${gameId}/playback`);
      $("#game-video").src = play.media_url;
    } catch (error) {
      $("#game-video").classList.add("hidden");
      $("#game-unavailable").classList.remove("hidden");
      $("#game-unavailable").textContent = error.message || "This game is not currently available with your access.";
    }
  } else {
    $("#game-video").classList.add("hidden");
    $("#game-unavailable").classList.remove("hidden");
  }
}

async function loadFeed() {
  const root = $("#feed-list");
  root.innerHTML = "<div class='empty-frame'><span class='empty-kicker'>Huddle</span><p class='empty'>Loading your community’s moments…</p></div>";
  try {
    const sport = state.sport ? `&sport=${encodeURIComponent(state.sport)}` : "";
    const data = await api("GET", `/api/member/feed?view=${state.mode}${sport}`);
    if (!data.items.length) {
      root.innerHTML = "<div class='empty-frame'><span class='empty-kicker'>Awaiting a sideline shot</span><p class='empty'>Nothing in this huddle yet. Parent-shot moments and packed-gym energy land here.</p></div>";
      return;
    }
    root.innerHTML = data.items.map(postCard).join("");
    bindCards(root);
  } catch (error) {
    root.innerHTML = "<div class='empty-frame'><span class='empty-kicker'>Huddle</span><p class='empty'>Could not load the huddle.</p></div>";
    toast(error.message);
  }
}

async function loadPublicFeed() {
  try {
    const data = await api("GET", "/api/network/feed?mode=for_you");
    $("#public-feed").innerHTML = (data.items || []).slice(0, 3).map(postCard).join("");
    bindCards($("#public-feed"));
  } catch (_) { /* unsigned catalog is optional */ }
}

async function loadPortal() {
  const me = await api("GET", "/api/member/me");
  showSignedIn(me.member, me.profile);
  if (me.settings) {
    $("#profile-form").show_watching_to_friends.checked = !!me.settings.show_watching_to_friends;
  }
  if (typeof me.unread_notifications === "number" && me.unread_notifications > 0) {
    $("#notify-badge").textContent = me.unread_notifications;
    $("#notify-badge").classList.remove("hidden");
  }
  await Promise.all([loadFeed(), loadCatalog(), loadNotifications()]);
  if (!state.notifyTimer) {
    state.notifyTimer = setInterval(() => { if (state.signedIn) loadNotifications(); }, 30000);
  }
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

function authError(error) {
  return error.message + (error.code ? " (" + error.code + ")" : "");
}

async function submitAuth(path, body) {
  const result = await api("POST", path, body);
  if (result.home === "/ops" && !pendingPlayback()) { location.href = "/ops"; return; }
  await loadPortal();
}

$("#login-form").addEventListener("submit", async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target).entries());
  try { await submitAuth("/api/auth/login", data); }
  catch (error) { toast(authError(error)); }
});
$("#register-form").addEventListener("submit", async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target).entries());
  try { await submitAuth("/api/auth/register", data); }
  catch (error) { toast(authError(error)); }
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
  await api("POST", "/api/auth/logout");
  location.reload();
};
window.addEventListener("hashchange", applyRoute);
window.addEventListener("pagehide", () => stopPortalMedia("pagehide"));
$$("#section-nav a, #bottom-nav a").forEach(link => link.onclick = event => {
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
$("#create-btn").onclick = $("#bottom-create").onclick = () => {
  $("#composer").classList.add("hidden");
  $("#create-dialog").showModal();
};
$("#notify-btn").onclick = () => { location.hash = "notifications"; };
$$(".create-choices [data-kind]").forEach(btn => btn.onclick = () => {
  state.kind = btn.dataset.kind;
  $("#composer").classList.remove("hidden");
  $("#composer-kind").textContent = btn.dataset.kind === "game" ? "Full Game" : btn.dataset.kind === "clip" ? "Clip" : "Photo";
  $("#game-fields").classList.toggle("hidden", state.kind !== "game");
  $("#composer-tags").classList.toggle("hidden", state.kind === "game");
  $("#game-fields").querySelector("[name=rights_attestation]").required = state.kind === "game";
  $("#composer-file").accept = state.kind === "photo" ? "image/*" : "video/*";
});
$("#composer-file").onchange = () => {
  const file = $("#composer-file").files[0];
  const video = $("#composer-preview");
  const photo = $("#composer-photo");
  video.classList.add("hidden");
  photo.classList.add("hidden");
  if (!file) return;
  if (file.type.startsWith("video/")) {
    video.src = URL.createObjectURL(file);
    video.classList.remove("hidden");
  } else if (file.type.startsWith("image/")) {
    photo.src = URL.createObjectURL(file);
    photo.classList.remove("hidden");
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
      toast("Game ready");
      $("#create-dialog").close();
      openGame(game.game.game_id);
      return;
    }
    status.textContent = "Requesting direct upload…";
    const upload = await api("POST", "/api/network/uploads", { kind: state.kind });
    const file = $("#composer-file").files[0];
    if (state.kind === "photo") {
      status.textContent = "Uploading photo to object storage…";
      const url = String(upload.upload_url || "");
      const localFake = url.includes("photos.test") || url.startsWith("/");
      const token = (upload.upload_token || url.split("?")[0].split("/").pop());
      if (file && upload.upload_method === "put" && !localFake) {
        await fetch(url, { method: "PUT", body: file, credentials: "include" });
        await api("POST", `/api/network/provider/fake/upload/${token}`, {
          filename: file.name,
          byte_size: file.size,
        });
      } else if (file && localFake) {
        const ctype = (file.type && file.type.startsWith("image/")) ? file.type : "image/jpeg";
        const resp = await fetch(`/api/network/provider/fake/upload/${token}`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": ctype },
          body: file,
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          const err = Error(data.error || "Photo upload failed");
          err.code = data.code;
          throw err;
        }
      } else {
        await api("POST", `/api/network/provider/fake/upload/${token}`, {
          filename: file && file.name,
          byte_size: file && file.size,
        });
      }
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
      tagged_handles: parseList(form.tagged_handles.value),
      tagged_team_ids: parseList(form.tagged_teams.value),
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

async function studioCreate(publish) {
  syncStudio(false);
  const form = $("#studio-form");
  $("#studio-status").textContent = "Creating clip definition…";
  const clip = await api("POST", "/api/network/clips", {
    source_game_id: form.game_id.value,
    start_seconds: Number(form.start_seconds.value),
    end_seconds: Number(form.end_seconds.value),
    caption: form.caption.value || form.title.value,
    visibility: form.visibility.value,
  });
  state.lastClipId = clip.clip.clip_id;
  $("#studio-status").textContent = "Rendering derived clip…";
  await api("POST", `/api/network/clips/${clip.clip.clip_id}/render`);
  if (!publish) {
    $("#studio-status").textContent = "Saved privately. Post to Huddle when you want it public.";
    toast("Clip saved");
    return clip;
  }
  $("#studio-status").textContent = "Publishing…";
  const post = await api("POST", `/api/network/clips/${clip.clip.clip_id}/publish`, {
    caption: form.caption.value || form.title.value, visibility: form.visibility.value,
  });
  state.lastPostId = post.post && post.post.post_id;
  $("#studio-status").textContent = "Posted to Huddle";
  toast("Clip published");
  loadFeed();
  return post;
}

$("#studio-form").onsubmit = async event => {
  event.preventDefault();
  try { await studioCreate(true); }
  catch (error) {
    $("#studio-status").textContent = error.message;
    toast(error.message);
  }
};
$("#studio-save").onclick = async () => {
  try { await studioCreate(false); }
  catch (error) {
    $("#studio-status").textContent = error.message;
    toast(error.message);
  }
};
$("#studio-share").onclick = async () => {
  if (!state.lastPostId) { toast("Post to Huddle first"); return; }
  try {
    const res = await api("POST", `/api/member/posts/${state.lastPostId}/share`, { destination: "copy_link" });
    await navigator.clipboard.writeText(res.url);
    toast("Copied " + res.url);
  } catch (error) { toast(error.message); }
};
$("#studio-source").onchange = () => selectStudioGame($("#studio-source").value);
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
    await api("POST", "/api/member/settings", {
      show_watching_to_friends: $("#profile-form").show_watching_to_friends.checked,
    });
    toast("Profile saved");
    loadProfileTab();
  } catch (error) { toast(error.message); }
};
async function openSearchItem(item) {
  $("#search-results").classList.add("hidden");
  if (item.kind === "person" && item.handle) {
    location.hash = "profile";
    return;
  }
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
$("#game-back").onclick = () => {
  setView("huddle");
  if ((location.hash || "").replace(/^#/, "") !== "huddle") location.hash = "huddle";
};
$("#create-clip-btn").onclick = () => {
  if (state.gameId) openStudio(state.gameId);
};
async function startWatchParty(eventId) {
  try {
    const party = await api("POST", "/api/member/watch-parties", { event_id: eventId, visibility: "friends" });
    toast("Watch party " + party.join_code + " — chat is separate from the game feed");
    connectPartySocket(party.party_id);
  } catch (error) { toast(error.message); }
}
$("#watch-party-btn").onclick = () => {
  const eventId = state.heroEventId;
  if (eventId) startWatchParty(eventId);
};
bindStudio();
(async () => {
  try {
    player.config = await api("GET", "/api/config");
    if (player.config && player.config.max_game_clip_seconds) {
      state.maxClipSeconds = Number(player.config.max_game_clip_seconds);
      state.minClipSeconds = Number(player.config.min_game_clip_seconds || 5);
      $("#studio-max").textContent = String(state.maxClipSeconds);
      $("#studio-start-range").max = String(state.maxClipSeconds);
      $("#studio-end-range").max = String(state.maxClipSeconds);
    }
  } catch (_) { /* keep default 60s cap */ }
  try { await loadPortal(); }
  catch (_) {
    loadPublicFeed();
    applyRoute();
  }
  if (player.config && player.config.simulation) {
    const hint = $("#demo-hint");
    if (hint) {
      hint.textContent = "Local demo: demo-viewer / change-me-viewer-local — or create an account.";
      hint.classList.remove("hidden");
    }
  }
})();
