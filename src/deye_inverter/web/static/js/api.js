// Thin wrapper around fetch for the JSON API. A 401 sends the browser to the login page.

export class ApiError extends Error {}

async function request(method, path, body) {
  const options = { method, headers: { Accept: "application/json" } };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  if (response.status === 401) {
    window.location.href = "/login";
    throw new ApiError("Login required");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(data.detail || data.error || `HTTP ${response.status}`);
  }
  return data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body = {}) => request("POST", path, body),
  delete: (path) => request("DELETE", path),
};
