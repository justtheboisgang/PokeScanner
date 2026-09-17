import { useEffect, useState } from "react";
import { api } from "../api.js";

function Stat({ label, value, sub }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

function pct(v) {
  return v == null ? "—" : `${(v * 100).toFixed(0)} %`;
}

function num(v, digits = 1) {
  return v == null ? "—" : Number(v).toFixed(digits);
}

export default function Calibration() {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getCalibration().then(setD).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="text-rose-400">Fehler: {error}</p>;
  if (!d) return <p className="text-slate-400">lädt…</p>;

  const mins = d.avg_seconds_to_decision != null ? (d.avg_seconds_to_decision / 60).toFixed(1) : null;

  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">Kalibrierung</h1>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <Stat label="Kandidaten" value={d.total_candidates} />
        <Stat label="Entschieden" value={d.decided_count} sub={`Quote ${pct(d.decision_rate)}`} />
        <Stat label="Unbewertbar" value={pct(d.unbewertbar_rate)} />
        <Stat
          label="Ø Zeit bis Urteil"
          value={mins == null ? "—" : `${mins} min`}
        />
        <Stat label="Abgeschl. Deals" value={d.closed_deals} />
        <Stat
          label="Ø Prognosefehler"
          value={d.avg_forecast_error_eur == null ? "—" : `${num(d.avg_forecast_error_eur, 2)} €`}
          sub={d.avg_abs_forecast_error_eur == null ? undefined : `|Ø| ${num(d.avg_abs_forecast_error_eur, 2)} €`}
        />
      </div>

      {d.market_comparison && (
        <section className="mt-4 rounded-lg border border-slate-800 bg-slate-900 p-4">
          <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-400">
            Echte Verkäufe vs. Marktpreis
          </h2>
          <p className="mb-3 text-xs text-slate-500">
            Was wirklich gezahlt wurde, geteilt durch das, was Cardmarket verlangt.
            Unter 100 % heißt: der Marktpreis ist zu hoch — ein „Schnäppchen"
            gegenüber dem Trendpreis ist dann keines.
          </p>
          {d.market_comparison.sample_size === 0 ? (
            <p className="text-sm text-slate-500">{d.market_comparison.verdict}</p>
          ) : (
            <>
              <div className="mb-3 flex flex-wrap items-baseline gap-x-6 gap-y-2">
                <div>
                  <div className="text-xs text-slate-500">Verhältnis (Median)</div>
                  <div
                    className={`text-2xl font-semibold ${
                      d.market_comparison.median_ratio < 0.95
                        ? "text-amber-300"
                        : "text-emerald-300"
                    }`}
                  >
                    {(d.market_comparison.median_ratio * 100).toFixed(0)} %
                  </div>
                </div>
                <div>
                  <div className="text-xs text-slate-500">Ø verkauft</div>
                  <div className="text-lg">
                    {num(d.market_comparison.median_sold_eur, 2)} €
                  </div>
                </div>
                <div>
                  <div className="text-xs text-slate-500">Ø Marktpreis</div>
                  <div className="text-lg text-slate-400">
                    {num(d.market_comparison.median_market_eur, 2)} €
                  </div>
                </div>
                <div>
                  <div className="text-xs text-slate-500">Stichprobe</div>
                  <div className="text-lg">{d.market_comparison.sample_size}</div>
                </div>
              </div>
              <p className="text-sm text-slate-300">{d.market_comparison.verdict}</p>
            </>
          )}
        </section>
      )}

      <section className="mt-4 rounded-lg border border-slate-800 bg-slate-900 p-4">
        <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-400">
          Prognosefehler je Kaskadenstufe
        </h2>
        <p className="mb-3 text-xs text-slate-500">
          Zeigt, welche Stufe trägt. Negativ = Prognose war zu optimistisch.
        </p>
        {(d.per_cascade_level || []).length === 0 ? (
          <p className="text-sm text-slate-500">
            Noch keine abgeschlossenen Deals mit Referenzwert.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-800/60 text-xs uppercase text-slate-400">
                <tr>
                  <th className="px-3 py-2">Stufe</th>
                  <th className="px-3 py-2">Deals</th>
                  <th className="px-3 py-2">Ø Fehler</th>
                  <th className="px-3 py-2">Ø |Fehler|</th>
                </tr>
              </thead>
              <tbody>
                {d.per_cascade_level.map((r) => (
                  <tr key={r.cascade_level} className="border-t border-slate-800">
                    <td className="px-3 py-2 font-medium">Stufe {r.cascade_level}</td>
                    <td className="px-3 py-2 text-slate-300">{r.closed_deals}</td>
                    <td
                      className={`px-3 py-2 font-medium ${
                        r.avg_forecast_error_eur == null
                          ? "text-slate-500"
                          : r.avg_forecast_error_eur >= 0
                            ? "text-emerald-300"
                            : "text-rose-300"
                      }`}
                    >
                      {r.avg_forecast_error_eur == null
                        ? "—"
                        : `${num(r.avg_forecast_error_eur, 2)} €`}
                    </td>
                    <td className="px-3 py-2 text-slate-300">
                      {r.avg_abs_forecast_error_eur == null
                        ? "—"
                        : `${num(r.avg_abs_forecast_error_eur, 2)} €`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
            Alarme pro Kanal
          </h2>
          {Object.keys(d.alerts_per_channel).length === 0 ? (
            <p className="text-sm text-slate-500">—</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {Object.entries(d.alerts_per_channel).map(([k, v]) => (
                <li key={k} className="flex justify-between">
                  <span className="text-slate-300">{k}</span>
                  <span className="font-medium">{v}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
            Urteile
          </h2>
          {Object.keys(d.decisions).length === 0 ? (
            <p className="text-sm text-slate-500">noch keine</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {Object.entries(d.decisions).map(([k, v]) => (
                <li key={k} className="flex justify-between">
                  <span className="text-slate-300">{k}</span>
                  <span className="font-medium">{v}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
