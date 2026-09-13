import { useEffect, useState } from "react";
import { api, formatEuro } from "../api.js";

const AMPEL = {
  green: "bg-emerald-500",
  amber: "bg-amber-500",
  red: "bg-rose-500",
};

export default function Inventory() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .listInventory()
      .then(setRows)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">Inventar</h1>
      {error && <p className="text-rose-400">Fehler: {error}</p>}
      {loading ? (
        <p className="text-slate-400">lädt…</p>
      ) : rows.length === 0 ? (
        <p className="text-slate-400">Keine offenen Positionen.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-800/60 text-xs uppercase text-slate-400">
              <tr>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Titel</th>
                <th className="px-3 py-2">Kaufpreis</th>
                <th className="px-3 py-2">Gekauft</th>
                <th className="px-3 py-2">Tage im Bestand</th>
                <th className="px-3 py-2">Exit-Regel</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.purchase_id} className="border-t border-slate-800">
                  <td className="px-3 py-2">
                    <span
                      className={`inline-block h-3 w-3 rounded-full ${AMPEL[r.exit_status]}`}
                      title={r.exit_status}
                    />
                  </td>
                  <td className="px-3 py-2">{r.title}</td>
                  <td className="px-3 py-2 text-slate-300">{formatEuro(r.purchase_price)}</td>
                  <td className="px-3 py-2 text-slate-500">{r.purchase_date}</td>
                  <td className="px-3 py-2 font-medium">{r.days_in_stock}</td>
                  <td className="px-3 py-2 text-slate-400">{r.exit_hint}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
