(function () {
  const $ = (id) => document.getElementById(id);
  let stream = null;
  let sessionId = null;
  let idem = "pc_" + Math.random().toString(36).slice(2);

  function setStatus(obj) {
    $("status").textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
  }

  async function api(method, path, body) {
    const headers = { "Content-Type": "application/json" };
    const token = $("token").value.trim();
    if (token) headers.Authorization = "Bearer " + token;
    const res = await fetch(path, {
      method: method,
      headers: headers,
      credentials: "same-origin",
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (e) { data = { raw: text }; }
    if (!res.ok) {
      const err = new Error((data && (data.error || data.code)) || res.statusText);
      err.status = res.status;
      err.payload = data;
      throw err;
    }
    return data;
  }

  $("cam-btn").addEventListener("click", async function () {
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      $("preview").srcObject = stream;
      $("start-btn").disabled = false;
      setStatus("Local camera preview active. Not uploaded. Not published.");
    } catch (e) {
      setStatus("Camera error: " + e.message);
    }
  });

  $("start-btn").addEventListener("click", async function () {
    try {
      const body = { idempotency_key: idem };
      const ev = $("event_id").value.trim();
      if (ev) body.event_id = ev;
      const data = await api("POST", "/api/live-sessions", body);
      sessionId = data.live_session.live_session_id;
      $("stop-btn").disabled = false;
      $("refresh-btn").disabled = false;
      setStatus(data.live_session);
    } catch (e) {
      setStatus({ error: e.message, status: e.status, payload: e.payload });
    }
  });

  $("stop-btn").addEventListener("click", async function () {
    if (!sessionId) return;
    try {
      const data = await api("POST", "/api/live-sessions/" + sessionId + "/stop", {
        reason: "operator_ui_stop",
      });
      setStatus(data.live_session);
    } catch (e) {
      setStatus({ error: e.message, status: e.status, payload: e.payload });
    }
  });

  $("refresh-btn").addEventListener("click", async function () {
    if (!sessionId) return;
    try {
      const data = await api("GET", "/api/live-sessions/" + sessionId);
      setStatus(data.live_session);
    } catch (e) {
      setStatus({ error: e.message, status: e.status, payload: e.payload });
    }
  });
})();
