import { FormEvent, Suspense, lazy, useEffect, useState } from "react";

const ManuscriptTab = lazy(() => import("./ManuscriptTab"));
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useWorkspace } from "../App";
import { ApiError, api, Book, STATUS_LABELS } from "../lib/api";
import MetadataTab from "./MetadataTab";
import DistributionTab from "./DistributionTab";
import ProductsTab from "./ProductsTab";
import ResearchTab from "./ResearchTab";
import { AiTab, ChapterAi } from "./AiPanel";
import { BookRoyalties } from "./Royalties";


type StoreLink = { url: string; channel?: string };
type BookFull = Book & { store_links: StoreLink[]; public: boolean; slug: string };
type AssetRow = { id: string; kind: string; url: string; content_type: string };

const TABS = ["Przegląd", "Metadane", "Produkty i druk", "Dystrybucja", "Research", "Rękopis", "Asystent AI", "Tantiemy"] as const;

function channelOf(url: string) {
  const host = (() => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; } })();
  if (host.includes("amazon")) return "Amazon / KDP";
  if (host.includes("play.google")) return "Google Play";
  if (host.includes("kobo")) return "Kobo";
  if (host.includes("empik")) return "Empik";
  if (host.includes("legimi")) return "Legimi";
  if (host.includes("woblink")) return "Woblink";
  if (host.includes("virtualo")) return "Virtualo";
  if (host.includes("lulu")) return "Lulu";
  return host;
}

