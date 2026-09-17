import { useEffect, useState } from "react";
import { api } from "../api.js";

function fmtDuration(s) {
  if (s == null) return "—";
  if (s < 90) return `${Math.round(s)} s`;
  if (s < 5400) return `${(s / 60).toFixed(0)} min`;
  if (s < 172800) return `${(s / 3600).toFixed(1)} h`;
  return `${(s / 86400).toFixed(1)} d`;
}

export default function Diagnostics() {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getDiagnostics().then(setD).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="text-rose-400">Fehler: {error}</p>;
  if (!d) return <p className="text-slate-400">lädt…</p>;

  const reasons = d.unbewertbar_reasons || [];
  const resolvePct =
    d.resolver_attempted > 0
      ? ((d.resolver_resolved / d.resolver_attempted) * 100).toFixed(0)
      : "0";

  return (
    <div>
      <h1 className="mb-1 text-xl font-semibold">Diagnose</h1>
      <p className="mb-5 text-sm text-slate-500">
        Warum ist alles „unbewertbar"? Welche Begriffe bringen Funde? Wie schnell alarmiert das System?
      </p>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-500">Kandidaten</div>
          <div className="mt-1 text-2xl font-semibold">{d.total_candidates}</div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-500">Ø Time-to-Alert (Median)</div>
          <div className="mt-1 text-2xl font-semibold">{fmtDuration(d.time_to_alert_median_seconds)}</div>
          <div className="mt-1 text-xs text-slate-500">90%: {fmtDuration(d.time_to_alert_p90_seconds)} · n={d.time_to_alert_count}</div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-500">Resolver aufgelöst</div>
          <div className="mt-1 text-2xl font-semibold">{resolvePct}%</div>
          <div className="mt-1 text-xs text-slate-500">
            {d.resolver_resolved} / {d.resolver_attempted}
          </div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <div className="text-xs uppercase tracking-wide text-slate-500">Nie bewertet</div>
          <div className="mt-1 text-2xl font-semibold">{d.never_attempted}</div>
          <div className="mt-1 text-xs text-slate-500">
            {d.per_term.length} Suchbegriffe aktiv
          </div>
        </div>
      </div>

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
        Warum blieb es unbewertbar?
      </h2>
      <div className="mb-3 overflow-x-auto rounded-lg border border-slate-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-800/60 text-xs uppercase text-slate-400">
            <tr>
              <th className="px-3 py-2">Grund</th>
              <th className="px-3 py-2">Kandidaten</th>
            </tr>
          </thead>
          <tbody className="tnum">
            {reasons.length === 0 ? (
              <tr>
                <td className="px-3 py-3 text-slate-500" colSpan={2}>
                  Noch kein Bewertungsversuch ausgewertet.
                </td>
              </tr>
            ) : (
              reasons.map((r) => (
                <tr key={r.label} className="border-t border-slate-800">
                  <td className="px-3 py-2 text-slate-300">{r.label}</td>
                  <td className="px-3 py-2 font-medium">{r.count}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <p className="mb-6 text-xs text-slate-500">
        Diese Tabelle zählt nur <span className="text-slate-400">geprüfte</span>{" "}
        Kandidaten. Die {d.never_attempted} „nie bewertet"
        sind kein Misserfolg: die Automatik läuft bei neuen Listings, älteres
        zieht <code>revalue</code> nach.
      </p>

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
        Pro Suchbegriff — Funde &amp; Verdict-Verteilung
      </h2>
      <div className="overflow-x-auto rounded-lg border border-slate-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-800/60 text-xs uppercase text-slate-400">
            <tr>
              <th className="px-3 py-2">Suchbegriff</th>
              <th className="px-3 py-2">Funde</th>
              <th className="px-3 py-2">Anteil</th>
              <th className="px-3 py-2 text-emerald-400">Buy</th>
              <th className="px-3 py-2 text-rose-400">Skip</th>
              <th className="px-3 py-2 text-amber-400">Unclear</th>
              <th className="px-3 py-2 text-slate-500">offen</th>
            </tr>
          </thead>
          <tbody className="tnum">
            {d.per_term.length === 0 ? (
              <tr><td className="px-3 py-3 text-slate-500" colSpan={7}>noch keine Daten</td></tr>
            ) : (
              d.per_term.map((t) => (
                <tr key={t.term} className="border-t border-slate-800">
                  <td className="px-3 py-2">{t.term}</td>
                  <td className="px-3 py-2 font-medium">{t.candidates}</td>
                  <td className="px-3 py-2 text-slate-400">{(t.share * 100).toFixed(0)}%</td>
                  <td className="px-3 py-2">{t.buy}</td>
                  <td className="px-3 py-2">{t.skip}</td>
                  <td className="px-3 py-2">{t.unclear}</td>
                  <td className="px-3 py-2 text-slate-500">{t.undecided}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Begriffe mit vielen Funden aber ohne „Buy" verbrennen nur Geld — nach ~2 Wochen hier ablesbar.
        Der Resolver-Wert bleibt niedrig, solange Karten nicht (manuell) aufgelöst werden — das kommt in Block 2.
      </p>
    </div>
  );
}
