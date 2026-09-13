import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, formatDate, formatEuro } from "../api.js";

const COUNTERFEIT_OPTIONS = [
  { value: "", label: "— bitte wählen —" },
  { value: "passed", label: "geprüft: echt" },
  { value: "failed", label: "geprüft: Fälschung" },
  { value: "unsure", label: "unsicher" },
  { value: "not_checked", label: "nicht geprüft" },
];

function CompsTable({ rv }) {
  if (!rv) {
    return (
      <p className="text-slate-400">
        Kein Referenzwert — <span className="text-slate-300">unbewertbar</span>,
        bitte selbst prüfen.
      </p>
    );
  }
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
        <span className="font-semibold">
          Referenzwert {formatEuro(rv.value, rv.currency)}
        </span>
        <span className="rounded bg-indigo-600/20 px-1.5 py-0.5 text-xs text-indigo-300">
          Stufe {rv.cascade_level} · n={rv.sample_size}
          {rv.is_weak ? " · schwach" : ""}
        </span>
        <span className="text-xs text-slate-500">Quelle: {rv.source}</span>
      </div>
      {rv.comps.length === 0 ? (
        <p className="text-sm text-slate-500">
          Keine Einzel-Comps gespeichert (z.B. TCGdex-Referenz).
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-800/60 text-xs uppercase text-slate-400">
              <tr>
                <th className="px-3 py-2">Preis</th>
                <th className="px-3 py-2">Verkauft</th>
                <th className="px-3 py-2">Sprache</th>
                <th className="px-3 py-2">Zustand</th>
                <th className="px-3 py-2">BOA</th>
                <th className="px-3 py-2">Item</th>
              </tr>
            </thead>
            <tbody>
              {rv.comps.map((c) => (
                <tr key={c.id} className="border-t border-slate-800">
                  <td className="px-3 py-2 font-medium">
                    {formatEuro(c.price, c.currency)}
                  </td>
                  <td className="px-3 py-2 text-slate-400">
                    {c.sold_at ? formatDate(c.sold_at) : "—"}
                  </td>
                  <td className="px-3 py-2">{c.language}</td>
                  <td className="px-3 py-2">{c.condition}</td>
                  <td className="px-3 py-2">
                    {c.boa_hydrated ? (
                      <span className="text-emerald-400">✓</span>
                    ) : (
                      <span className="text-amber-400" title="nicht BOA-hydratisiert">
                        !
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-slate-500">
                    {c.source_item_id || "—"}
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

function DecisionForm({ candidateId, existing, onSaved }) {
  const [verdict, setVerdict] = useState(existing?.verdict || "");
  const [counterfeit, setCounterfeit] = useState(existing?.counterfeit_check || "");
  const [reason, setReason] = useState(existing?.reason || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const canSubmit = verdict && counterfeit; // Fälschungsprüfung ist Pflicht (§7)

  const submit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await api.putDecision(candidateId, {
        verdict,
        counterfeit_check: counterfeit,
        reason: reason || null,
      });
      onSaved(saved);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const verdictBtn = (value, label, active, activeCls) => (
    <button
      type="button"
      onClick={() => setVerdict(value)}
      className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium ring-1 transition ${
        verdict === value
          ? activeCls
          : "bg-slate-800 text-slate-300 ring-slate-700 hover:bg-slate-700"
      }`}
    >
      {label}
    </button>
  );

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="flex gap-2">
        {verdictBtn("buy", "Buy", true, "bg-emerald-600 text-white ring-emerald-500")}
        {verdictBtn("skip", "Skip", true, "bg-rose-600 text-white ring-rose-500")}
        {verdictBtn("unclear", "Unclear", true, "bg-amber-600 text-white ring-amber-500")}
      </div>

      <div>
        <label className="mb-1 block text-sm text-slate-300">
          Fälschungsprüfung <span className="text-rose-400">*</span>
        </label>
        <select
          value={counterfeit}
          onChange={(e) => setCounterfeit(e.target.value)}
          className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
        >
          {COUNTERFEIT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="mb-1 block text-sm text-slate-300">Grund</label>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          placeholder="Warum? (auch bei Skip wichtig — Kalibrierungsdaten)"
          className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
        />
      </div>

      {error && <p className="text-sm text-rose-400">{error}</p>}
      <button
        type="submit"
        disabled={!canSubmit || saving}
        className="w-full rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {saving ? "speichert…" : existing ? "Urteil aktualisieren" : "Urteil speichern"}
      </button>
      {!canSubmit && (
        <p className="text-xs text-slate-500">
          Verdict und Fälschungsprüfung sind Pflicht.
        </p>
      )}
    </form>
  );
}

export default function CandidateDetail() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = () =>
    api.getCandidate(id).then(setData).catch((e) => setError(e.message));

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (error) return <p className="text-rose-400">Fehler: {error}</p>;
  if (!data) return <p className="text-slate-400">lädt…</p>;

  const l = data.listing;

  return (
    <div>
      <Link to="/" className="mb-4 inline-block text-sm text-indigo-400 hover:underline">
        ← zurück zum Feed
      </Link>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <h1 className="text-xl font-semibold">{l.title}</h1>
          <div className="flex flex-wrap items-center gap-3 text-sm text-slate-400">
            <span className="text-base font-semibold text-slate-100">
              {formatEuro(l.price, l.currency)}
            </span>
            <span>{l.location || "—"}</span>
            <span>{l.seller_type}</span>
            <span>{l.channel}</span>
            {l.url && (
              <a
                href={l.url}
                target="_blank"
                rel="noreferrer"
                className="text-indigo-400 hover:underline"
              >
                zum Listing ↗
              </a>
            )}
          </div>

          {l.images.length > 0 && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {l.images.map((src, i) => (
                <a key={i} href={src} target="_blank" rel="noreferrer">
                  <img
                    src={src}
                    alt=""
                    className="aspect-square w-full rounded-lg border border-slate-800 object-cover"
                  />
                </a>
              ))}
            </div>
          )}

          {l.description && (
            <div className="whitespace-pre-wrap rounded-lg border border-slate-800 bg-slate-900 p-4 text-sm text-slate-300">
              {l.description}
            </div>
          )}

          <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
              Referenzwert & Comps
            </h2>
            <CompsTable rv={data.reference_value} />
          </section>
        </div>

        <div className="space-y-4">
          <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
              Urteil
            </h2>
            <DecisionForm
              candidateId={id}
              existing={data.decision}
              onSaved={() => load()}
            />
          </section>

          {data.enrichment && (
            <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
                Anreicherung <span className="text-slate-500">(Hinweis, keine Bewertung)</span>
              </h2>
              {data.enrichment.condition_flags.length > 0 ? (
                <div className="mb-3 flex flex-wrap gap-1.5">
                  {data.enrichment.condition_flags.map((f) => (
                    <span
                      key={f}
                      className="rounded bg-amber-600/20 px-1.5 py-0.5 text-[11px] text-amber-300 ring-1 ring-amber-600/40"
                    >
                      {f}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="mb-3 text-xs text-slate-500">
                  keine Zustandshinweise im Text
                </p>
              )}
              {data.enrichment.vision_summary ? (
                <p className="whitespace-pre-wrap text-sm text-slate-300">
                  👁️ {data.enrichment.vision_summary}
                </p>
              ) : (
                <p className="text-xs text-slate-500">keine Vision-Triage</p>
              )}
            </section>
          )}

          <section className="rounded-lg border border-slate-800 bg-slate-900 p-4 text-sm text-slate-400">
            <div className="flex justify-between">
              <span>Suchbegriff</span>
              <span className="text-slate-200">{data.matched_search_term || "—"}</span>
            </div>
            <div className="flex justify-between">
              <span>Alarm gesendet</span>
              <span className="text-slate-200">{formatDate(data.alert_sent_at)}</span>
            </div>
            <div className="flex justify-between">
              <span>Gesch. Gewinn</span>
              <span className="text-slate-200">
                {data.estimated_profit != null
                  ? formatEuro(data.estimated_profit)
                  : "unbewertbar"}
              </span>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
