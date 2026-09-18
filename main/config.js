/**
 * Public site configuration. Fetch the Render API; send members to
 * app.3zonesports.com (the member-facing product). Do not surface
 * infrastructure origins in page copy, forms, or status badges.
 */

const PRODUCTION_API_ORIGIN = 'https://three-zone-sports-1.onrender.com';
const MEMBER_APP_ORIGIN = 'https://app.3zonesports.com';

const ThreeZoneConfig = {
  PRODUCTION_API_ORIGIN,
  MEMBER_APP_ORIGIN,

  endpoints: {
    health: '/api/health',
    public: {
      live: '/api/public/live',
      schedules: '/api/public/schedules',
      archives: '/api/public/archives',
    },
  },

  _origin() {
    if (typeof window !== 'undefined' && window.__THREE_ZONE_BACKEND_URL__) {
      return String(window.__THREE_ZONE_BACKEND_URL__).replace(/\/+$/, '');
    }
    if (typeof window !== 'undefined') {
      const host = String(window.location.hostname || '');
      if (host === 'localhost' || host === '127.0.0.1') {
        return 'http://' + host + ':8000';
      }
    }
    return PRODUCTION_API_ORIGIN;
  },

  memberOrigin() {
    if (typeof window !== 'undefined') {
      const host = String(window.location.hostname || '');
      if (host === 'localhost' || host === '127.0.0.1') {
        return this._origin();
      }
    }
    return MEMBER_APP_ORIGIN;
  },

  memberAppPath(search) {
    const raw = String(search || '');
    const queryIndex = raw.indexOf('?');
    const query = queryIndex === -1 ? '' : raw.slice(queryIndex + 1);
    let eventId = '';
    let archiveId = '';
    let destination = '';
    query.split('&').forEach(function (part) {
      if (!part) return;
      const idx = part.indexOf('=');
      let key = idx === -1 ? part : part.slice(0, idx);
      let value = idx === -1 ? '' : part.slice(idx + 1);
      try {
        key = decodeURIComponent(key.replace(/\+/g, ' '));
      } catch (_) {
        key = key.replace(/\+/g, ' ');
      }
      try {
        value = decodeURIComponent(value.replace(/\+/g, ' '));
      } catch (_) {
        value = value.replace(/\+/g, ' ');
      }
      if (key === 'event' && eventId === '') eventId = value;
      if (key === 'archive' && archiveId === '') archiveId = value;
      if (key === 'to' && destination === '') destination = value;
    });
    if (eventId) return '/game/' + encodeURIComponent(eventId);
    if (archiveId) return '/archive/' + encodeURIComponent(archiveId);
    const destinations = {
      auth: '/auth',
      me: '/me',
      live: '/live',
      clips: '/clips',
      archive: '/archive',
    };
    if (destinations[destination]) return destinations[destination];
    return '/';
  },

  async memberAppUrl(path) {
    const suffix = path == null || path === '' ? '/' : path;
    return this.memberOrigin() + suffix;
  },

  async fetch(endpoint, options) {
    const baseUrl = this._origin();
    const response = await fetch(baseUrl + endpoint, {
      credentials: 'include',
      headers: options && options.headers ? options.headers : undefined,
      method: (options && options.method) || 'GET',
      signal: options && options.signal,
    });
    if (!response.ok) {
      const error = new Error('unavailable');
      error.status = response.status;
      error.code = 'unavailable';
      throw error;
    }
    const contentType = response.headers.get('Content-Type') || '';
    if (!contentType.includes('application/json')) {
      const error = new Error('unavailable');
      error.status = response.status;
      error.code = 'unavailable';
      throw error;
    }
    try {
      return await response.json();
    } catch (_) {
      const error = new Error('unavailable');
      error.code = 'unavailable';
      throw error;
    }
  },

  async checkHealth() {
    try {
      const data = await this.fetch(this.endpoints.health);
      return !!(data && data.status === 'ok');
    } catch (_) {
      return false;
    }
  },
};

if (typeof window !== 'undefined') {
  window.ThreeZoneConfig = ThreeZoneConfig;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = ThreeZoneConfig;
}
