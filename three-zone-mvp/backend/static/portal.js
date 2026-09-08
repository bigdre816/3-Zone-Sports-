"use strict";

const $ = (sel) => document.querySelector(sel);
const pages = ["about", "support", "privacy", "terms"];
const sections = ["live", "schedules", "archives"];

const api = async (method, path, body) => {
  const response = await fetch(path, {
    method,
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || "Request failed");
  return data;
};

const toast = (text) => {
  $("#toast").textContent = text;
  $("#toast").classList.remove("hidden");
  setTimeout(() => $("#toast").classList.add("hidden"), 3000);
};

const statusLabel = (status) => {
  if (status === "live") return "LIVE";
  if (status === "replay") return "ENDED";
  if (status === "archive") return "ARCHIVED";
  if (status === "green" || status === "scheduled") return "UPCOMING";
  return "UNAVAILABLE";
};

function showAuthed(on) {
  $("#landing").classList.toggle("hidden", on);
  $("#enter").classList.toggle("hidden", on);
  $("#signin").classList.toggle("hidden", on);
  $("#signout").classList.toggle("hidden", !on);
}

function showHash() {
  const hash = (location.hash || "#home").slice(1);
  const authed = !$("#signout").classList.contains("hidden");
  document.querySelectorAll("nav a").forEach((a) => {
    a.classList.toggle("active", a.getAttribute("href") === "#" + hash);
  });

  if (pages.includes(hash)) {
    $("#landing").classList.add("hidden");
    $("#portal").classList.add("hidden");
    document.querySelectorAll(".page").forEach((el) => el.classList.add("hidden"));
    const page = $("#page-" + hash);
    if (page) page.classList.remove("hidden");
    return;
  }

  document.querySelectorAll(".page").forEach((el) => el.classList.add("hidden"));
  if (!authed) {
    $("#landing").classList.remove("hidden");
    $("#portal").classList.add("hidden");
    if (sections.includes(hash)) enter(hash);
    return;
  }

  $("#landing").classList.add("hidden");
  $("#portal").classList.remove("hidden");
  const showAll = !sections.includes(hash);
  $("#section-live").classList.toggle("hidden", !showAll && hash !== "live");
  $("#section-schedules").classList.toggle("hidden", !showAll && hash !== "schedules");
  $("#section-archives").classList.toggle("hidden", !showAll && hash !== "archives");
  const columns = document.querySelector(".columns");
  if (columns) columns.classList.toggle("hidden", !showAll && hash === "live");
}

async function loadPortal() {
  const me = await api("GET", "/api/member/me");
  $("#member-name").textContent = me.member.display_name;
  $("#demo-label").classList.toggle("hidden", !me.member.member_id.startsWith("demo-"));
  const [live, schedules, archives] = await Promise.all([
    api("GET", "/api/member/live"),
    api("GET", "/api/member/schedules"),
    api("GET", "/api/member/archives"),
  ]);
  $("#live").innerHTML = live.events.map((event) => {
    const hold = event.rights && (event.rights.revoked || !event.rights.active);
    const label = hold ? "RIGHTS HOLD" : statusLabel(event.status);
    const playable = event.status === "live" && !hold;
    let action = `<p>Available when this game goes live.</p>`;
    if (hold) action = `<p>This game is not currently available with your access.</p>`;
    else if (playable) action = `<button type="button" data-play="${event.event_id}" data-title="${event.title}">Watch live</button>`;
    return `<article id="event-${event.event_id}"><span class="pill">${label}</span><h3>${event.title}</h3>${action}</article>`;
  }).join("") || `<p class="empty">No live or upcoming games with your access.</p>`;

  $("#schedules").innerHTML = schedules.schedules.map((row) => `
    <div class="schedule-row">
      <b>${row.team}</b>
      <span>${row.home_away === "AWAY" ? "@" : "vs"} ${row.opponent}</span>
      <span>${new Date(row.start_at * 1000).toLocaleString()}</span>
      <small>${row.location}</small>
    </div>`).join("") || `<p class="empty">No schedules with your access.</p>`;

  $("#archives").innerHTML = archives.archives.map((item) => `
    <article>
      <span class="pill">ARCHIVED</span>
      <h3>${item.title}</h3>
      <p>${item.school} → ${item.team} → ${item.season} → ${item.kind}</p>
      <button type="button" data-archive="${item.archive_id}" data-event="${item.event_id}" data-title="${item.title}">Watch archive</button>
    </article>`).join("") || `<p class="empty">No archives with your access.</p>`;

  document.querySelectorAll("[data-play]").forEach((btn) => {
    btn.onclick = () => play(btn.dataset.play, btn.dataset.title, "live");
  });
  document.querySelectorAll("[data-archive]").forEach((btn) => {
    btn.onclick = () => playArchive(btn.dataset.archive, btn.dataset.event, btn.dataset.title);
  });
}

async function enter(nextHash) {
  try {
    const start = await api("POST", "/api/auth/start", { identifier: "demo-viewer" });
    await api("POST", "/api/auth/verify", { member_id: start.member_id });
    showAuthed(true);
    await loadPortal();
    location.hash = nextHash && nextHash !== "home" ? "#" + nextHash : "#live";
    showHash();
  } catch (error) {
    toast(error.message);
  }
}

function openPlayer(title, mediaUrl, leaseId, mode) {
  $("#player-wrap").classList.remove("hidden");
  $("#player-title").textContent = title;
  $("#player-state").textContent = mode === "archive"
    ? "Authorized archive playback · short-lived lease issued"
    : "Authorized by Three-Zone · short-lived playback lease issued";
  $("#video").src = mediaUrl + "?v=" + leaseId;
  $("#video").play().catch(() => {});
  $("#player-wrap").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function play(eventId, title, mode) {
  try {
    const result = await api("POST", `/api/member/events/${eventId}/playback`);
    openPlayer(title || "Now playing", result.media_url, result.lease_id, mode);
  } catch (_) {
    toast("This game is not currently available with your access.");
  }
}

async function playArchive(archiveId, eventId, title) {
  try {
    const result = await api("POST", `/api/member/archive/${archiveId}/playback`);
    openPlayer(title || "Archive", result.media_url, result.lease_id, "archive");
  } catch (_) {
    play(eventId, title, "archive");
  }
}

async function search(term) {
  const box = $("#search-results");
  if (term.length < 2) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  const result = await api("GET", "/api/member/search?q=" + encodeURIComponent(term));
  if (!result.results.length) {
    box.classList.remove("hidden");
    box.innerHTML = `<p>No authorized results.</p>`;
    return;
  }
  box.classList.remove("hidden");
  box.innerHTML = result.results.map((item) => {
    const dest = item.kind === "game" ? "live" : item.kind === "archive" ? "archives" : "schedules";
    return `<button type="button" class="search-hit" data-kind="${item.kind}" data-id="${item.id || item.team_id || item.school_id || ""}" data-dest="${dest}">${item.name} <small>${item.kind}</small></button>`;
  }).join("");
  box.querySelectorAll(".search-hit").forEach((btn) => {
    btn.onclick = () => {
      location.hash = "#" + btn.dataset.dest;
      showHash();
      if (btn.dataset.kind === "game") {
        const card = $("#event-" + btn.dataset.id);
        if (card) {
          card.scrollIntoView({ behavior: "smooth", block: "center" });
          const watch = card.querySelector("[data-play]");
          if (watch) watch.click();
        }
      }
    };
  });
}

$("#enter").onclick = () => enter("live");
$("#hero-enter").onclick = () => enter("live");
$("#signin").onclick = () => enter("live");
$("#signout").onclick = async () => {
  await api("POST", "/api/auth/logout");
  location.hash = "";
  location.reload();
};
$("#search").addEventListener("input", (event) => search(event.target.value.trim()));
window.addEventListener("hashchange", showHash);

(async () => {
  try {
    await api("GET", "/api/member/me");
    showAuthed(true);
    await loadPortal();
  } catch (_) {
    showAuthed(false);
  }
  showHash();
})();
