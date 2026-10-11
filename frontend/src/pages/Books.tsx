import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useWorkspace } from "../App";
import { ApiError, api, Book, ROLE_LABELS, STATUS_LABELS } from "../lib/api";

const CAN_CREATE = ["owner", "author"];

// Import format, one book per line:  Tytuł | Podtytuł | link do sklepu | link do sklepu …
function parseImport(text: string) {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      const [title, subtitle = "", ...links] = line.split("|").map((s) => s.trim());
      return {
        title,
        subtitle,
        status: "published",
        store_links: links.filter(Boolean).map((url) => ({ url })),
      };
    });
}

export default function Books() {
  const { ws } = useParams();
  const workspace = useWorkspace();
  const navigate = useNavigate();
  const [books, setBooks] = useState<Book[] | null>(null);
  const [mode, setMode] = useState<"" | "new" | "import">("");
  const [title, setTitle] = useState("");
  const [importText, setImportText] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const load = () => api<Book[]>(`/workspaces/${ws}/books`).then(setBooks).catch((e) => setError(e.message));
  useEffect(() => {
    setBooks(null);
    load();
  }, [ws]);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const b = await api<Book>(`/workspaces/${ws}/books`, { method: "POST", body: { title } });
      navigate(`/w/${ws}/ksiazki/${b.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Nie udało się dodać tytułu.");
    }
  };

  const runImport = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setMsg("");
    const items = parseImport(importText);
    if (!items.length) return setError("Wklej co najmniej jeden tytuł.");
    try {
      const r = await api<{ imported: number }>(`/workspaces/${ws}/books/import`, { method: "POST", body: { books: items } });
      setMsg(`Zaimportowano: ${r.imported}.`);
      setImportText("");
      setMode("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Import się nie udał.");
    }
  };

  if (!workspace) return <div className="error">Nie znaleziono przestrzeni.</div>;
  const canCreate = CAN_CREATE.includes(workspace.role || "");

  return (
    <div className="stack">
      <div className="row spread">
        <div>
          <h1>{workspace.name}</h1>
          <span className="muted small">Twoja rola: {ROLE_LABELS[workspace.role || ""] || workspace.role}</span>
        </div>
        <div className="row">
          {canCreate && <button onClick={() => setMode(mode === "new" ? "" : "new")}>Nowy tytuł</button>}
          {canCreate && <button className="ghost" onClick={() => setMode(mode === "import" ? "" : "import")}>Import wydanych</button>}
          {workspace.role !== "reviewer" && <Link className="btn ghost" to={`/w/${ws}/dystrybucja`}>Dystrybucja</Link>}
          {workspace.role === "owner" && <Link className="btn ghost" to={`/w/${ws}/sklep`}>Sklep</Link>}
          {workspace.role === "owner" && <Link className="btn ghost" to={`/w/${ws}/tantiemy`}>Tantiemy</Link>}
          {workspace.role === "owner" && <Link className="btn ghost" to={`/w/${ws}/ustawienia`}>Ustawienia</Link>}
        </div>
      </div>

      {mode === "new" && (
        <form className="card row" onSubmit={create}>
          <input style={{ flex: 1 }} placeholder="Tytuł książki" value={title} onChange={(e) => setTitle(e.target.value)} required autoFocus />
          <button>Dodaj</button>
        </form>
      )}
      {mode === "import" && (
        <form className="card stack" onSubmit={runImport}>
          <h3>Import już wydanych książek</h3>
          <p className="muted small">
            Jedna książka w linii: <code>Tytuł | Podtytuł | link do sklepu | kolejny link…</code>. Książki trafią do etapu
            „Opublikowana”, a linki do sklepów zapiszą się w karcie.
          </p>
          <textarea rows={6} value={importText} onChange={(e) => setImportText(e.target.value)}
            placeholder={"Rodzic bez poczucia winy | Poradnik | https://www.amazon.pl/dp/...\nCyfrowy Zen | 21 dni do suwerenności cyfrowej"} />
          <div className="row"><button>Importuj</button><span className="muted small">{parseImport(importText).length} pozycji</span></div>
        </form>
      )}
      {error && <div className="error">{error}</div>}
      {msg && <div className="ok">{msg}</div>}

      <div className="card">
        {books === null ? (
          <div className="muted">Ładowanie…</div>
        ) : books.length === 0 ? (
          <div className="empty">Brak tytułów. Dodaj pierwszy albo zaimportuj już wydane.</div>
        ) : (
          <table>
            <thead><tr><th>Tytuł</th><th>Etap</th><th>Język</th><th>Dodano</th></tr></thead>
            <tbody>
              {books.map((b) => (
                <tr key={b.id} className="click" onClick={() => navigate(`/w/${ws}/ksiazki/${b.id}`)}>
                  <td><b>{b.title}</b>{b.subtitle && <div className="muted small">{b.subtitle}</div>}</td>
                  <td><span className={`pill ${b.status}`}>{STATUS_LABELS[b.status] || b.status}</span></td>
                  <td>{b.language.toUpperCase()}</td>
                  <td className="muted small">{new Date(b.created_at).toLocaleDateString("pl-PL")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
