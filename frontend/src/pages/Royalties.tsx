import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useWorkspace } from "../App";
import { api, Book } from "../lib/api";

type Money = { units: number; amounts: Record<string, number> };
type Summary = {
  years: string[]; totals: Money; channels: Record<string, string>;
  by_book: (Money & { book_id: string; title: string })[];
  by_channel: (Money & { channel: string; label: string })[];
  by_month: (Money & { period: string })[];
  unmatched: (Money & { raw_title: string })[];
  imports: { id: string; channel: string; label: string; filename: string; rows: number; duplicates: number; created_at: string }[];
};
const FIELD_LABELS: Record<string, string> = { title: "Tytuł *", amount: "Kwota *", units: "Sztuki", period: "Data", currency: "Waluta", id: "ISBN/ASIN", market: "Rynek" };
const MONTHS = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"];

export const fmt = (m: Money) => Object.entries(m.amounts).map(([c, a]) => `${a.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${c}`).join(" + ") || "—";
const monthLabel = (p: string) => `${MONTHS[Number(p.slice(5, 7)) - 1]} ${p.slice(0, 4)}`;

function Breakdown({ s }: { s: Summary }) {
  const max = Math.max(1, ...s.by_month.map((x) => x.units));
  return (
    <div className="grid grid-2">
      <div className="card stack">
        <h3>Sklepy</h3>
        {s.by_channel.length === 0 && <span className="muted">Brak danych.</span>}
        {s.by_channel.map((c) => <div key={c.channel} className="row spread"><span>{c.label}</span><span>{c.units} szt. · <b>{fmt(c)}</b></span></div>)}
      </div>
      <div className="card stack">
        <h3>Miesiące</h3>
        {s.by_month.length === 0 && <span className="muted">Brak danych.</span>}
        {s.by_month.map((m) => (
          <div key={m.period} className="stack" style={{ gap: ".15rem" }}>
            <div className="row spread small"><span>{monthLabel(m.period)}</span><span>{m.units} szt. · {fmt(m)}</span></div>
            <div style={{ height: 6, borderRadius: 3, background: "var(--gold)", width: `${(m.units / max) * 100}%`, minWidth: 2 }} />
          </div>
        ))}
      </div>
    </div>
  );
}

