// Thin API client. Uses relative /api (proxied to FastAPI in dev).

async function request(path, options) {
  const resp = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }
  return resp.json();
}

export const api = {
  listCandidates: ({ undecidedOnly = false } = {}) =>
    request(`/candidates?undecided_only=${undecidedOnly}`),
  getCandidate: (id) => request(`/candidates/${id}`),
  putDecision: (id, body) =>
    request(`/candidates/${id}/decision`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  listJournal: () => request(`/journal`),
  listInventory: () => request(`/inventory`),
  getCalibration: () => request(`/calibration`),
  getCosts: () => request(`/costs`),
  getDiagnostics: () => request(`/diagnostics`),
};

export function formatEuro(value, currency = "EUR") {
  if (value === null || value === undefined) return "Preis unbekannt";
  const num = Number(value);
  if (num === 0) return "Zu verschenken (0 €)";
  return `${num.toLocaleString("de-DE", { minimumFractionDigits: 2 })} ${currency}`;
}

export function formatDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString("de-DE");
}
