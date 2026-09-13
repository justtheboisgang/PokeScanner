import { useEffect, useState } from "react";
import { api, formatEuro } from "../api.js";

export default function Costs() {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getCosts().then(setD).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="text-rose-400">Fehler: {error}</p>;
  if (!d) return <p className="text-slate-400">lädt…</p>;

  return (
    <div>
      <h1 className="mb-1 text-xl font-semibold">Kosten</h1>
      {!d.costs_configured && (
        <p className="mb-4 text-sm text-amber-400">
          Keine Stück-Kosten konfiguriert (COST_*): es wird nur der API-Verbrauch
          angezeigt, keine geschätzten Euro-Beträge.
        </p>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-500">Funde</div>
          <div className="mt-1 text-2xl font-semibold">{d.funds}</div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-500">Gesch. Gesamtkosten</div>
          <div className="mt-1 text-2xl font-semibold">
            {d.costs_configured ? formatEuro(d.total_est_cost_eur) : "—"}
          </div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-500">Kosten / Fund</div>
          <div className="mt-1 text-2xl font-semibold">
            {d.cost_per_fund_eur == null ? "—" : formatEuro(d.cost_per_fund_eur)}
          </div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-800/60 text-xs uppercase text-slate-400">
            <tr>
              <th className="px-3 py-2">Quelle</th>
              <th className="px-3 py-2">Calls</th>
              <th className="px-3 py-2">Stückkosten</th>
              <th className="px-3 py-2">Gesch. Kosten</th>
            </tr>
          </thead>
          <tbody>
            {d.usage.length === 0 ? (
              <tr>
                <td className="px-3 py-3 text-slate-500" colSpan={4}>
                  noch kein Verbrauch erfasst
                </td>
              </tr>
            ) : (
              d.usage.map((u) => (
                <tr key={u.source} className="border-t border-slate-800">
                  <td className="px-3 py-2">{u.source}</td>
                  <td className="px-3 py-2 font-medium">{u.calls}</td>
                  <td className="px-3 py-2 text-slate-400">
                    {Number(u.unit_cost_eur) > 0 ? formatEuro(u.unit_cost_eur) : "—"}
                  </td>
                  <td className="px-3 py-2 text-slate-300">
                    {Number(u.unit_cost_eur) > 0 ? formatEuro(u.est_cost_eur) : "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
