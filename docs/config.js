/**
 * Three-Zone Sports frontend configuration.
 *
 * GitHub Pages serves the public marketing site while the member/backend app may
 * live on another origin, so this file resolves a working backend URL at runtime.
 */

const ThreeZoneConfig = {
  BACKEND_URL: (() => {
    if (typeof window !== 'undefined' && window.__THREE_ZONE_BACKEND_URL__) {
      return String(window.__THREE_ZONE_BACKEND_URL__).replace(/\/+$/, '');
    }
    if (typeof window !== 'undefined') {
      try {
        const saved = window.localStorage.getItem('threezone_backend_url');
        if (saved) return saved.replace(/\/+$/, '');
      } catch (_) {}
      if (window.location.hostname === 'localhost') {
        return 'http://localhost:8000';
      }
    }
    return '';
  })(),

  endpoints: {
    health: '/api/health',
    config: '/api/config',
    public: {
      live: '/api/public/live',
      schedules: '/api/public/schedules',
      archives: '/api/public/archives',
    },
    auth: {
      login: '/api/auth/login',
      register: '/api/auth/register',
      logout: '/api/auth/logout',
      me: '/api/me',
    },
    member: {
      me: '/api/member/me',
      live: '/api/member/live',
      schedules: '/api/member/schedules',
      archives: '/api/member/archives',
      search: '/api/member/search',
      playback: (eventId) => `/api/member/events/${eventId}/playback`,
    },
    events: {
      list: '/api/events',
      get: (eventId) => `/api/events/${eventId}`,
    },
  },

  _backendUrlPromise: null,

  _candidateBackendUrls() {
    const seen = new Set();
    const out = [];
    const add = value => {
      const item = String(value || '').replace(/\/+$/, '');
      if (!item || seen.has(item)) return;
      seen.add(item);
      out.push(item);
    };
    add(this.BACKEND_URL);
    if (typeof window !== 'undefined') {
      add(window.location.origin);
      const host = window.location.hostname.replace(/^www\./, '');
      if (host === '3zonesports.com') {
        add('https://app.3zonesports.com');
        add('https://api.3zonesports.com');
        add('https://three-zone-sports-api.onrender.com');
      }
    }
    return out;
  },

  async _probeBackend(baseUrl) {
    const url = `${baseUrl}${this.endpoints.health}`;
    const response = await fetch(url, { credentials: 'include' });
    if (!response.ok) return false;
    const data = await response.json().catch(() => ({}));
    return data && data.status === 'ok';
  },

  async resolveBackendUrl() {
    if (this._backendUrlPromise) return this._backendUrlPromise;
    this._backendUrlPromise = (async () => {
      for (const candidate of this._candidateBackendUrls()) {
        try {
          if (await this._probeBackend(candidate)) {
            this.BACKEND_URL = candidate;
            try { window.localStorage.setItem('threezone_backend_url', candidate); } catch (_) {}
            return candidate;
          }
        } catch (_) {}
      }
      this.BACKEND_URL = '';
      try { window.localStorage.removeItem('threezone_backend_url'); } catch (_) {}
      return '';
    })();
    try {
      return await this._backendUrlPromise;
    } finally {
      this._backendUrlPromise = null;
    }
  },

  async _requestJson(url, options = {}) {
    const headers = {
      ...(options.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers,
    };
    const response = await fetch(url, {
      ...options,
      headers,
      credentials: 'include',
    });
    const contentType = response.headers.get('Content-Type') || '';
    const text = await response.text();
    const data = contentType.includes('application/json')
      ? JSON.parse(text || '{}')
      : null;
    if (!response.ok) {
      const message = (data && data.error) || text || `HTTP ${response.status}`;
      throw { status: response.status, message, code: data && data.code };
    }
    if (!data) {
      throw { status: response.status, message: 'Invalid API response', code: 'bad_response' };
    }
    return data;
  },

  async fetch(endpoint, options = {}) {
    const baseUrl = await this.resolveBackendUrl();
    if (!baseUrl) {
      throw {
        status: 503,
        message: 'Member services are not yet configured.',
        code: 'backend_unconfigured',
      };
    }
    const url = `${baseUrl}${endpoint}`;
    try {
      const payload = {
        ...options,
        body: options.body !== undefined && typeof options.body !== 'string'
          ? JSON.stringify(options.body)
          : options.body,
      };
      return await this._requestJson(url, payload);
    } catch (error) {
      console.error(`API Error (${endpoint}):`, error);
      throw error;
    }
  },

  async memberAppUrl(path = '/') {
    const baseUrl = await this.resolveBackendUrl();
    return baseUrl ? `${baseUrl}${path}` : '';
  },

  async checkHealth() {
    try {
      const baseUrl = await this.resolveBackendUrl();
      if (!baseUrl) return false;
      const result = await this._requestJson(`${baseUrl}${this.endpoints.health}`);
      return result.status === 'ok';
    } catch {
      return false;
    }
  },

  async getPublicConfig() {
    try {
      return await this.fetch(this.endpoints.config);
    } catch {
      return null;
    }
  },
};

if (typeof window !== 'undefined') {
  window.ThreeZoneConfig = ThreeZoneConfig;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = ThreeZoneConfig;
}
