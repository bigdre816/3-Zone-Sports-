"use strict";
const $ = s => document.querySelector(s);
const api = async (method, path, body) => {
  const response = await fetch(path, {method, credentials:"include",
    headers: body ? {"Content-Type":"application/json"} : {},
    body: body ? JSON.stringify(body) : undefined});
  const data = await response.json();
  if (!response.ok) throw Error(data.error || "Request failed");
  return data;
};
const toast = text => {
  $("#toast").textContent = text; $("#toast").classList.remove("hidden");
  setTimeout(() => $("#toast").classList.add("hidden"), 3000);
};
const card = (title, state, id) => `<article><span class="pill">${state}</span><h3>${title}</h3><button data-event="${id}">▶ Watch live</button></article>`;

async function loadPortal() {
  const me = await api("GET", "/api/member/me");
  $("#member-name").textContent = me.member.display_name.replace("Demo Member (viewer)", "Andre");
  const [live, schedules, archives] = await Promise.all([
    api("GET", "/api/member/live"), api("GET", "/api/member/schedules"), api("GET", "/api/member/archives")
  ]);
  $("#live").innerHTML = live.events.map(e => card(e.title, e.status === "live" ? "LIVE" : "UPCOMING", e.event_id)).join("");
  $("#schedules").innerHTML = schedules.schedules.map(s => `<div class="schedule-row"><b>${s.team}</b><span>${s.opponent}</span><span>${new Date(s.start_at * 1000).toLocaleDateString()}</span><small>${s.location}</small></div>`).join("");
  $("#archives").innerHTML = archives.archives.map(a => `<article><span class="pill">ARCHIVED</span><h3>${a.title}</h3><p>${a.school} · ${a.team}<br>${a.season} · ${a.kind}</p></article>`).join("");
  document.querySelectorAll("[data-event]").forEach(button => button.onclick = () => play(button.dataset.event));
}
async function enter() {
  try {
    const start = await api("POST", "/api/auth/start", {identifier:"demo-viewer"});
    await api("POST", "/api/auth/verify", {member_id:start.member_id});
    $("#landing").classList.add("hidden"); $("#portal").classList.remove("hidden");
    $("#enter").classList.add("hidden"); $("#signout").classList.remove("hidden");
    await loadPortal();
  } catch (error) { toast(error.message); }
}
async function play(eventId) {
  try {
    const result = await api("POST", `/api/member/events/${eventId}/playback`);
    $("#player-wrap").classList.remove("hidden"); $("#player-title").textContent = "Now playing";
    $("#player-state").textContent = "Authorized by Three-Zone · short-lived playback lease issued";
    $("#video").src = result.media_url + "?lease=" + result.lease_id;
    $("#video").play().catch(() => {});
  } catch (_) { toast("This game is not currently available with your access."); }
}
$("#enter").onclick = enter; $("#hero-enter").onclick = enter;
$("#signout").onclick = async () => { await api("POST", "/api/auth/logout"); location.reload(); };
$("#search").oninput = async event => {
  if (event.target.value.length < 2) return;
  const result = await api("GET", "/api/member/search?q=" + encodeURIComponent(event.target.value));
  toast(result.results.map(item => item.name).join(" · ") || "No authorized results");
};
