import { FormEvent, useEffect, useState } from "react";
import { ApiError, api } from "../lib/api";

export type Volume = {
  id: string; title: string; subtitle: string; authors: string[]; publisher: string; published_date: string;
  isbn13: string; isbn10: string; pages: number | null; cover_url: string; is_ebook: boolean; store_url: string; exists?: boolean;
};

function useSearch(path: string) {
  const [results, setResults] = useState<Volume[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async (q: string) => {
    if (q.trim().length < 2) return;
    setBusy(true); setError("");
    try {
      setResults((await api<{ results: Volume[] }>(`${path}/google-books/search?q=${encodeURIComponent(q.trim())}`)).results);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Wyszukiwanie się nie udało.");
    } finally {
      setBusy(false);
    }
  };
  return { results, busy, error, run };
}

function Row({ v, children }: { v: Volume; children?: React.ReactNode }) {
  return (
    <div className="row" style={{ alignItems: "flex-start", borderTop: "1px solid var(--line)", paddingTop: ".6rem", gap: ".8rem" }}>
      {v.cover_url ? <img src={v.cover_url} alt="" style={{ width: 46, height: 68, objectFit: "cover", borderRadius: 4, background: "#222" }} />
        : <div style={{ width: 46, height: 68, borderRadius: 4, background: "var(--panel-2)" }} />}
      <div className="stack" style={{ flex: 1, gap: ".15rem" }}>
        <b>{v.title}{v.subtitle && <span className="muted">: {v.subtitle}</span>}</b>
        <span className="small muted">
          {[v.authors.join(", "), v.publisher, v.published_date, v.isbn13 && `ISBN ${v.isbn13}`, v.pages && `${v.pages} s.`, v.is_ebook ? "e-book" : "druk"].filter(Boolean).join(" · ")}
        </span>
      </div>
      {children}
    </div>
  );
}

/** Books list: find already-published titles on Google Books and import them in one go. */
export function GoogleBooksImport({ ws, onDone }: { ws: string; onDone: () => void }) {
  const [q, setQ] = useState("Kamil Skomra");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [msg, setMsg] = useState("");
  const [importing, setImporting] = useState(false);
  const { results, busy, error, run } = useSearch(`/workspaces/${ws}`);
  const [err, setErr] = useState("");

  const submit = (e: FormEvent) => { e.preventDefault(); setPicked(new Set()); setMsg(""); run(q); };
  const doImport = async () => {
    setImporting(true); setErr(""); setMsg("");
    try {
      const r = await api<{ imported: { title: string }[]; skipped: { title?: string; reason: string }[] }>(
        `/workspaces/${ws}/google-books/import`, { method: "POST", body: { volume_ids: [...picked] } });
      setMsg(`Zaimportowano: ${r.imported.length}${r.skipped.length ? `, pominięto: ${r.skipped.length} (${r.skipped.map((s) => s.reason).join("; ")})` : ""}. ` +
        "Każdy tytuł ma już opis, autora, wydanie z ISBN, okładkę i link do Google Play.");
      setPicked(new Set());
      onDone();
      run(q);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Import się nie udał.");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="card stack">
      <h3>Import z Google Books</h3>
      <p className="muted small">Wyszukaj po autorze, tytule albo ISBN. Zaznacz swoje książki — przeniesiemy tytuł, podtytuł, opis, autorów, kategorie, ISBN, liczbę stron, datę wydania, okładkę i link do sklepu.</p>
      <form className="row" onSubmit={submit}>
        <input style={{ flex: 1 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="np. Kamil Skomra albo 978…" />
        <button disabled={busy}>{busy ? "Szukam…" : "Szukaj"}</button>
      </form>
      {(error || err) && <div className="error">{error || err}</div>}
      {msg && <div className="ok">{msg}</div>}
      {results && results.length === 0 && <div className="muted">Brak wyników.</div>}
      {results?.map((v) => (
        <Row key={v.id} v={v}>
          {v.exists ? <span className="muted small">już w katalogu</span> : (
            <label className="row small" style={{ flexDirection: "row", color: "var(--text)" }}>
              <input type="checkbox" checked={picked.has(v.id)} onChange={(e) => {
                const n = new Set(picked); if (e.target.checked) n.add(v.id); else n.delete(v.id); setPicked(n);
              }} /> importuj
            </label>
          )}
        </Row>
      ))}
      {results && results.length > 0 && (
        <div className="row"><button onClick={doImport} disabled={!picked.size || importing}>{importing ? "Importuję…" : `Importuj zaznaczone (${picked.size})`}</button></div>
      )}
    </div>
  );
}

/** Metadata tab: fill empty fields of this title from a Google Books entry (never overwrites). */
export function GoogleBooksFill({ base, onDone }: { base: string; onDone: () => void }) {
  const ws = base.split("/books/")[0];
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const { results, busy, error, run } = useSearch(ws);

  useEffect(() => {
    if (open && !q) api<{ title: string }>(base).then((b) => { setQ(b.title); run(b.title); }).catch(() => {});
  }, [open]);

  const fill = async (v: Volume) => {
    setErr(""); setMsg("");
    try {
      const r = await api<{ filled: string[] }>(`${base}/google-books/fill`, { method: "POST", body: { volume_id: v.id } });
      setMsg(r.filled.length ? `Uzupełniono: ${r.filled.join(", ")}. Pola, które już miały treść, zostały bez zmian.` : "Nic do uzupełnienia — wszystkie pola są już wypełnione.");
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Nie udało się uzupełnić.");
    }
  };

  if (!open) return <button className="ghost" type="button" onClick={() => setOpen(true)}>Uzupełnij z Google Books</button>;
  return (
    <div className="card stack">
      <div className="row spread"><h3 style={{ margin: 0 }}>Uzupełnij z Google Books</h3>
        <button className="ghost small" type="button" onClick={() => setOpen(false)}>zamknij</button></div>
      <form className="row" onSubmit={(e) => { e.preventDefault(); run(q); }}>
        <input style={{ flex: 1 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="tytuł, autor albo ISBN" />
        <button className="ghost" disabled={busy}>{busy ? "Szukam…" : "Szukaj"}</button>
      </form>
      {(error || err) && <div className="error">{error || err}</div>}
      {msg && <div className="ok">{msg}</div>}
      {results?.map((v) => (
        <Row key={v.id} v={v}><button className="ghost small" type="button" onClick={() => fill(v)}>użyj tych danych</button></Row>
      ))}
      {results && results.length === 0 && <div className="muted">Brak wyników.</div>}
    </div>
  );
}
