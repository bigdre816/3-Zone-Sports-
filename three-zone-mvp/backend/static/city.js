(() => {
  'use strict';

  const byId = (id) => document.getElementById(id);
  let origin = null;
  let destination = null;

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    let payload = {};
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) {
      const error = new Error(payload.error || `Request failed (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function showError(message) {
    const box = byId('city-error');
    box.textContent = message;
    box.classList.remove('hidden');
  }

  function clearError() {
    byId('city-error').classList.add('hidden');
  }

  function directionsUrl(place) {
    const value = place.address || `${place.latitude},${place.longitude}`;
    return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(value)}`;
  }

  function eventDate(event) {
    if (!event || event.starts_at == null) return null;
    const value = typeof event.starts_at === 'number'
      ? new Date(event.starts_at * 1000)
      : new Date(event.starts_at);
    return Number.isNaN(value.getTime()) ? null : value;
  }

  function formatEventTime(event) {
    const value = eventDate(event);
    if (!value) return 'Time not exact';
    try {
      return new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
        timeZone: event.timezone || undefined,
      }).format(value);
    } catch (_) {
      return value.toLocaleString();
    }
  }

  function formatTime(iso, zone) {
    if (!iso) return '—';
    const value = new Date(iso);
    try {
      return new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
        timeZone: zone || undefined,
      }).format(value);
    } catch (_) {
      return value.toLocaleString();
    }
  }

  function renderDestination(place, event) {
    destination = place;
    const summary = byId('destination-summary');
    summary.replaceChildren();
    const name = document.createElement('strong');
    name.textContent = place.name;
    summary.appendChild(name);
    for (const line of [place.address, place.neighborhood || '', event ? `${event.title} · ${formatEventTime(event)}` : '']) {
      if (!line) continue;
      summary.appendChild(document.createElement('br'));
      const span = document.createElement('span');
      span.textContent = line;
      summary.appendChild(span);
    }
    byId('directions-fallback').href = directionsUrl(place);
  }

  async function loadDestination() {
    clearError();
    const eventId = byId('city-event-id').value.trim();
    const placeId = byId('city-place-id').value.trim();
    try {
      if (eventId) {
        const data = await api(`/api/member/city/events/${encodeURIComponent(eventId)}`);
        renderDestination(data.place, data.event);
        byId('city-place-id').value = data.place.city_place_id;
        return true;
      }
      if (placeId) {
        const data = await api(`/api/member/city/places/${encodeURIComponent(placeId)}`);
        renderDestination(data.place, null);
        return true;
      }
      showError('Enter a city event ID or city place ID.');
      return false;
    } catch (error) {
      showError(error.status === 401 ? 'Sign in to THREEZONE before planning a route.' : error.message);
      return false;
    }
  }

  function useMyLocation() {
    clearError();
    const status = byId('origin-status');
    if (!navigator.geolocation) {
      status.textContent = 'Precise location is unavailable in this browser. Enter a starting address instead.';
      return;
    }
    status.textContent = 'Requesting one-time precise location…';
    navigator.geolocation.getCurrentPosition(
      (position) => {
        origin = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        };
        byId('manual-origin').value = '';
        status.textContent = 'One-time precise location ready for this calculation. It is not saved by this screen.';
      },
      (error) => {
        origin = null;
        status.textContent = error.code === 1
          ? 'Location permission denied. Enter a starting address instead.'
          : 'Could not get your current location. Enter a starting address instead.';
      },
      { enableHighAccuracy: true, maximumAge: 30000, timeout: 10000 },
    );
  }

  function selectedOrigin() {
    const manual = byId('manual-origin').value.trim();
    if (manual) return { address: manual };
    return origin;
  }

  function metersToMiles(meters) {
    const value = Number(meters);
    return Number.isFinite(value) ? `${(value / 1609.344).toFixed(1)} mi` : '—';
  }

  function updateFreshness(iso) {
    const label = byId('route-freshness');
    if (!iso) {
      label.textContent = 'No successful estimate';
      return;
    }
    const ageMs = Math.max(0, Date.now() - new Date(iso).getTime());
    const minutes = Math.floor(ageMs / 60000);
    label.textContent = minutes < 1 ? 'Updated just now' : `Updated ${minutes}m ago${minutes >= 5 ? ' · stale' : ''}`;
  }

  function renderRoute(result) {
    const zone = result.event?.timezone;
    byId('route-card').classList.remove('hidden');
    byId('suggested-departure').textContent = result.leave_now
      ? 'LEAVE NOW'
      : formatTime(result.suggested_departure_at, zone);
    byId('route-explanation').textContent = result.explanation || '';
    byId('route-drive').textContent = `${result.route.duration_minutes} min`;
    byId('route-distance').textContent = metersToMiles(result.route.distance_meters);
    byId('route-arrival').textContent = formatTime(result.estimated_arrival_at, zone);
    byId('route-status').textContent = result.leave_now && result.estimated_late_seconds > 0
      ? 'Preferred departure passed'
      : 'Traffic-aware estimate ready';
    byId('directions-fallback').href = result.directions_fallback_url;
    updateFreshness(result.route.last_successful_estimate_at);
  }

  async function calculateRoute() {
    clearError();
    if (!destination && !(await loadDestination())) return;
    const originValue = selectedOrigin();
    if (!originValue) {
      showError('Choose Use my location or enter a starting address.');
      return;
    }
    const eventId = byId('city-event-id').value.trim();
    const body = {
      city_event_id: eventId || undefined,
      city_place_id: eventId ? undefined : destination.city_place_id,
      origin: originValue,
      early_arrival_minutes: Number(byId('early-minutes').value || 0),
      parking_walking_minutes: Number(byId('parking-minutes').value || 0),
    };
    if (!eventId) {
      const arrival = byId('arrival-target').value;
      if (arrival) body.desired_arrival_at = new Date(arrival).toISOString();
    }
    const button = byId('calculate-route');
    try {
      button.disabled = true;
      button.textContent = 'Calculating…';
      renderRoute(await api('/api/member/city/getting-there', {
        method: 'POST',
        body: JSON.stringify(body),
      }));
    } catch (error) {
      byId('route-card').classList.remove('hidden');
      byId('route-status').textContent = 'Route estimate unavailable';
      byId('route-freshness').textContent = 'No new estimate';
      byId('directions-fallback').href = directionsUrl(destination);
      showError(`${error.message} You can still open external directions.`);
    } finally {
      button.disabled = false;
      button.textContent = 'Calculate Getting There';
    }
  }

  byId('load-destination').addEventListener('click', loadDestination);
  byId('use-location').addEventListener('click', useMyLocation);
  byId('manual-origin').addEventListener('input', () => {
    if (byId('manual-origin').value.trim()) {
      origin = null;
      byId('origin-status').textContent = 'Manual starting address selected.';
    }
  });
  byId('calculate-route').addEventListener('click', calculateRoute);
})();
