import { FormEvent, useEffect, useState } from "react";
import { ApiError, api } from "../lib/api";

type Source = { id: string; kind: string; title: string; url: string; citation: string; accessed_on: string };
type Note = { id: string; body: string; source_id: string | null; is_quote: boolean; page_ref: string; tags: string[]; created_at: string };
type Gate = { closed: boolean; closed_at: string | null; note: string; override_reason: string; mode: string };
type Vault = { sources: Source[]; notes: Note[]; gate: Gate };

const KINDS: Record<string, string> = { url: "strona WWW", book: "książka", article: "artykuł", interview: "wywiad", file: "plik", other: "inne" };

export default function ResearchTab({ base, canEdit }: { base: string; canEdit: boolean }) {
  const url = `${base}/research`;
  const [vault, setVault] = useState<Vault | null>(null);
  const [q, setQ] = useState("");
  const [src, setSrc] = useState({ kind: "url", title: "", url: "", citation: "", accessed_on: "" });
  const [note, setNote] = useState({ body: "", source_id: "", is_quote: false, page_ref: "", tags: "" });
  const [gateNote, setGateNote] = useState("");
  const [error, setError] = useState("");

  const load = (query = q) => api<Vault>(`${url}${query ? `?q=${encodeURIComponent(query)}` : ""}`).then(setVault).catch((e) => setError(e.message));
  useEffect(() => {
    load("");
  }, [base]);

  if (!vault) return <div className="muted">{error || "Ładowanie…"}</div>;
  const fail = (e: unknown) => setError(e instanceof ApiError ? e.message : "Coś poszło nie tak.");
  const srcName = (id: string | null) => vault.sources.find((s) => s.id === id)?.title || "";

  const addSource = async (e: FormEvent) => {
    e.preventDefault(); setError("");
    try {
      await api(`${url}/sources`, { method: "POST", body: { ...src, accessed_on: src.accessed_on || new Date().toISOString().slice(0, 10) } });
      setSrc({ kind: "url", title: "", url: "", citation: "", accessed_on: "" });
      load();
    } catch (err) { fail(err); }
  };
  const addNote = async (e: FormEvent) => {
    e.preventDefault(); setError("");
    try {
      await api(`${url}/notes`, { method: "POST", body: {
        body: note.body, source_id: note.source_id || null, is_quote: note.is_quote, page_ref: note.page_ref,
        tags: note.tags.split(",").map((t) => t.trim()).filter(Boolean),
      } });
      setNote({ body: "", source_id: note.source_id, is_quote: false, page_ref: "", tags: "" });
      load();
    } catch (err) { fail(err); }
  };
  const del = async (path: string) => { await api(`${url}/${path}`, { method: "DELETE" }).catch(fail); load(); };
  const gate = async (close: boolean) => {
    try {
      await api(`${url}/gate`, close ? { method: "POST", body: { note: gateNote } } : { method: "DELETE" });
      load();
    } catch (err) { fail(err); }
  };

  return (
    <div className="stack">
      <div className="card row spread">
        {vault.gate.closed ? (
          <span className="ok">Research zamknięty {vault.gate.closed_at && new Date(vault.gate.closed_at).toLocaleDateString("pl-PL")}
            {vault.gate.note && <span className="muted"> — {vault.gate.note}</span>}</span>
        ) : (
          <span>Research otwarty. {vault.gate.mode === "hard" ? "Pisanie ruszy po jego zamknięciu." : "Możesz zacząć pisać wcześniej, podając powód."}</span>
        )}
        {canEdit && (vault.gate.closed ? (
          <button className="ghost" onClick={() => gate(false)}>Otwórz ponownie</button>
        ) : (
          <div className="row">
            <input placeholder="Uwaga (opcjonalnie)" value={gateNote} onChange={(e) => setGateNote(e.target.value)} />
            <button onClick={() => gate(true)}>Research zamknięty</button>
          </div>
        ))}
      </div>

      <form className="row" onSubmit={(e) => { e.preventDefault(); load(); }}>
        <input style={{ flex: 1 }} placeholder="Szukaj w źródłach i notatkach…" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="ghost">Szukaj</button>
        {q && <button type="button" className="ghost" onClick={() => { setQ(""); load(""); }}>Wyczyść</button>}
      </form>
      {error && <div className="error">{error}</div>}

      <div className="grid grid-2">
        <div className="card stack">
          <h3>Źródła ({vault.sources.length})</h3>
          {vault.sources.map((s) => (
            <div key={s.id} className="stack" style={{ borderTop: "1px solid var(--line)", paddingTop: ".5rem", gap: ".2rem" }}>
              <div className="row spread">
                <b>{s.url ? <a href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a> : s.title}</b>
                {canEdit && <button className="ghost small" onClick={() => del(`sources/${s.id}`)}>usuń</button>}
              </div>
              <span className="muted small">{KINDS[s.kind]}{s.accessed_on && ` · dostęp ${s.accessed_on}`}</span>
              {s.citation && <span className="small">{s.citation}</span>}
            </div>
          ))}
          {canEdit && (
            <form className="stack" onSubmit={addSource}>
              <div className="row">
                <select value={src.kind} onChange={(e) => setSrc({ ...src, kind: e.target.value })}>
                  {Object.entries(KINDS).filter(([k]) => k !== "file").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
                <input style={{ flex: 1 }} placeholder="Tytuł źródła" value={src.title} onChange={(e) => setSrc({ ...src, title: e.target.value })} required />
              </div>
              <input placeholder="Link (opcjonalnie)" value={src.url} onChange={(e) => setSrc({ ...src, url: e.target.value })} />
              <input placeholder="Opis bibliograficzny: autor, rok, wydawca…" value={src.citation} onChange={(e) => setSrc({ ...src, citation: e.target.value })} />
              <button className="ghost">Dodaj źródło</button>
            </form>
          )}
        </div>

        <div className="card stack">
          <h3>Notatki i cytaty ({vault.notes.length})</h3>
          {canEdit && (
            <form className="stack" onSubmit={addNote}>
              <textarea placeholder="Notatka albo cytat" value={note.body} onChange={(e) => setNote({ ...note, body: e.target.value })} required />
              <div className="row">
                <select style={{ flex: 1 }} value={note.source_id} onChange={(e) => setNote({ ...note, source_id: e.target.value })}>
                  <option value="">— bez źródła —</option>
                  {vault.sources.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
                </select>
                <input style={{ width: 90 }} placeholder="strona" value={note.page_ref} onChange={(e) => setNote({ ...note, page_ref: e.target.value })} />
              </div>
              <div className="row">
                <label className="row" style={{ flexDirection: "row", color: "var(--text)" }}>
                  <input type="checkbox" checked={note.is_quote} onChange={(e) => setNote({ ...note, is_quote: e.target.checked })} /> cytat (wymaga źródła)
                </label>
                <input style={{ flex: 1 }} placeholder="tagi, po przecinku" value={note.tags} onChange={(e) => setNote({ ...note, tags: e.target.value })} />
              </div>
              <button className="ghost">Dodaj</button>
            </form>
          )}
          {vault.notes.map((n) => (
            <div key={n.id} className="stack" style={{ borderTop: "1px solid var(--line)", paddingTop: ".5rem", gap: ".2rem" }}>
              <div style={{ whiteSpace: "pre-line", fontStyle: n.is_quote ? "italic" : "normal" }}>{n.is_quote ? `„${n.body}”` : n.body}</div>
              <div className="row spread small muted">
                <span>{srcName(n.source_id)}{n.page_ref && `, ${n.page_ref}`}{n.tags.length > 0 && ` · #${n.tags.join(" #")}`}</span>
                {canEdit && <button className="ghost small" onClick={() => del(`notes/${n.id}`)}>usuń</button>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
