import { useEffect, useState } from "react";
import { ApiError, api } from "../lib/api";

type Profile = { key: string; name: string; panel_url: string; formats: string[]; note: string; steps: string[] };
type ListingRow = {
  channel: string; status: string; url: string; notes: string; rejection_reason: string; checklist: number[];
  sent_at: string | null; published_at: string | null; profile: Profile; issues: string[];
};

export const LISTING_STATUSES: Record<string, string> = {
  not_ready: "Nieprzygotowane", ready: "Gotowe do wysyłki", sent: "Wysłane", in_review: "W weryfikacji",
  published: "Opublikowane", rejected: "Odrzucone", withdrawn: "Wycofane",
};

async function downloadPackage(path: string, filename: string) {
  // Authenticated download: fetch as blob with the bearer token, then save.
  const r = await fetch(`/api/v1${path}`, { headers: { Authorization: `Bearer ${localStorage.getItem("hrlb_access")}` } });
  if (!r.ok) throw new Error("Nie udało się przygotować pakietu.");
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function DistributionTab({ base, canManage, onPublished }: { base: string; canManage: boolean; onPublished: () => void }) {
  const [rows, setRows] = useState<ListingRow[] | null>(null);
  const [open, setOpen] = useState<string>("");
  const [error, setError] = useState("");

  const load = () => api<ListingRow[]>(`${base}/listings`).then(setRows).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, [base]);

  if (!rows) return <div className="muted">{error || "Ładowanie…"}</div>;

  const update = async (channel: string, body: Record<string, unknown>) => {
    setError("");
    try {
      await api(`${base}/listings/${channel}`, { method: "PUT", body });
      await load();
      if (body.status === "published") onPublished();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Nie udało się zapisać.");
    }
  };

  return (
    <div className="stack">
      {error && <div className="error">{error}</div>}
      {rows.map((r) => {
        const isOpen = open === r.channel;
        return (
          <div key={r.channel} className="card stack">
            <div className="row spread">
              <div>
                <h3 style={{ margin: 0 }}>{r.profile.name}</h3>
                {r.profile.note && <div className="muted small">{r.profile.note}</div>}
              </div>
              <div className="row">
                {canManage ? (
                  <select value={r.status} onChange={(e) => update(r.channel, { status: e.target.value })}>
                    {Object.entries(LISTING_STATUSES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                ) : (
                  <span className={`pill ${r.status}`}>{LISTING_STATUSES[r.status]}</span>
                )}
                <button className="ghost" onClick={() => setOpen(isOpen ? "" : r.channel)}>{isOpen ? "Zwiń" : "Szczegóły"}</button>
              </div>
            </div>
            {r.issues.length > 0 && (
              <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem", color: "var(--muted)" }}>
                {r.issues.map((i) => <li key={i}>{i}</li>)}
              </ul>
            )}
            {isOpen && (
              <div className="grid grid-2">
                <div className="stack">
                  <b className="small">Kroki w panelu kanału</b>
                  {r.profile.steps.map((s, i) => (
                    <label key={i} style={{ flexDirection: "row", alignItems: "flex-start", gap: ".5rem", color: "var(--text)" }}>
                      <input type="checkbox" disabled={!canManage} checked={r.checklist.includes(i)}
                        onChange={(e) => update(r.channel, {
                          checklist: e.target.checked ? [...r.checklist, i] : r.checklist.filter((x) => x !== i),
                        })} />
                      <span className="small">{s}</span>
                    </label>
                  ))}
                </div>
                <div className="stack">
                  <a className="btn ghost" href={r.profile.panel_url} target="_blank" rel="noopener noreferrer">Otwórz panel {r.profile.name} ↗</a>
                  {canManage && (
                    <button onClick={() => downloadPackage(`${base}/package/${r.channel}`, `pakiet-${r.channel}.zip`).catch((e) => setError(e.message))}>
                      Pobierz pakiet (metadane + instrukcja)
                    </button>
                  )}
                  <label>Link do książki w sklepie
                    <input defaultValue={r.url} disabled={!canManage} placeholder="https://…"
                      onBlur={(e) => e.target.value !== r.url && update(r.channel, { url: e.target.value })} />
                  </label>
                  {r.status === "rejected" && (
                    <label>Powód odrzucenia
                      <textarea defaultValue={r.rejection_reason} disabled={!canManage}
                        onBlur={(e) => e.target.value !== r.rejection_reason && update(r.channel, { rejection_reason: e.target.value })} />
                    </label>
                  )}
                  <label>Notatki
                    <textarea defaultValue={r.notes} disabled={!canManage}
                      onBlur={(e) => e.target.value !== r.notes && update(r.channel, { notes: e.target.value })} />
                  </label>
                  <div className="muted small">
                    {r.sent_at && <>Wysłano: {new Date(r.sent_at).toLocaleDateString("pl-PL")} </>}
                    {r.published_at && <>· Opublikowano: {new Date(r.published_at).toLocaleDateString("pl-PL")}</>}
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
