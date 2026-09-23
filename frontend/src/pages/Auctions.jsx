import { useEffect, useState } from "react";
import { api, formatEuro } from "../api.js";

/** Countdown aus Sekunden. Kurz vor Schluss zaehlt jede Minute. */
function countdown(seconds) {
  if (seconds < 0) return "beendet";
  if (seconds < 60) return `${seconds} s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

function Urgency({ seconds }) {
  if (seconds < 0)
    return <span className="text-slate-500">beendet</span>;
  // Unter zehn Minuten wird es ernst — dann faellt die Entscheidung.
  const tone =
    seconds < 600
      ? "bg-rose-600/20 text-rose-300 ring-rose-600/40"
      : seconds < 1800
        ? "bg-amber-600/20 text-amber-300 ring-amber-600/40"
        : "bg-slate-700/60 text-slate-300 ring-slate-600/40";
  return (
    <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ${tone}`}>
      endet in {countdown(seconds)}
    </span>
  );
}

function Row({ item }) {
  const watched = item.reference_value_eur != null;
  return (
    <div
      className={`rounded-xl border p-3 transition ${
        item.would_alert
          ? "border-emerald-700/50 bg-emerald-950/20"
          : "border-slate-800 bg-slate-900"
      }`}
    >
      <div className="flex items-start gap-3">
        {item.image ? (
          <img
            src={item.image}
            alt=""
            loading="lazy"
            className="h-16 w-16 shrink-0 rounded object-cover"
          />
        ) : (
          <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded bg-slate-800 text-[10px] text-slate-600">
            kein Bild
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Urgency seconds={item.seconds_left} />
            {item.alerted_at && (
              <span className="rounded bg-indigo-600/20 px-1.5 py-0.5 text-[11px] text-indigo-300">
                gemeldet
              </span>
            )}
          </div>
          <a
            href={item.url || "#"}
            target="_blank"
            rel="noreferrer"
            className="mt-1 block truncate text-sm font-medium hover:text-indigo-300 hover:underline"
          >
            {item.title}
          </a>
          <div className="mt-1 flex flex-wrap items-center gap-3 text-sm">
            <span className="font-semibold text-slate-100">
              {formatEuro(item.current_price, item.currency)}
            </span>
            {watched ? (
              <>
                <span className="text-slate-500">
                  Marktpreis {formatEuro(item.reference_value_eur)}
                </span>
                <span
                  className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${
                    item.would_alert
                      ? "bg-emerald-600/20 text-emerald-300"
                      : "bg-slate-700/60 text-slate-300"
                  }`}
                >
                  {item.discount_pct >= 0 ? "−" : "+"}
                  {Math.abs(item.discount_pct).toFixed(0)}%
                </span>
              </>
            ) : (
              <span className="text-xs text-slate-500">
                wird nicht überwacht — {item.skip_reason || "kein Grund vermerkt"}
              </span>
            )}
          </div>
          {watched && (
            <div className="mt-1 truncate text-xs text-slate-500">
              {item.card_name} {item.card_number} · {item.matched_search_term || "—"}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Auctions() {
  const [items, setItems] = useState([]);
  const [includePast, setIncludePast] = useState(false);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .listAuctions({ includePast })
        .then((rows) => alive && setItems(rows))
        .catch((e) => alive && setError(e.message))
        .finally(() => alive && setLoading(false));
    load();
    // Diese Seite ist zeitkritisch: ein Countdown, der nicht laeuft, ist
    // schlimmer als keiner. Alle 30 Sekunden neu laden.
    const timer = setInterval(load, 30000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [includePast]);

  const soon = items.filter((i) => i.seconds_left >= 0 && i.would_alert).length;

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Auktionen</h1>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={includePast}
            onChange={(e) => setIncludePast(e.target.checked)}
            className="h-4 w-4 rounded border-slate-600 bg-slate-800"
          />
          beendete zeigen
        </label>
      </div>
      <p className="mb-5 text-sm text-slate-500">
        Läuft gerade und endet bald. Die Discord-Meldung kommt erst kurz vor
        Schluss — hier siehst du vorher, was sich anbahnt.
        {soon > 0 && (
          <span className="ml-1 text-emerald-400">
            {soon} davon aktuell weit genug unter Marktpreis.
          </span>
        )}
      </p>

      {error && <p className="text-rose-400">Fehler: {error}</p>}
      {loading ? (
        <p className="text-slate-400">lädt…</p>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-slate-800 bg-slate-900 p-4 text-sm text-slate-400">
          <p>Gerade keine Auktionen im Fenster.</p>
          <p className="mt-1 text-xs text-slate-500">
            Die Wache sucht alle paar Minuten nach Auktionen, die innerhalb der
            nächsten Dreiviertelstunde enden. Steht hier dauerhaft nichts,
            prüfe <code>python -m app.checkconfig</code>.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <Row key={item.id} item={item} />
          ))}
        </div>
      )}

      <p className="mt-4 text-xs text-slate-500">
        Der Vergleich läuft gegen <strong>Marktpreise</strong> — das ist, was
        verlangt wird, nicht was erzielt wurde. Gebote steigen in den letzten
        Sekunden, und Versandkosten sind nicht eingerechnet.
      </p>
    </div>
  );
}
