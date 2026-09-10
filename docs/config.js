/**
 * Public site configuration. The production app origin is resolved automatically.
 * Do not surface this origin in page copy, forms, or status badges.
 */

const PRODUCTION_API_ORIGIN = 'https://three-zone-sports.onrender.com';

const ThreeZoneConfig = {
  PRODUCTION_API_ORIGIN,

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
    return this._origin();
  },

  async memberAppUrl(path) {
    const suffix = path == null || path === '' ? '/' : path;
    return this._origin() + suffix;
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
