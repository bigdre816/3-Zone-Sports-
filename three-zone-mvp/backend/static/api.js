"use strict";

async function api(method, path, body) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method, credentials: "include", headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const err = Error(data.error || "Request failed");
    err.code = data.code;
    throw err;
  }
  return data;
}
