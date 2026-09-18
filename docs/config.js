/**
 * Public site configuration. Fetch the Render API; send members to the
 * GitHub→Render member shell. Lovable is preview/sandbox only and is never
 * the production member destination. Do not surface infrastructure origins
 * in page copy, forms, or status badges.
 */

const PRODUCTION_API_ORIGIN = 'https://three-zone-sports-1.onrender.com';
const MEMBER_APP_ORIGIN = PRODUCTION_API_ORIGIN;

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

  _isLovableHost(host) {
    const name = String(host || '').toLowerCase().replace(/\.+$/, '');
    return name === 'lovable.app' || name.endsWith('.lovable.app');
  },

  memberOrigin() {
    if (typeof window !== 'undefined') {
      const loc = window.location || {};
      const host = String(loc.hostname || '');
      if (host === 'localhost' || host === '127.0.0.1') {
        return this._origin();
      }
      // Already on this Render service — stay same-origin. Never bounce to
      // a Lovable preview host.
      if (host.endsWith('.onrender.com') && !this._isLovableHost(host)) {
        if (loc.origin) {
          return String(loc.origin).replace(/\/+$/, '');
        }
        return 'https://' + host;
      }
    }
    const dest = MEMBER_APP_ORIGIN;
    if (this._isLovableHost(dest.replace(/^https?:\/\//, '').split('/')[0])) {
      return PRODUCTION_API_ORIGIN;
    }
    return dest;
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
