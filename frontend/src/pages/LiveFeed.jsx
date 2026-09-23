import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";

/** Preis als Zahl — die Waehrung steht in der Spaltenueberschrift. */
function num(value, digits = 2) {
  if (value === null || value === undefined) return "—";
  return Number(value).toLocaleString("de-DE", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function ago(iso) {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return `${Math.round(s)}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  if (s < 172800) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

// Der Wert-Status ist die wichtigste Spalte: er sagt, WORAUF eine Zahl beruht.
// Deshalb bekommt er Farbe — und die Farbe bedeutet jedes Mal dasselbe.
function Basis({ item }) {
  if (!item.is_unbewertbar) {
    const market = item.cascade_level === 4;
    return (
      <span
        className={`font-mono text-2xs ${market ? "text-psychic" : "text-grass"}`}
        title={
          market
            ? "Marktpreis — was verlangt wird, nicht was erzielt wurde"
            : `Verkaufsdaten, Stufe ${item.cascade_level}, n=${item.sample_size}`
        }
      >
        {market ? "MARKT" : `SOLD·${item.cascade_level}`}
        {!market && item.sample_size ? (
          <span className="text-paper-dim"> n={item.sample_size}</span>
        ) : null}
      </span>
    );
  }
  if (!item.valuation_attempted_at)
    return <span className="font-mono text-2xs text-paper-dim">OFFEN</span>;
  return (
    <span
      className="font-mono text-2xs text-paper-muted"
      title={item.valuation_note || "geprüft, kein Wert ermittelbar"}
    >
      KEIN WERT
    </span>
  );
}

function Verdict({ verdict }) {
  if (!verdict) return null;
  const tone = { buy: "text-grass", skip: "text-fire", unclear: "text-electric" }[
    verdict
  ];
  return (
    <span className={`font-mono text-2xs uppercase ${tone}`}>{verdict}</span>
  );
}

function Row({ item }) {
  const profit = item.estimated_profit;
  const positive = profit != null && Number(profit) > 0;
  return (
    <tr className="group border-b border-ink-850 transition-colors hover:bg-ink-900">
      <td className="py-2 pr-3 align-top">
        <span className="tnum text-2xs text-paper-dim">
          {ago(item.created_at)}
        </span>
      </td>
      <td className="py-2 pr-3 align-top">
        {item.image ? (
          <img
            src={item.image}
            alt=""
            loading="lazy"
            className="h-9 w-9 rounded-sm object-cover ring-1 ring-ink-800"
          />
        ) : (
          <div className="h-9 w-9 rounded-sm bg-ink-850 ring-1 ring-ink-800" />
        )}
      </td>
      <td className="max-w-0 py-2 pr-4 align-top">
        <Link
          to={`/candidates/${item.id}`}
          className="block truncate text-sm text-paper transition-colors group-hover:text-water"
        >
          {item.title}
        </Link>
        <div className="mt-0.5 truncate text-2xs text-paper-dim">
          {item.location || "—"}
          <span className="mx-1.5 text-ink-600">/</span>
          {item.matched_search_term || "—"}
          {item.is_unbewertbar && item.valuation_note && (
            <>
              <span className="mx-1.5 text-ink-600">/</span>
              <span className="text-paper-muted">{item.valuation_note}</span>
            </>
          )}
        </div>
      </td>
      <td className="whitespace-nowrap py-2 pr-4 align-top">
        <span className="font-mono text-2xs uppercase tracking-wider text-paper-dim">
          {item.channel.replace("_", " ")}
        </span>
      </td>
      <td className="whitespace-nowrap py-2 pr-4 text-right align-top">
        <span className="tnum text-sm text-paper">{num(item.price)}</span>
      </td>
      <td className="whitespace-nowrap py-2 pr-4 text-right align-top">
        <Basis item={item} />
      </td>
      <td className="whitespace-nowrap py-2 pr-4 text-right align-top">
        {profit == null ? (
          <span className="tnum text-sm text-paper-dim">—</span>
        ) : (
          <span
            className={`tnum text-sm font-medium ${
              positive ? "text-grass" : "text-fire"
            }`}
          >
            {positive ? "+" : "−"}
            {num(Math.abs(Number(profit)))}
          </span>
        )}
      </td>
      <td className="whitespace-nowrap py-2 text-right align-top">
        <Verdict verdict={item.verdict} />
      </td>
    </tr>
  );
}

export default function LiveFeed() {
  const [items, setItems] = useState([]);
  const [undecidedOnly, setUndecidedOnly] = useState(false);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .listCandidates({ undecidedOnly })
      .then(setItems)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [undecidedOnly]);

  const valued = items.filter((i) => !i.is_unbewertbar).length;
  const open = items.filter((i) => !i.valuation_attempted_at && i.is_unbewertbar)
    .length;

  return (
    <div>
      <div className="mb-4 flex items-baseline gap-6">
        <h1 className="text-lg font-semibold tracking-tight">Live Feed</h1>
        {/* Kennzahlen als Zeile, nicht als Kachelwand: drei Zahlen brauchen
            keine drei Kaesten. */}
        <div className="flex gap-5 font-mono text-2xs uppercase tracking-wider text-paper-dim">
          <span>
            {items.length} <span className="text-ink-600">Funde</span>
          </span>
          <span className="text-grass">
            {valued} <span className="text-ink-600">bewertet</span>
          </span>
          <span>
            {open} <span className="text-ink-600">offen</span>
          </span>
        </div>
        <label className="ml-auto flex cursor-pointer items-center gap-2 text-xs text-paper-muted hover:text-paper">
          <input
            type="checkbox"
            checked={undecidedOnly}
            onChange={(e) => setUndecidedOnly(e.target.checked)}
            className="h-3.5 w-3.5 rounded-sm border-ink-600 bg-ink-850 accent-water"
          />
          nur unentschieden
        </label>
      </div>

      {error && <p className="text-fire">Fehler: {error}</p>}

      <div className="overflow-x-auto">
        <table className="w-full table-fixed border-collapse">
          <colgroup>
            <col className="w-12" />
            <col className="w-12" />
            <col />
            <col className="w-28" />
            <col className="w-24" />
            <col className="w-28" />
            <col className="w-24" />
            <col className="w-16" />
          </colgroup>
          <thead>
            <tr className="border-b border-ink-700">
              <th className="colhead py-2 pr-3 text-left">Alter</th>
              <th className="colhead py-2 pr-3 text-left" />
              <th className="colhead py-2 pr-4 text-left">Angebot</th>
              <th className="colhead py-2 pr-4 text-left">Quelle</th>
              <th className="colhead py-2 pr-4 text-right">Preis €</th>
              <th className="colhead py-2 pr-4 text-right">Basis</th>
              <th className="colhead py-2 pr-4 text-right">Gewinn €</th>
              <th className="colhead py-2 text-right">Urteil</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={8} className="py-8 text-center text-sm text-paper-dim">
                  lädt…
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={8} className="py-8 text-center text-sm text-paper-dim">
                  Noch keine Kandidaten.
                </td>
              </tr>
            ) : (
              items.map((item) => <Row key={item.id} item={item} />)
            )}
          </tbody>
        </table>
      </div>

      <p className="mt-4 text-2xs text-paper-dim">
        <span className="text-grass">SOLD·n</span> = echte Verkaufspreise ·{" "}
        <span className="text-psychic">MARKT</span> = Angebotspreis, nur eine
        Schätzung · <span className="text-paper-muted">KEIN WERT</span> = geprüft,
        nichts ermittelbar · <span className="text-paper-dim">OFFEN</span> = noch
        nicht geprüft. Versandkosten sind in keiner Zahl enthalten.
      </p>
    </div>
  );
}
