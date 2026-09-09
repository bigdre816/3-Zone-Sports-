/**
 * Three-Zone Sports Frontend Configuration
 * 
 * Centralized configuration for all backend API communications.
 * Update BACKEND_URL to point to your deployed member app.
 */

const ThreeZoneConfig = {
  // Production deployment URL - update this when backend is deployed
  // Examples: https://app.3zonesports.com, https://three-zone-api.render.com
  BACKEND_URL: (() => {
    // Auto-detect in development
    if (typeof window !== 'undefined' && window.location.hostname === 'localhost') {
      return 'http://localhost:8000';
    }
    // Use environment variable if available (for CI/CD)
    if (typeof process !== 'undefined' && process.env.REACT_APP_BACKEND_URL) {
      return process.env.REACT_APP_BACKEND_URL;
    }
    // Default to empty string (same origin) - will prompt user if needed
    return '';
  })(),

  // API endpoints (relative to BACKEND_URL)
  endpoints: {
    health: '/api/health',
    config: '/api/config',
    
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
