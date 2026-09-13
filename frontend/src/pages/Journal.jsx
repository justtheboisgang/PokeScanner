import { useEffect, useState } from "react";
import { api, formatEuro } from "../api.js";

function Money({ value, signed = false }) {
  if (value === null || value === undefined)
    return <span className="text-slate-500">—</span>;
  const num = Number(value);
  const cls = num >= 0 ? "text-emerald-400" : "text-rose-400";
  const prefix = signed && num >= 0 ? "+" : "";
  return <span className={cls}>{prefix}{formatEuro(value)}</span>;
}

export default function Journal() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .listJournal()
      .then(setRows)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">Journal</h1>
      {error && <p className="text-rose-400">Fehler: {error}</p>}
      {loading ? (
        <p className="text-slate-400">lädt…</p>
      ) : rows.length === 0 ? (
        <p className="text-slate-400">Noch keine abgeschlossenen Deals.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-800/60 text-xs uppercase text-slate-400">
              <tr>
                <th className="px-3 py-2">Verkäufer</th>
                <th className="px-3 py-2">Kauf</th>
                <th className="px-3 py-2">Verkauf</th>
                <th className="px-3 py-2">Tage</th>
                <th className="px-3 py-2">Ergebnis</th>
                <th className="px-3 py-2">Prognose</th>
                <th className="px-3 py-2">Fehler</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.purchase_id} className="border-t border-slate-800">
                  <td className="px-3 py-2">{r.seller_name}</td>
                  <td className="px-3 py-2 text-slate-400">
                    {formatEuro(r.purchase_price)}
                    <span className="text-slate-600"> · {r.purchase_date}</span>
                  </td>
                  <td className="px-3 py-2 text-slate-400">
                    {formatEuro(r.sale_price)}
                    <span className="text-slate-600"> · {r.sale_date}</span>
                  </td>
                  <td className="px-3 py-2 text-slate-400">{r.days_to_sell ?? "—"}</td>
                  <td className="px-3 py-2 font-medium">
                    <Money value={r.actual_profit} signed />
                  </td>
                  <td className="px-3 py-2">
                    {r.forecast_profit != null ? (
                      <Money value={r.forecast_profit} signed />
                    ) : (
                      <span className="text-slate-500">unbewertbar</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <Money value={r.forecast_error} signed />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
