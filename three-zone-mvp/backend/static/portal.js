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
  if (!response.ok) throw Error(data.error || "Request failed");
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
const parseList = value => (value || "").split(",").map(part => part.trim()).filter(Boolean);
const STAFF = new Set(["operator", "owner", "admin"]);
const state = {
  profile: null, mode: "for_you", sport: "", kind: "photo", tab: "posts",
  maxClipSeconds: 90, studioDuration: 90, previewing: false, gameId: null,
};

function showSignedIn(member, profile) {
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
  if (name !== "watch") $("#player-wrap").classList.add("hidden");
}

function mediaUnavailable(reason) {
  return `<div class="media-ph">${escapeText(reason || "Media unavailable")}</div>`;
}

function mediaTag(item) {
  if (item.content_state === "restricted" || item.publication_status === "restricted") {
    return mediaUnavailable("This post is restricted");
  }
  if (item.content_state === "removed" || item.publication_status === "removed") {
    return mediaUnavailable("This post was removed");
  }
  const id = item.derived_media_asset_id || item.media_asset_id || item.source_media_asset_id;
  if (!id) return mediaUnavailable("Media unavailable");
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
  const tags = (item.athlete_tags || []).map(tag =>
    `<span class="pill">@${escapeText(tag.handle)}</span>`
  ).join(" ");
  const restricted = item.content_state === "restricted" || item.publication_status === "restricted";
  const removed = item.content_state === "removed" || item.publication_status === "removed";
  const actions = (restricted || removed) ? "" : `<div class="actions">
      <button type="button" data-like="post:${item.post_id}">Like ${item.like_count || 0}</button>
      <button type="button" data-save="post:${item.post_id}">Save</button>
      <button type="button" data-send="post:${item.post_id}">Send</button>
      <button type="button" class="quiet" data-report="post:${item.post_id}">Report</button>
    </div>
    <form class="comment-form" data-subject="post:${item.post_id}">
      <label>Comment <input name="body" maxlength="500" /></label>
      <button type="submit">Comment</button>
    </form>`;
  return `<article class="post-card">
    <header><strong>${escapeText(item.author.display_name)}</strong>
      <span class="sub">@${escapeText(item.author.handle)} · ${escapeText(item.author.profile_type)}</span>
      ${badge}</header>
    ${mediaTag(item)}
    <p>${escapeText(item.caption)}</p>
    <p class="sub">${escapeText(item.sport)}${tags ? " · " + tags : ""}</p>
    ${provenance}${watch}
    ${actions}
  </article>`;
}

