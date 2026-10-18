import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useWorkspace } from "../App";
import { api } from "../lib/api";
import { LISTING_STATUSES } from "./DistributionTab";

type Cell = { status: string; issues: string[]; can_prepare: boolean };
type Row = {
  book_id: string; title: string; language: string; public: boolean; kdp_select: boolean; has_cover: boolean;
  gaps: string[]; isbn_missing: string[]; cells: Record<string, Cell>;
};
type Overview = {
  channels: { key: string; name: string; panel_url: string }[];
  isbn: { total: number; used: number; free: number };
  rows: Row[];
};
type Pool = { total: number; used: number; free: number; items: { isbn: string; display: string; note: string; title: string; format: string }[] };

const COLORS: Record<string, string> = {
  published: "var(--green)", rejected: "var(--red)", in_review: "var(--gold-2)", sent: "var(--gold)",
  ready: "var(--text)", not_ready: "var(--muted)", withdrawn: "var(--muted)",
};
const FORMAT_PL: Record<string, string> = { ebook_epub: "e-book", ebook_pdf: "e-book PDF", paperback: "miękka", hardcover: "twarda", audiobook: "audiobook" };

async function download(path: string, filename: string) {
  const r = await fetch(`/api/v1${path}`, { headers: { Authorization: `Bearer ${localStorage.getItem("hrlb_access")}` } });
  if (!r.ok) throw new Error("Nie udało się przygotować paczki.");
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

export default function Publishing() {
  const { ws } = useParams();
  const workspace = useWorkspace();
  const [data, setData] = useState<Overview | null>(null);
  const [pool, setPool] = useState<Pool | null>(null);
  const [text, setText] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [showPool, setShowPool] = useState(false);
  const base = `/workspaces/${ws}`;

  const load = () => {
    api<Overview>(`${base}/publishing`).then(setData).catch((e) => setError(e.message));
    api<Pool>(`${base}/isbn-pool`).then(setPool).catch(() => undefined);
  };
  useEffect(load, [ws]);

  const run = async (label: string, fn: () => Promise<string | void>) => {
    setBusy(label); setError(""); setMsg("");
    try { const m = await fn(); if (m) setMsg(m); load(); } catch (e) { setError((e as Error).message); } finally { setBusy(""); }
  };

  const prepareAll = () => run("prepare", async () => {
    const r = await api<{ isbn_assigned: number; marked_ready: number; blocked: { title: string; channel: string; why: string }[] }>(`${base}/publishing/prepare`, { method: "POST" });
    return `Przydzielono ISBN: ${r.isbn_assigned}. Oznaczono jako gotowe do wysyłki: ${r.marked_ready}. Zablokowane: ${r.blocked.length}.`;
  });
  const verify = () => run("verify", async () => {
    const r = await api<{ checked: number; published: number; unknown: number }>(`${base}/publishing/verify`, { method: "POST" });
    return `Sprawdzono ${r.checked}, opublikowane: ${r.published}${r.unknown ? `, sklepy blokujące boty: ${r.unknown}` : ""}.`;
  });
  const importIsbn = () => run("isbn", async () => {
    const r = await api<{ added: number; duplicates: number; rejected: string[]; free: number }>(`${base}/isbn-pool/import`, { method: "POST", body: { text, note } });
    setText("");
    return `Dodano ${r.added}, duplikaty: ${r.duplicates}, odrzucone (zła suma kontrolna): ${r.rejected.length}. Wolnych numerów: ${r.free}.`;
  });
  const assign = (id: string) => run(`isbn-${id}`, async () => {
    const r = await api<{ assigned: unknown[]; pool_empty_for: string[] }>(`${base}/books/${id}/isbn/assign`, { method: "POST", body: {} });
    return r.pool_empty_for.length ? "Pula ISBN jest pusta — dodaj numery." : `Przydzielono ISBN: ${r.assigned.length}.`;
  });
  const toggleSelect = (r: Row) => run(`kdp-${r.book_id}`, async () => {
    await api(`${base}/books/${r.book_id}`, { method: "PATCH", body: { kdp_select: !r.kdp_select } });
  });

  return (
    <div className="stack">
      <Link to={`/w/${ws}`} className="small">← {workspace?.name}</Link>
      <div className="row spread">
        <div>
          <h1>Centrum publikacji</h1>
          <p className="muted small">Jedno miejsce: gotowość każdej książki w każdym sklepie, numery ISBN, paczki do wgrania i sprawdzanie statusów.</p>
        </div>
        <div className="row">
          <button disabled={!!busy} onClick={prepareAll}>{busy === "prepare" ? "Przygotowuję…" : "Przygotuj wszystko"}</button>
          <button className="ghost" disabled={!!busy} onClick={() => run("zip", () => download(`${base}/publishing/package`, "HRL-Books-paczki.zip").then(() => "Pobrano paczki wszystkich tytułów."))}>Pobierz wszystkie paczki</button>
          <button className="ghost" disabled={!!busy} onClick={verify}>{busy === "verify" ? "Sprawdzam…" : "Sprawdź statusy w sklepach"}</button>
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {msg && <div className="ok">{msg}</div>}

      <div className="card">
        <div className="row spread">
          <b>Pula ISBN</b>
          <span className="small muted">{data ? `${data.isbn.free} wolnych · ${data.isbn.used} przydzielonych · razem ${data.isbn.total}` : "…"}</span>
        </div>
        <p className="small muted">Wklej numery (po jednym w wierszu, z kreskami lub bez). Każdy format książki dostaje osobny numer — system przydziela kolejny wolny i nigdy go nie powtarza.</p>
        <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="978-83-…" />
        <div className="row">
          <input style={{ maxWidth: 320 }} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Notatka, np. „pula z BN, paź 2026”" />
          <button disabled={!text.trim() || !!busy} onClick={importIsbn}>Dodaj do puli</button>
          <button className="ghost" onClick={() => setShowPool(!showPool)}>{showPool ? "Ukryj listę" : "Pokaż listę"}</button>
        </div>
        {showPool && pool && (
          <table style={{ marginTop: ".6rem" }}>
            <thead><tr><th>ISBN</th><th>Stan</th><th>Notatka</th></tr></thead>
            <tbody>
              {pool.items.map((i) => (
                <tr key={i.isbn}>
                  <td className="small">{i.display}</td>
                  <td className="small">{i.title ? `${i.title} (${FORMAT_PL[i.format] || i.format})` : <span className="muted">wolny</span>}</td>
                  <td className="small muted">{i.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {data && (
        <div className="card" style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr><th>Tytuł</th><th>Gotowość</th>{data.channels.map((c) => <th key={c.key}><a href={c.panel_url} target="_blank" rel="noreferrer">{c.name}</a></th>)}<th></th></tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.book_id}>
                  <td><Link to={`/w/${ws}/ksiazki/${r.book_id}?tab=Dystrybucja`}><b>{r.title}</b></Link>
                    <div className="small muted">{r.language.toUpperCase()} · {r.has_cover ? "okładka ✓" : "bez okładki"}</div></td>
                  <td className="small">
                    {r.gaps.length === 0 && r.isbn_missing.length === 0 ? <span className="ok">kompletne</span> : (
                      <>
                        {r.gaps.length > 0 && <div style={{ color: "var(--gold)" }}>brak: {r.gaps.join(", ")}</div>}
                        {r.isbn_missing.length > 0 && <div className="muted">bez ISBN: {r.isbn_missing.map((f) => FORMAT_PL[f] || f).join(", ")}</div>}
                      </>
                    )}
                    <label className="small" style={{ display: "flex", gap: ".35rem", alignItems: "center", marginTop: ".25rem" }}>
                      <input type="checkbox" checked={r.kdp_select} disabled={!!busy} onChange={() => toggleSelect(r)} /> KDP Select
                    </label>
                  </td>
                  {data.channels.map((c) => {
                    const cell = r.cells[c.key];
                    return (
                      <td key={c.key} className="small" style={{ color: COLORS[cell.status] }} title={cell.issues.join("\n")}>
                        {LISTING_STATUSES[cell.status]}
                        {cell.issues.length > 0 && cell.status !== "published" && <div style={{ color: "var(--gold)" }}>⚠ {cell.issues.length}</div>}
                      </td>
                    );
                  })}
                  <td className="small" style={{ whiteSpace: "nowrap" }}>
                    {r.isbn_missing.length > 0 && <button className="ghost" disabled={!!busy} onClick={() => assign(r.book_id)}>Przydziel ISBN</button>}{" "}
                    <button className="ghost" disabled={!!busy} onClick={() => run(`z-${r.book_id}`, () => download(`${base}/publishing/package?book_id=${r.book_id}`, `${r.title}.zip`).then(() => undefined))}>Paczki</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small muted" style={{ marginTop: ".6rem" }}>
            Najedź na status, żeby zobaczyć, co blokuje sklep. Statusy „Wysłane” i „W weryfikacji” system sam zmienia na „Opublikowane”, gdy strona w sklepie
            zaczyna odpowiadać (przycisk „Sprawdź statusy”). Sklepy, które blokują boty, pozostają do ręcznego potwierdzenia.
          </p>
        </div>
      )}
    </div>
  );
}
