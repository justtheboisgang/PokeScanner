import { Fragment, useEffect, useState } from "react";
import { api, formatEuro } from "../api.js";

const AMPEL = {
  green: "bg-emerald-500",
  amber: "bg-amber-500",
  red: "bg-rose-500",
};

const CHANNELS = [
  { value: "ebay", label: "eBay" },
  { value: "kleinanzeigen", label: "Kleinanzeigen" },
  { value: "ebay_browse", label: "eBay (Browse)" },
  { value: "willhaben", label: "willhaben" },
];

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function SaleForm({ row, onSaved, onCancel }) {
  const [price, setPrice] = useState("");
  const [date, setDate] = useState(todayISO());
  const [channel, setChannel] = useState("ebay");
  const [fees, setFees] = useState("0");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const canSubmit = price !== "" && date;
  const field =
    "rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm";

  // Roh-Marge zur Orientierung: Verkauf - Kauf - Versand - Gebühren.
  const margin =
    price === ""
      ? null
      : Number(price) -
        Number(row.purchase_price) -
        Number(row.shipping_cost || 0) -
        Number(fees || 0);

  const submit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true);
    setError(null);
    try {
      await api.createSale(row.purchase_id, {
        price: String(price),
        date,
        channel,
        fees: String(fees || "0"),
      });
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <tr className="border-t border-slate-800 bg-slate-900/60">
      <td colSpan={7} className="px-3 py-3">
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs text-slate-400">Verkaufspreis €</label>
            <input
              type="number"
              step="0.01"
              min="0"
              autoFocus
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              className={`${field} w-32`}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-400">Gebühren €</label>
            <input
              type="number"
              step="0.01"
              min="0"
              value={fees}
              onChange={(e) => setFees(e.target.value)}
              className={`${field} w-28`}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-400">Verkaufsdatum</label>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className={field}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-400">Kanal</label>
            <select
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
              className={field}
            >
              {CHANNELS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          {margin !== null && (
            <div className="text-sm">
              <div className="mb-1 text-xs text-slate-400">Roh-Marge</div>
              <span
                className={
                  margin >= 0 ? "font-semibold text-emerald-300" : "font-semibold text-rose-300"
                }
              >
                {formatEuro(margin)}
              </span>
            </div>
          )}
          <button
            type="submit"
            disabled={!canSubmit || saving}
            className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {saving ? "speichert…" : "Verkauf speichern"}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg px-3 py-2 text-sm text-slate-400 hover:text-slate-200"
          >
            abbrechen
          </button>
          {error && <p className="w-full text-sm text-rose-400">{error}</p>}
        </form>
      </td>
    </tr>
  );
}

export default function Inventory() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selling, setSelling] = useState(null);

  const load = () =>
    api
      .listInventory()
      .then(setRows)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));

  useEffect(() => {
    load();
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
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <Fragment key={r.purchase_id}>
                  <tr className="border-t border-slate-800">
                    <td className="px-3 py-2">
                      <span
                        className={`inline-block h-3 w-3 rounded-full ${AMPEL[r.exit_status]}`}
                        title={r.exit_status}
                      />
                    </td>
                    <td className="px-3 py-2">{r.title}</td>
                    <td className="px-3 py-2 text-slate-300">
                      {formatEuro(r.purchase_price)}
                    </td>
                    <td className="px-3 py-2 text-slate-500">{r.purchase_date}</td>
                    <td className="px-3 py-2 font-medium">{r.days_in_stock}</td>
                    <td className="px-3 py-2 text-slate-400">{r.exit_hint}</td>
                    <td className="px-3 py-2 text-right">
                      <button
                        onClick={() =>
                          setSelling(selling === r.purchase_id ? null : r.purchase_id)
                        }
                        className="rounded-lg bg-slate-800 px-2.5 py-1.5 text-xs font-medium text-slate-200 ring-1 ring-slate-700 transition hover:bg-slate-700"
                      >
                        {selling === r.purchase_id ? "schließen" : "Verkauft"}
                      </button>
                    </td>
                  </tr>
                  {selling === r.purchase_id && (
                    <SaleForm
                      row={r}
                      onSaved={() => {
                        setSelling(null);
                        load();
                      }}
                      onCancel={() => setSelling(null)}
                    />
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
