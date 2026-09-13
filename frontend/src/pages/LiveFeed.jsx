import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, formatEuro } from "../api.js";

function VerdictBadge({ verdict }) {
  if (!verdict) return null;
  const styles = {
    buy: "bg-emerald-600/20 text-emerald-300 ring-emerald-600/40",
    skip: "bg-rose-600/20 text-rose-300 ring-rose-600/40",
    unclear: "bg-amber-600/20 text-amber-300 ring-amber-600/40",
  };
  return (
    <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ${styles[verdict]}`}>
      {verdict}
    </span>
  );
}

function CascadeBadge({ item }) {
  if (item.is_unbewertbar) {
    return (
      <span className="rounded bg-slate-700/60 px-1.5 py-0.5 text-[11px] text-slate-300">
        unbewertbar
      </span>
    );
  }
  return (
    <span className="rounded bg-indigo-600/20 px-1.5 py-0.5 text-[11px] text-indigo-300 ring-1 ring-indigo-600/40">
      Stufe {item.cascade_level} · n={item.sample_size}
      {item.is_weak ? " · schwach" : ""}
    </span>
  );
}

function Card({ item }) {
  return (
    <Link
      to={`/candidates/${item.id}`}
      className="group flex flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-900 transition hover:border-slate-700 hover:bg-slate-800/60"
    >
      <div className="aspect-video w-full overflow-hidden bg-slate-800">
        {item.image ? (
          <img
            src={item.image}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover transition group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-slate-600">
            kein Bild
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-3">
        <div className="line-clamp-2 text-sm font-medium">{item.title}</div>
        <div className="mt-auto flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-slate-200">
            {formatEuro(item.price, item.currency)}
          </span>
          <VerdictBadge verdict={item.verdict} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <CascadeBadge item={item} />
          {item.estimated_profit != null && (
            <span className="rounded bg-emerald-600/20 px-1.5 py-0.5 text-[11px] text-emerald-300">
              +{formatEuro(item.estimated_profit)}
            </span>
          )}
        </div>
        <div className="truncate text-xs text-slate-500">
          {item.location || "—"} · {item.matched_search_term || "—"}
        </div>
      </div>
    </Link>
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

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Live Feed</h1>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={undecidedOnly}
            onChange={(e) => setUndecidedOnly(e.target.checked)}
            className="h-4 w-4 rounded border-slate-600 bg-slate-800"
          />
          nur unentschieden
        </label>
      </div>

      {error && <p className="text-rose-400">Fehler: {error}</p>}
      {loading ? (
        <p className="text-slate-400">lädt…</p>
      ) : items.length === 0 ? (
        <p className="text-slate-400">Noch keine Kandidaten.</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((item) => (
            <Card key={item.id} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}
