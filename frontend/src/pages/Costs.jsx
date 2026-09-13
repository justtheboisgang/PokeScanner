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
      <h1 className="mb-4 text-xl font-semibold">Kosten</h1>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-500">Käufe (Buy)</div>
          <div className="mt-1 text-2xl font-semibold">{d.buy_count}</div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-500">Gesamtkosten (gesch.)</div>
          <div className="mt-1 text-2xl font-semibold">{formatEuro(d.total_cost_eur)}</div>
        </div>
        <div className="rounded-lg border border-indigo-700/50 bg-indigo-600/10 p-4">
          <div className="text-xs uppercase tracking-wide text-indigo-300">Kosten / Fund</div>
          <div className="mt-1 text-2xl font-semibold">
            {d.cost_per_fund_eur == null ? "—" : formatEuro(d.cost_per_fund_eur)}
          </div>
          <div className="mt-1 text-xs text-slate-500">Gesamtkosten ÷ Buy-Kandidaten</div>
        </div>
      </div>

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
        Heute pro Anbieter (Tagesbudget)
      </h2>
      <div className="overflow-x-auto rounded-lg border border-slate-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-800/60 text-xs uppercase text-slate-400">
            <tr>
              <th className="px-3 py-2">Anbieter</th>
              <th className="px-3 py-2">Heute ausgegeben</th>
              <th className="px-3 py-2">Tagesbudget</th>
              <th className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {d.providers.map((p) => {
              const budget = Number(p.budget_eur);
              const spent = Number(p.spent_today_eur);
              const pctOver = budget > 0 && spent >= budget;
              return (
                <tr key={p.provider} className="border-t border-slate-800">
                  <td className="px-3 py-2">{p.provider}</td>
                  <td className="px-3 py-2 font-medium">{formatEuro(p.spent_today_eur)}</td>
                  <td className="px-3 py-2 text-slate-400">
                    {budget > 0 ? formatEuro(p.budget_eur) : "aus (0 €)"}
                  </td>
                  <td className="px-3 py-2">
                    {p.disabled ? (
                      <span className="rounded bg-rose-600/20 px-2 py-0.5 text-xs text-rose-300 ring-1 ring-rose-600/40">
                        {budget > 0 ? "Budget erreicht" : "deaktiviert"}
                      </span>
                    ) : (
                      <span className="rounded bg-emerald-600/20 px-2 py-0.5 text-xs text-emerald-300 ring-1 ring-emerald-600/40">
                        aktiv
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Kosten sind Schätzungen aus konfigurierbaren Stückkosten. Bei Erreichen des
        Tagesbudgets wird der Anbieter für den Rest des Tages automatisch deaktiviert.
      </p>
    </div>
  );
}
