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
  if (!response.ok) throw Error(data.error || "Request failed");
  return data;
};
const toast = text => {
  $("#toast").textContent = text; $("#toast").classList.remove("hidden");
  setTimeout(() => $("#toast").classList.add("hidden"), 3000);
};
const STAFF = new Set(["operator", "owner", "admin"]);
const card = (title, state, id) => `<article><span class="pill">${state}</span><h3>${title}</h3><button data-event="${id}" type="button">Watch</button></article>`;

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
(async () => {
  try { await loadPortal(); } catch (_) {}
})();
$("#search").oninput = async event => {
  if (event.target.value.length < 2) return;
  const result = await api("GET", "/api/member/search?q=" + encodeURIComponent(event.target.value));
  toast(result.results.map(item => item.name).join(" · ") || "No authorized results");
};