async function loadFeed() {
  const root = $("#feed-list");
  root.innerHTML = "<p class='empty'>Loading feed…</p>";
  try {
    const sport = state.sport ? `&sport=${encodeURIComponent(state.sport)}` : "";
    const data = await api("GET", `/api/network/feed?mode=${state.mode}${sport}`);
    if (!data.items.length) {
      root.innerHTML = "<p class='empty'>No posts in this feed yet.</p>";
      return;
    }
    root.innerHTML = data.items.map(postCard).join("");
    bindCards(root);
  } catch (_) {
    root.innerHTML = "<p class='empty'>Feed is unavailable right now.</p>";
  }
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

function bindMediaErrors(root) {
  root.querySelectorAll("video, img").forEach(el => {
    el.addEventListener("error", () => {
      const ph = document.createElement("div");
      ph.className = "media-ph";
      ph.textContent = "Media unavailable";
      el.replaceWith(ph);
    });
  });
}

function bindCards(root) {
  bindMediaErrors(root);
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

async function loadCatalog() {
  const card = (title, stateLabel, id) =>
    `<article><span class="pill">${stateLabel}</span><h3>${escapeText(title)}</h3>
     <button data-event="${id}" type="button">Watch</button></article>`;
  try {
    const live = await api("GET", "/api/member/live");
    $("#live-list").innerHTML = live.events.map(e => card(e.title, e.status === "live" ? "LIVE" : "UPCOMING", e.event_id)).join("");
    $$("[data-event]").forEach(button => button.onclick = () => play(button.dataset.event));
  } catch (error) { toast(error.message); }
  try {
    const schedules = await api("GET", "/api/member/schedules");
    $("#schedule-list").innerHTML = schedules.schedules.map(s =>
      `<div class="schedule-row"><b>${escapeText(s.team)}</b><span>${escapeText(s.opponent)}</span>
       <span>${new Date(s.start_at * 1000).toLocaleDateString()}</span><small>${escapeText(s.location)}</small></div>`
    ).join("");
  } catch (error) { toast(error.message); }
  try {
    const archives = await api("GET", "/api/member/archives");
    $("#archive-list").innerHTML = archives.archives.map(a =>
      `<article><span class="pill">ARCHIVED</span><h3>${escapeText(a.title)}</h3>
       <p>${escapeText(a.school)} · ${escapeText(a.team)}<br>${escapeText(a.season)} · ${escapeText(a.kind)}</p></article>`
    ).join("");
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
  const maxClip = state.maxClipSeconds || 90;
  start = Math.max(0, Number(start) || 0);
  end = Number(end);
  if (!(end > start)) end = start + 0.1;
  if (duration > 0) end = Math.min(end, duration);
  if (end - start > maxClip) end = start + maxClip;
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

async function openStudio(gameId) {
  const data = await api("GET", `/api/network/games/${gameId}`);
  const game = data.game;
  $("#studio-form").game_id.value = gameId;
  $("#studio-form").start_seconds.value = "0";
  $("#studio-form").end_seconds.value = "";
  $("#studio-status").textContent = game.can_create_clip ? "Ready to clip" : "Game not ready";
  $("#studio-form").querySelector("[type=submit]").disabled = !game.can_create_clip;
  if (game.source_media_asset_id) {
    $("#studio-video").src = `/api/network/media/${game.source_media_asset_id}`;
  }
  $("#studio-dialog").showModal();
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

async function loadPortal() {
  const me = await api("GET", "/api/member/me");
  showSignedIn(me.member, me.profile);
  await Promise.all([loadFeed(), loadCatalog()]);
}

async function submitAuth(path, body) {
  const result = await api("POST", path, body);
  if (result.session_token) sessionStorage.setItem("tz_session", result.session_token);
  if (result.home === "/ops") { location.href = "/ops"; return; }
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
async function play(eventId) {
  try {
    const result = await api("POST", `/api/member/events/${eventId}/playback`);
    $("#player-wrap").classList.remove("hidden");
    $("#player-title").textContent = "Now playing";
    $("#player-state").textContent = "Authorized playback lease issued";
    $("#video").src = result.media_url + "?lease=" + result.lease_id;
    $("#video").play().catch(() => {});
  } catch (_) { toast("This game is not currently available with your access."); }
}
$("#signout").onclick = async () => {
  sessionStorage.removeItem("tz_session");
  await api("POST", "/api/auth/logout");
  location.reload();
};
$$("#section-nav a").forEach(link => link.onclick = event => {
  event.preventDefault();
  const view = link.dataset.view;
  setView(view);
  if (view === "feed") loadFeed();
  if (view === "inbox") loadInbox();
  if (view === "profile") loadProfileTab();
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
    status.textContent = state.kind === "clip" ? "Uploading clip…" : "Uploading photo…";
    await api("POST", upload.upload_url, {
      duration_seconds: state.kind === "clip" ? 20 : 0,
      filename: ($("#composer-file").files[0] || {}).name,
    });
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
$("#studio-form").onsubmit = async event => {
  event.preventDefault();
  syncStudio(false);
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
$("#search").oninput = async event => {
  if (event.target.value.length < 2) return;
  try {
    const result = await api("GET", "/api/member/search?q=" + encodeURIComponent(event.target.value));
    toast(result.results.map(item => item.name).join(" · ") || "No authorized results");
  } catch (error) { toast(error.message); }
};
$("#game-back").onclick = () => {
  setView("profile");
  loadProfileTab();
};
$("#create-clip-btn").onclick = () => {
  if (state.gameId) openStudio(state.gameId);
};
bindStudio();
(async () => {
  try {
    const cfg = await api("GET", "/api/config");
    if (cfg.max_game_clip_seconds) {
      state.maxClipSeconds = Number(cfg.max_game_clip_seconds);
      $("#studio-max").textContent = String(state.maxClipSeconds);
      $("#studio-start-range").max = String(state.maxClipSeconds);
      $("#studio-end-range").max = String(state.maxClipSeconds);
    }
  } catch (_) { /* keep default 90s cap */ }
  try { await loadPortal(); }
  catch (_) { loadPublicFeed(); }
})();
