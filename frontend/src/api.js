// Thin API client for the FastAPI backend. Kept separate from components so the
// data layer is swappable and easy to mock in tests.

async function get(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json();
}

export const getHealth = () => get("/api/health");
export const getMeta = () => get("/api/meta");
export const getModels = () => get("/api/models");

export async function triageClaim(claim, { provider, model } = {}) {
  const res = await fetch("/api/triage", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ claim, provider, model }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `Triage failed: ${res.status}`);
  return data;
}