export default function BookDetail() {
  const { ws, id } = useParams();
  const workspace = useWorkspace();
  const navigate = useNavigate();
  const [book, setBook] = useState<BookFull | null>(null);
  const [params] = useSearchParams();
  const initialTab = (TABS as readonly string[]).includes(params.get("tab") || "") ? (params.get("tab") as (typeof TABS)[number]) : "Przegląd";
  const [tab, setTab] = useState<(typeof TABS)[number]>(initialTab);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [newLink, setNewLink] = useState("");
  const [cover, setCover] = useState<string>("");
  const [slugDraft, setSlugDraft] = useState("");

  useEffect(() => {
    api<BookFull>(`/workspaces/${ws}/books/${id}`).then((b) => { setBook(b); setSlugDraft(b.slug); }).catch((e) => setError(e.message));
    api<AssetRow[]>(`/workspaces/${ws}/assets?book_id=${id}`)
      .then((a) => setCover(a.find((x) => x.kind === "cover" && x.content_type.startsWith("image/"))?.url || "")).catch(() => {});
  }, [ws, id]);

  if (error && !book) return <div className="error">{error}</div>;
  if (!book) return <div className="muted">Ładowanie…</div>;
  const canEdit = ["owner", "editor", "author"].includes(workspace?.role || "");

  const save = async (e?: FormEvent, patch?: Partial<BookFull>) => {
    e?.preventDefault();
    setError("");
    setSaved("");
    try {
      const body = patch || {
        title: book.title, subtitle: book.subtitle, language: book.language, status: book.status,
        desc_short: book.desc_short,
      };
      const nb = await api<BookFull>(`/workspaces/${ws}/books/${id}`, { method: "PATCH", body });
      setBook(nb);
      setSlugDraft(nb.slug);
      setSaved("Zapisano.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Nie udało się zapisać.");
    }
  };

  const addLink = (e: FormEvent) => {
    e.preventDefault();
    if (!newLink.trim()) return;
    save(undefined, { store_links: [...book.store_links, { url: newLink.trim() }] });
    setNewLink("");
  };

  const uploadCover = async (f: File | undefined) => {
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f); fd.append("kind", "cover"); fd.append("book_id", id!);
    const r = await fetch(`/api/v1/workspaces/${ws}/assets`, { method: "POST", body: fd,
      headers: { Authorization: `Bearer ${localStorage.getItem("hrlb_access")}` } });
    const d = await r.json().catch(() => ({}));
    if (r.ok) setCover(d.url); else setError(typeof d.detail === "string" ? d.detail : "Nie udało się wgrać okładki.");
  };
  const publicUrl = `${window.location.origin}/ksiegarnia/${workspace?.slug}/${book.slug}`;

  const remove = async () => {
    if (!confirm(`Usunąć „${book.title}”? Przez 30 dni można go jeszcze przywrócić.`)) return;
    await api(`/workspaces/${ws}/books/${id}`, { method: "DELETE" });
    navigate(`/w/${ws}`);
  };

  return (
    <div className="stack">
      <Link to={`/w/${ws}`} className="small">← {workspace?.name}</Link>
      <div className="row spread">
        <h1>{book.title}</h1>
        <span className={`pill ${book.status}`}>{STATUS_LABELS[book.status]}</span>
      </div>
      <div className="tabs">
        {TABS.map((t) => (
          <button key={t} className={t === tab ? "on" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      {tab === "Przegląd" && (
        <div className="grid grid-2">
          <form className="card stack" onSubmit={save}>
            <h3>Podstawowe dane</h3>
            <label>Tytuł<input value={book.title} disabled={!canEdit} onChange={(e) => setBook({ ...book, title: e.target.value })} required /></label>
            <label>Podtytuł<input value={book.subtitle} disabled={!canEdit} onChange={(e) => setBook({ ...book, subtitle: e.target.value })} /></label>
            <div className="row">
              <label style={{ flex: 1 }}>Etap
                <select value={book.status} disabled={!canEdit} onChange={(e) => setBook({ ...book, status: e.target.value })}>
                  {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
              <label style={{ width: 110 }}>Język
                <select value={book.language} disabled={!canEdit} onChange={(e) => setBook({ ...book, language: e.target.value })}>
                  <option value="pl">PL</option><option value="en">EN</option><option value="de">DE</option>
                </select>
              </label>
            </div>
            <label>Krótki opis<textarea value={book.desc_short} disabled={!canEdit} onChange={(e) => setBook({ ...book, desc_short: e.target.value })} /></label>
            {canEdit && <div className="row"><button>Zapisz</button>{saved && <span className="ok">{saved}</span>}</div>}
            {error && <div className="error">{error}</div>}
          </form>

          <div className="card stack">
            <h3>Gdzie jest w sprzedaży</h3>
            {book.store_links.length === 0 ? (
              <p className="muted small">Brak linków do sklepów.</p>
            ) : (
              <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                {book.store_links.map((l, i) => (
                  <li key={i} className="row spread">
                    <a href={l.url} target="_blank" rel="noopener noreferrer">{l.channel || channelOf(l.url)}</a>
                    {canEdit && (
                      <button className="ghost small" type="button"
                        onClick={() => save(undefined, { store_links: book.store_links.filter((_, j) => j !== i) })}>usuń</button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {canEdit && (
              <form className="row" onSubmit={addLink}>
                <input style={{ flex: 1 }} type="url" placeholder="https://… link do sklepu" value={newLink} onChange={(e) => setNewLink(e.target.value)} />
                <button className="ghost">Dodaj</button>
              </form>
            )}
            {workspace?.role === "owner" && <button className="danger" type="button" onClick={remove}>Usuń tytuł</button>}
          </div>

          <div className="card stack">
            <h3>Okładka i strona publiczna</h3>
            <div className="row" style={{ alignItems: "flex-start" }}>
              {cover ? <img src={cover} alt={`Okładka: ${book.title}`} style={{ width: 110, aspectRatio: "2 / 3", objectFit: "cover", borderRadius: 6 }} />
                : <div className="muted small" style={{ width: 110, aspectRatio: "2 / 3", border: "1px dashed var(--line)", borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center" }}>brak okładki</div>}
              <div className="stack" style={{ flex: 1 }}>
                {canEdit && <label className="small">Wgraj okładkę (JPG/PNG, najlepiej 1600×2560 px)
                  <input type="file" accept="image/jpeg,image/png" onChange={(e) => uploadCover(e.target.files?.[0])} /></label>}
                <span className="muted small">Okładka trafia na stronę książki i do pliku EPUB.</span>
              </div>
            </div>
            {workspace?.role === "owner" ? (
              <>
                <label className="row" style={{ flexDirection: "row", color: "var(--text)" }}>
                  <input type="checkbox" checked={book.public} onChange={(e) => save(undefined, { public: e.target.checked })} />
                  Strona książki widoczna publicznie
                </label>
                {book.public && (
                  <>
                    <a href={publicUrl} target="_blank" rel="noopener noreferrer" className="small" style={{ wordBreak: "break-all" }}>{publicUrl}</a>
                    <div className="row">
                      <input style={{ flex: 1 }} value={slugDraft} onChange={(e) => setSlugDraft(e.target.value.toLowerCase())} aria-label="Adres strony" />
                      <button className="ghost" type="button" disabled={slugDraft === book.slug} onClick={() => save(undefined, { slug: slugDraft })}>Zmień adres</button>
                    </div>
                    <span className="muted small">Strona pokazuje opis, autorów, linki do sklepów, wydania i produkty z motywem książki. Katalog: <a href={`/ksiegarnia/${workspace?.slug}`} target="_blank" rel="noopener noreferrer">/ksiegarnia/{workspace?.slug}</a></span>
                  </>
                )}
              </>
            ) : book.public && <a href={publicUrl} target="_blank" rel="noopener noreferrer" className="small">Strona publiczna książki</a>}
          </div>
        </div>
      )}

      {tab === "Metadane" && (
        <MetadataTab base={`/workspaces/${ws}/books/${id}`} canEdit={["owner", "editor"].includes(workspace?.role || "")} />
      )}

      {tab === "Dystrybucja" && (
        <DistributionTab
          base={`/workspaces/${ws}/books/${id}`}
          canManage={workspace?.role === "owner"}
          onPublished={() => {
            if (book.status !== "published" && confirm("Książka jest już w sprzedaży. Zmienić jej etap na „Opublikowana”?")) {
              save(undefined, { status: "published" });
            }
          }}
        />
      )}

      {tab === "Produkty i druk" && (
        <ProductsTab ws={ws!} bookId={id!} bookTitle={book.title} canManage={workspace?.role === "owner"} />
      )}

      {tab === "Research" && (
        <ResearchTab base={`/workspaces/${ws}/books/${id}`} canEdit={["owner", "author"].includes(workspace?.role || "")} />
      )}

      {tab === "Rękopis" && (
        <Suspense fallback={<div className="muted">Ładowanie edytora…</div>}>
          <ManuscriptTab base={`/workspaces/${ws}/books/${id}`} canEdit={["owner", "editor", "author"].includes(workspace?.role || "")}
            aiSlot={["owner", "editor", "author"].includes(workspace?.role || "") ? (ch, reload, dirty) => (
              <ChapterAi base={`/workspaces/${ws}/books/${id}`} chapter={ch} dirty={dirty} reload={reload} enabled={!!workspace?.ai_enabled} ws={ws!} />
            ) : undefined} />
        </Suspense>
      )}

      {tab === "Asystent AI" && (
        <AiTab base={`/workspaces/${ws}/books/${id}`} ws={ws!} canUse={["owner", "editor", "author"].includes(workspace?.role || "")} />
      )}

      {tab === "Tantiemy" && <BookRoyalties ws={ws!} bookId={id!} isOwner={workspace?.role === "owner"} />}

    </div>
  );
}