/** Workspace page: import reports, totals per title / store / month, unmatched rows. */
export default function RoyaltiesPage() {
  const { ws } = useParams();
  const workspace = useWorkspace();
  const [s, setS] = useState<Summary | null>(null);
  const [books, setBooks] = useState<Book[]>([]);
  const [year, setYear] = useState("");
  const [form, setForm] = useState({ channel: "kdp", period: "", currency: "PLN" });
  const [file, setFile] = useState<File | null>(null);
  const [headers, setHeaders] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = (y = year) => api<Summary>(`/workspaces/${ws}/royalties${y ? `?year=${y}` : ""}`).then(setS).catch((e) => setError(e.message));
  useEffect(() => { load(); api<Book[]>(`/workspaces/${ws}/books`).then(setBooks); }, [ws]);

  if (workspace && workspace.role !== "owner") return <div className="card empty">Tantiemy widzi tylko właściciel przestrzeni.</div>;
  if (!s) return <div className="muted">{error || "Ładowanie…"}</div>;

  const upload = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true); setError(""); setMsg("");
    const fd = new FormData();
    fd.append("file", file); fd.append("channel", form.channel); fd.append("period", form.period); fd.append("currency", form.currency);
    if (headers.length) fd.append("mapping", JSON.stringify(Object.fromEntries(Object.entries(mapping).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)]))));
    const r = await fetch(`/api/v1/workspaces/${ws}/royalties/import`, { method: "POST", body: fd,
      headers: { Authorization: `Bearer ${localStorage.getItem("hrlb_access")}` } });
    const d = await r.json().catch(() => ({}));
    setBusy(false);
    if (!r.ok) {
      setError(d.detail?.message || (typeof d.detail === "string" ? d.detail : "Import się nie udał."));
      if (d.detail?.headers?.length) setHeaders(d.detail.headers);
      return;
    }
    setMsg(`Zaimportowano wierszy: ${d.rows}${d.duplicates ? ` (pominięto ${d.duplicates} już wcześniej wczytanych)` : ""}.`);
    setHeaders([]); setMapping({}); setFile(null);
    (document.getElementById("roy-file") as HTMLInputElement).value = "";
    load();
  };
  const assign = async (raw_title: string, book_id: string) => {
    await api(`/workspaces/${ws}/royalties/assign`, { method: "POST", body: { raw_title, book_id: book_id || null } });
    load();
  };
  const removeImport = async (id: string) => {
    if (!confirm("Usunąć ten import razem z jego wierszami?")) return;
    await api(`/workspaces/${ws}/royalties/imports/${id}`, { method: "DELETE" });
    load();
  };

  return (
    <div className="stack">
      <div className="row spread">
        <div><Link to={`/w/${ws}`} className="small">← Tytuły</Link><h1 style={{ margin: ".2rem 0 0" }}>Tantiemy</h1></div>
        <select value={year} onChange={(e) => { setYear(e.target.value); load(e.target.value); }}>
          <option value="">Cały okres</option>{s.years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>

      <form className="card stack" onSubmit={upload}>
        <h3>Wczytaj raport sprzedaży</h3>
        <p className="muted small">Plik CSV albo XLSX pobrany z panelu sklepu (np. KDP → Raporty → Tantiemy). Kolumny rozpoznajemy same; ten sam raport wczytany drugi raz nie zdubluje danych.</p>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <label>Sklep<select value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value })}>
            {Object.entries(s.channels).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label>Miesiąc (gdy raport nie ma dat)<input type="month" value={form.period} onChange={(e) => setForm({ ...form, period: e.target.value })} /></label>
          <label>Waluta domyślna<select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>
            {["PLN", "EUR", "USD", "GBP"].map((c) => <option key={c}>{c}</option>)}</select></label>
          <label>Plik<input id="roy-file" type="file" accept=".csv,.xlsx,.txt" onChange={(e) => { setFile(e.target.files?.[0] || null); setHeaders([]); }} /></label>
        </div>
        {headers.length > 0 && (
          <div className="stack">
            <b className="small">Wskaż, która kolumna jest którą:</b>
            <div className="row" style={{ flexWrap: "wrap" }}>
              {Object.entries(FIELD_LABELS).map(([f, label]) => (
                <label key={f} className="small">{label}
                  <select value={mapping[f] ?? ""} onChange={(e) => setMapping({ ...mapping, [f]: e.target.value })}>
                    <option value="">—</option>{headers.map((h, i) => <option key={i} value={i}>{h || `kolumna ${i + 1}`}</option>)}
                  </select>
                </label>
              ))}
            </div>
          </div>
        )}
        <div className="row"><button disabled={!file || busy}>{busy ? "Wczytuję…" : "Wczytaj"}</button>
          {msg && <span className="ok">{msg}</span>}</div>
        {error && <div className="error">{error}</div>}
      </form>

      <div className="card row spread">
        <span>Razem{year && ` w ${year}`}: <b>{s.totals.units}</b> szt.</span>
        <b style={{ fontSize: "1.3rem" }}>{fmt(s.totals)}</b>
      </div>

      <div className="card stack">
        <h3>Tytuły</h3>
        {s.by_book.length === 0 && <span className="muted">Wczytaj pierwszy raport.</span>}
        {s.by_book.map((b) => (
          <div key={b.book_id} className="row spread"><Link to={`/w/${ws}/ksiazki/${b.book_id}?tab=Tantiemy`}>{b.title}</Link><span>{b.units} szt. · <b>{fmt(b)}</b></span></div>
        ))}
      </div>

      {s.unmatched.length > 0 && (
        <div className="card stack">
          <h3>Nieprzypisane pozycje z raportów ({s.unmatched.length})</h3>
          <p className="muted small">Tytuł w raporcie różni się od tytułu w HRL Books. Przypisz go raz — kolejne raporty dopasują się same.</p>
          {s.unmatched.map((u) => (
            <div key={u.raw_title} className="row spread" style={{ borderTop: "1px solid var(--line)", paddingTop: ".4rem" }}>
              <span>{u.raw_title} <span className="muted small">· {u.units} szt. · {fmt(u)}</span></span>
              <select defaultValue="" onChange={(e) => e.target.value && assign(u.raw_title, e.target.value)}>
                <option value="">przypisz do…</option>{books.map((b) => <option key={b.id} value={b.id}>{b.title}</option>)}
              </select>
            </div>
          ))}
        </div>
      )}

      <Breakdown s={s} />

      {s.imports.length > 0 && (
        <div className="card stack">
          <h3>Wczytane raporty</h3>
          {s.imports.map((i) => (
            <div key={i.id} className="row spread small">
              <span>{new Date(i.created_at).toLocaleString("pl-PL")} · {i.label} · {i.filename} · {i.rows} wierszy{i.duplicates ? ` (+${i.duplicates} powtórzonych)` : ""}</span>
              <button className="ghost small" onClick={() => removeImport(i.id)}>usuń</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** Book tab: this title's revenue. */
export function BookRoyalties({ ws, bookId, isOwner }: { ws: string; bookId: string; isOwner: boolean }) {
  const [s, setS] = useState<Summary | null>(null);
  useEffect(() => { if (isOwner) api<Summary>(`/workspaces/${ws}/royalties?book_id=${bookId}`).then(setS); }, [ws, bookId, isOwner]);
  if (!isOwner) return <div className="card empty">Tantiemy widzi tylko właściciel przestrzeni.</div>;
  if (!s) return <div className="muted">Ładowanie…</div>;
  return (
    <div className="stack">
      <div className="card row spread">
        <span>Sprzedaż tego tytułu: <b>{s.totals.units}</b> szt.</span>
        <b style={{ fontSize: "1.3rem" }}>{fmt(s.totals)}</b>
      </div>
      {s.totals.units === 0 && <div className="card muted">Brak danych. Raporty ze sklepów wczytasz w <Link to={`/w/${ws}/tantiemy`}>Tantiemach</Link>.</div>}
      <Breakdown s={s} />
    </div>
  );
}
