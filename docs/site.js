'use strict';

const ThreeZoneSite = {
  UNAVAILABLE: {
    live: 'Games are temporarily unavailable. Try again shortly.',
    schedules: 'Schedules are temporarily unavailable. Try again shortly.',
    archives: 'Replays are temporarily unavailable. Try again shortly.',
    teams: 'Teams are temporarily unavailable. Try again shortly.',
    schools: 'Schools are temporarily unavailable. Try again shortly.',
    clips: 'Clips are temporarily unavailable. Try again shortly.',
  },

  el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (value == null || value === false) return;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key.slice(0, 2) === 'on' && typeof value === 'function') {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else {
        node.setAttribute(key, value === true ? '' : String(value));
      }
    });
    (children || []).forEach((child) => {
      if (child == null) return;
      node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
    });
    return node;
  },

  bindChrome() {
    const toggle = document.getElementById('menu-toggle');
    const nav = document.getElementById('main-nav');
    if (toggle && nav) {
      toggle.addEventListener('click', () => {
        nav.classList.toggle('open');
      });
    }
  },

  showUnavailable(container, kind) {
    const message = this.UNAVAILABLE[kind] || this.UNAVAILABLE.live;
    container.replaceChildren(this.el('div', { class: 'unavailable', text: message }));
  },

  showEmpty(container, message) {
    container.replaceChildren(this.el('div', { class: 'unavailable', text: message }));
  },

  gameHref(eventId) {
    return '/app/?event=' + encodeURIComponent(eventId);
  },

  archiveHref(archiveId) {
    return '/app/?archive=' + encodeURIComponent(archiveId);
  },

  formatWhen(epoch) {
    if (!epoch) return 'Time TBA';
    const date = new Date(Number(epoch) * 1000);
    if (Number.isNaN(date.getTime())) return 'Time TBA';
    return date.toLocaleString([], { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  },

  liveCard(event) {
    const live = event.status === 'live';
    const ready = event.status === 'green';
    const label = live ? 'LIVE NOW' : ready ? 'READY' : 'UPCOMING';
    const action = live
      ? this.el('a', { class: 'btn', href: this.gameHref(event.event_id), text: 'Watch' })
      : this.el('a', { class: 'btn secondary', href: '/schedules/', text: 'See schedule' });
    const score = event.scoreboard && (event.scoreboard.home != null || event.scoreboard.away != null)
      ? (event.scoreboard.home ?? '—') + ' – ' + (event.scoreboard.away ?? '—')
      : null;
    return this.el('article', { class: 'card' }, [
      this.el('div', { class: 'status' }, [
        this.el('span', { class: 'status-dot' + (live ? ' live' : '') }),
        this.el('strong', { text: label }),
      ]),
      this.el('h3', { text: event.title || 'Verified game' }),
      this.el('p', { text: [event.zone, event.category].filter(Boolean).join(' · ') || 'Three-Zone' }),
      score ? this.el('p', { class: 'score', text: score }) : null,
      action,
    ]);
  },

  scheduleCard(row) {
    return this.el('a', { class: 'card', href: '/schedules/' }, [
      this.el('h3', { text: (row.team || 'Team') + ' vs ' + (row.opponent || 'Opponent') }),
      this.el('p', { text: this.formatWhen(row.start_at) }),
      this.el('p', { text: [row.school, row.location || 'Location TBA'].filter(Boolean).join(' · ') }),
      this.el('div', { class: 'status' }, [
        this.el('span', { class: 'status-dot' }),
        document.createTextNode(row.home_away || row.status || 'Scheduled'),
      ]),
    ]);
  },

  archiveCard(row) {
    return this.el('article', { class: 'card' }, [
      this.el('h3', { text: row.title || 'Archived game' }),
      this.el('p', { text: [row.school, row.team].filter(Boolean).join(' · ') || 'Three-Zone archive' }),
      this.el('p', { text: [row.sport, row.level, row.season].filter(Boolean).join(' · ') }),
      this.el('a', { class: 'btn', href: this.archiveHref(row.archive_id), text: 'Watch replay' }),
    ]);
  },

  async loadLive(container, limit) {
    try {
      const data = await ThreeZoneConfig.fetch(ThreeZoneConfig.endpoints.public.live);
      const events = data.events || [];
      if (!events.length) {
        this.showEmpty(container, 'No games live right now. Check the schedule.');
        return events;
      }
      const cards = events.slice(0, limit || events.length).map((event) => this.liveCard(event));
      container.replaceChildren(...cards);
      return events;
    } catch (_) {
      this.showUnavailable(container, 'live');
      return [];
    }
  },

  async loadSchedules(container, limit) {
    try {
      const data = await ThreeZoneConfig.fetch(ThreeZoneConfig.endpoints.public.schedules);
      const rows = data.schedules || [];
      if (!rows.length) {
        this.showEmpty(container, 'No upcoming games found.');
        return rows;
      }
      const cards = rows.slice(0, limit || rows.length).map((row) => this.scheduleCard(row));
      container.replaceChildren(...cards);
      return rows;
    } catch (_) {
      this.showUnavailable(container, 'schedules');
      return [];
    }
  },

  async loadArchives(container, limit) {
    try {
      const data = await ThreeZoneConfig.fetch(ThreeZoneConfig.endpoints.public.archives);
      const rows = data.archives || [];
      if (!rows.length) {
        this.showEmpty(container, 'No replays yet. Check back after games conclude.');
        return rows;
      }
      const cards = rows.slice(0, limit || rows.length).map((row) => this.archiveCard(row));
      container.replaceChildren(...cards);
      return rows;
    } catch (_) {
      this.showUnavailable(container, 'archives');
      return [];
    }
  },

  uniqueBy(rows, key) {
    const seen = new Set();
    const out = [];
    rows.forEach((row) => {
      const value = (row[key] || '').trim();
      if (!value || seen.has(value)) return;
      seen.add(value);
      out.push(row);
    });
    return out;
  },
};

if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', () => {
    ThreeZoneSite.bindChrome();
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = ThreeZoneSite;
}
