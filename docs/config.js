/**
 * Three-Zone Sports Frontend Configuration
 * 
 * Centralized configuration for all backend API communications.
 * Update BACKEND_URL to point to your deployed member app.
 */

function normalizeOrigin(value) {
  return typeof value === 'string' ? value.trim().replace(/\/+$/, '') : '';
}

function resolveBackendOrigin() {
  if (typeof window === 'undefined') return '';

  const runtimeOverride = normalizeOrigin(window.__THREE_ZONE_BACKEND_URL__);
  if (runtimeOverride) return runtimeOverride;

  const meta = document.querySelector('meta[name="three-zone-backend"]');
  const metaOverride = normalizeOrigin(meta && meta.content);
  if (metaOverride) return metaOverride;

  if (typeof process !== 'undefined' && process.env && process.env.REACT_APP_BACKEND_URL) {
    return normalizeOrigin(process.env.REACT_APP_BACKEND_URL);
  }

  const { hostname, protocol } = window.location;
  if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]') {
    return 'http://localhost:8000';
  }
  if (hostname === '3zonesports.com' || hostname === 'www.3zonesports.com') {
    return 'https://api.3zonesports.com';
  }
  return /^https?:$/.test(protocol) ? normalizeOrigin(window.location.origin) : '';
}

const ThreeZoneConfig = {
  // The static site resolves the API at runtime so a backend redeploy does not
  // require editing every page.
  BACKEND_URL: resolveBackendOrigin(),

  // API endpoints (relative to BACKEND_URL)
  endpoints: {
    health: '/api/health',
    config: '/api/config',
    public: {
      live: '/api/public/live',
      schedules: '/api/public/schedules',
      archives: '/api/public/archives',
    },
    
    // Authentication
    auth: {
      login: '/api/auth/login',
      register: '/api/auth/register',
      logout: '/api/auth/logout',
      me: '/api/me',
    },
    
    // Member features
    member: {
      me: '/api/member/me',
      live: '/api/member/live',
      schedules: '/api/member/schedules',
      archives: '/api/member/archives',
      search: '/api/member/search',
      playback: (eventId) => `/api/member/events/${eventId}/playback`,
    },
    
    // Events
    events: {
      list: '/api/events',
      get: (eventId) => `/api/events/${eventId}`,
    },
  },

  /**
   * Fetch wrapper that handles API calls with proper headers and error handling
   */
  async fetch(endpoint, options = {}) {
    const url = this.BACKEND_URL ? `${this.BACKEND_URL}${endpoint}` : endpoint;
    
    const headers = {
      'Content-Type': 'application/json',
      ...options.headers,
    };

    try {
      const response = await fetch(url, {
        ...options,
        headers,
        credentials: 'include', // Include cookies for session
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({ error: 'Unknown error' }));
        throw {
          status: response.status,
          message: error.error || `HTTP ${response.status}`,
          code: error.code,
        };
      }

      return await response.json();
    } catch (error) {
      console.error(`API Error (${endpoint}):`, error);
      throw error;
    }
  },

  /**
   * Check if backend is available
   */
  async checkHealth() {
    try {
      const result = await this.fetch(this.endpoints.health);
      return result.status === 'ok';
    } catch {
      return false;
    }
  },

  /**
   * Get public config from backend
   */
  async getPublicConfig() {
    try {
      return await this.fetch(this.endpoints.config);
    } catch {
      return null;
    }
  },
};

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = ThreeZoneConfig;
}
