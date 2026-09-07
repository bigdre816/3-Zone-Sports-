"use strict";
const $ = s => document.querySelector(s);
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
const STAFF = new Set(["operator", "owner", "admin"]);
const card = (title, state, id) => `<article><span class="pill">${state}</span><h3>${title}</h3><button data-event="${id}" type="button">Watch</button></article>`;

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
  if (!player.config || !sessionStorage.getItem("tz_session")) return;
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

function showSignedIn(member) {
  $("#auth").classList.add("hidden");
  $("#portal").classList.remove("hidden");
  $("#section-nav").classList.remove("hidden");
  $("#signout").classList.remove("hidden");
  $("#member-name").textContent = member.display_name;
  $("#ops-link").classList.toggle("hidden", !STAFF.has(member.role));
}

async function loadPortal() {
  const me = await api("GET", "/api/member/me");
  showSignedIn(me.member);
  const fill = async (path, render) => {
    try { render(await api("GET", path)); }
    catch (error) { toast(error.message); }
  };
  await Promise.all([
    fill("/api/member/live", live => {
      $("#live-list").innerHTML = live.events.map(e => card(e.title, e.status === "live" ? "LIVE" : "UPCOMING", e.event_id)).join("");
      document.querySelectorAll("[data-event]").forEach(button => button.onclick = () => play(button.dataset.event));
    }),
    fill("/api/member/schedules", schedules => {
      $("#schedule-list").innerHTML = schedules.schedules.map(s => `<div class="schedule-row"><b>${s.team}</b><span>${s.opponent}</span><span>${new Date(s.start_at * 1000).toLocaleDateString()}</span><small>${s.location}</small></div>`).join("");
    }),
    fill("/api/member/archives", archives => {
      $("#archive-list").innerHTML = archives.archives.map(a => `<article><span class="pill">ARCHIVED</span><h3>${a.title}</h3><p>${a.school} · ${a.team}<br>${a.season} · ${a.kind}</p></article>`).join("");
    }),
  ]);
}

async function submitAuth(path, body) {
  const result = await api("POST", path, body);
  if (result.session_token) sessionStorage.setItem("tz_session", result.session_token);
  if (result.home === "/ops") {
    location.href = "/ops";
    return;
  }
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
    stopPortalMedia("pagehide");
    player.eventId = eventId;
    if (!player.config) player.config = await api("GET", "/api/config");
    const result = await api("POST", `/api/member/events/${eventId}/playback`);
    $("#player-wrap").classList.remove("hidden");
    $("#player-title").textContent = "Now playing";
    $("#player-state").textContent = result.media_type === "hls"
      ? "Authorized HLS lease issued"
      : "Authorized playback lease issued";
    attachPortalMedia(result.media_url, result.media_type);
    const session = await api("POST", `/api/events/${eventId}/view-sessions`, { lease_id: result.lease_id });
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
        const renewed = await api("POST", `/api/member/events/${eventId}/playback`);
        attachPortalMedia(renewed.media_url, renewed.media_type);
      } catch (_) { stopPortalMedia("lease_expired"); }
    }, wait);
    connectEventSocket(eventId);
  } catch (_) { toast("This game is not currently available with your access."); }
}
$("#signout").onclick = async () => {
  stopPortalMedia("logout");
  sessionStorage.removeItem("tz_session");
  await api("POST", "/api/auth/logout");
  location.reload();
};
(async () => {
  try { player.config = await api("GET", "/api/config"); } catch (_) {}
  try { await loadPortal(); } catch (_) {}
})();
window.addEventListener("pagehide", () => stopPortalMedia("pagehide"));
$("#search").oninput = async event => {
  if (event.target.value.length < 2) return;
  const result = await api("GET", "/api/member/search?q=" + encodeURIComponent(event.target.value));
  toast(result.results.map(item => item.name).join(" · ") || "No authorized results");
};
