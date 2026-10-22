import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { setSeo } from "../lib/seo";
import HrlLangSwitch from "../lib/hrl/HrlLangSwitch";

type Card = { slug: string; title: string; subtitle: string; desc_short: string; cover_url: string; authors: string[];
  series: string; series_volume: number | null };
type Catalog = { name: string; slug: string; books: Card[] };
type Page = Card & {
  publisher: string; url: string; language: string; desc_long: string; authors_bio: { name: string; bio: string }[];
  contributors: { name: string; role: string }[]; editions: { format: string; release_date: string; isbn: string; pages: number | null }[];
  stores: { url: string; label: string }[]; products: { id: string; title: string; catalog_label: string; design_url: string; price: number }[];
  more: Card[];
};

function Shell({ ws, name, children }: { ws?: string; name?: string; children: React.ReactNode }) {
  return (
    <div style={{ maxWidth: 1040, margin: "0 auto", padding: "1.2rem 1rem 3rem" }}>
      <header className="row spread" style={{ marginBottom: "1.5rem" }}>
        <Link to={ws ? `/ksiegarnia/${ws}` : "/"} style={{ textDecoration: "none" }}>
          <div className="brand">{name || <>HRL <span>Books</span></>}</div>
        </Link>
        <div className="row" style={{ gap: "0.8rem" }}>
          <HrlLangSwitch />
          {ws && <Link className="small" to={`/ksiegarnia/${ws}`}>Wszystkie książki</Link>}
        </div>
      </header>
      {children}
      <footer className="muted small" style={{ marginTop: "3rem", borderTop: "1px solid var(--line)", paddingTop: "1rem" }}>
        Działa na HRL Books ·{" "}
        <a href="https://hardbanrecordslab.online/terms/" target="_blank" rel="noopener noreferrer">Regulamin</a> ·{" "}
        <a href="https://hardbanrecordslab.online/privacy/" target="_blank" rel="noopener noreferrer">Polityka prywatności</a>
      </footer>
    </div>
  );
}

function Cover({ b, width }: { b: Card; width: number }) {
  return b.cover_url ? (
    <img src={b.cover_url} alt={`Okładka: ${b.title}`} style={{ width, aspectRatio: "2 / 3", objectFit: "cover", borderRadius: 6, boxShadow: "0 8px 24px rgba(0,0,0,.35)" }} />
  ) : (
    <div style={{ width, aspectRatio: "2 / 3", borderRadius: 6, background: "linear-gradient(160deg, #2a2f45, #14161f)", display: "flex",
      alignItems: "center", justifyContent: "center", padding: "1rem", textAlign: "center", fontFamily: "Georgia, serif", color: "var(--gold-2)" }}>
      {b.title}
    </div>
  );
}

function Grid({ ws, books }: { ws: string; books: Card[] }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "1.5rem" }}>
      {books.map((b) => (
        <Link key={b.slug} to={`/ksiegarnia/${ws}/${b.slug}`} className="stack" style={{ gap: ".4rem", color: "var(--text)", textDecoration: "none" }}>
          <Cover b={b} width={160} />
          <b>{b.title}</b>
          {b.authors.length > 0 && <span className="muted small">{b.authors.join(", ")}</span>}
        </Link>
      ))}
    </div>
  );
}

export function BookshopPage() {
  const { ws } = useParams();
  const [c, setC] = useState<Catalog | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Catalog>(`/public/w/${ws}`).then(setC).catch((e) => setError(e.message));
  }, [ws]);
  useEffect(() => {
    if (!c) return;
    return setSeo({
      title: `${c.name} — księgarnia: książki i e-booki`,
      description: `Księgarnia ${c.name}: ${c.books.length} ${c.books.length === 1 ? "tytuł" : "tytuły i książki"} do przeczytania i zakupu. Opisy, okładki i linki do sklepów.`,
      canonical: `${window.location.origin}/ksiegarnia/${c.slug}`,
    });
  }, [c]);
  if (!c) return <Shell>{error ? <div className="error">{error}</div> : <span className="muted">Ładowanie…</span>}</Shell>;
  return (
    <Shell ws={c.slug} name={c.name}>
      <h1>Książki</h1>
      {c.books.length === 0 ? <p className="muted">Wkrótce pojawią się tu nasze tytuły.</p> : <Grid ws={c.slug} books={c.books} />}
    </Shell>
  );
}

export function PublicBookPage() {
  const { ws, slug } = useParams();
  const [b, setB] = useState<Page | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setB(null);
    api<Page>(`/public/w/${ws}/${slug}`).then(setB).catch((e) => setError(e.message));
  }, [ws, slug]);
  useEffect(() => {
    if (!b) return;
    const isbn = b.editions.find((e) => e.isbn)?.isbn;
    const release = b.editions.map((e) => e.release_date).filter(Boolean).sort()[0];
    return setSeo({
      title: `${b.title}${b.authors.length ? ` — ${b.authors.join(", ")}` : ""} | ${b.publisher}`,
      description: b.desc_short || b.subtitle || b.title,
      canonical: b.url,
      jsonLd: {
        "@context": "https://schema.org", "@type": "Book", name: b.title, url: b.url,
        ...(b.subtitle && { alternativeHeadline: b.subtitle }),
        ...(b.authors.length && { author: b.authors.map((name) => ({ "@type": "Person", name })) }),
        ...(b.desc_short && { description: b.desc_short }),
        ...(b.cover_url && { image: b.cover_url }),
        ...(b.language && { inLanguage: b.language }),
        ...(isbn && { isbn }), ...(release && { datePublished: release }),
        publisher: { "@type": "Organization", name: b.publisher },
      },
    });
  }, [b]);
  if (!b) return <Shell ws={ws}>{error ? <div className="error">{error === "Nie znaleziono" ? "Tej książki nie ma (albo nie jest jeszcze publiczna)." : error}</div> : <span className="muted">Ładowanie…</span>}</Shell>;

  const release = b.editions.map((e) => e.release_date).filter(Boolean).sort()[0];
  return (
    <Shell ws={ws} name={b.publisher}>
      <article className="stack" style={{ gap: "2rem" }}>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 260px) 1fr", gap: "2rem", alignItems: "start" }} className="book-hero">
          <Cover b={b} width={260} />
          <div className="stack">
            {b.series && <span className="muted small">{b.series}{b.series_volume ? `, tom ${b.series_volume}` : ""}</span>}
            <h1 style={{ margin: 0, fontFamily: "Georgia, serif" }}>{b.title}</h1>
            {b.subtitle && <div style={{ fontSize: "1.15rem" }}>{b.subtitle}</div>}
            {b.authors.length > 0 && <div className="muted">{b.authors.join(", ")}</div>}
            {b.desc_short && <p style={{ fontSize: "1.05rem" }}>{b.desc_short}</p>}
            {b.stores.length > 0 && (
              <div className="stack" style={{ gap: ".5rem" }}>
                <b>Kup lub czytaj</b>
                <div className="row" style={{ flexWrap: "wrap" }}>
                  {b.stores.map((s) => <a key={s.url} className="btn" href={s.url} target="_blank" rel="noopener noreferrer">{s.label}</a>)}
                </div>
              </div>
            )}
            <div className="muted small">
              {[...b.editions.map((e) => e.format), release && `premiera ${new Date(release).toLocaleDateString("pl-PL")}`,
                b.language && `język: ${b.language === "pl" ? "polski" : b.language === "en" ? "angielski" : b.language}`].filter(Boolean).join(" · ")}
            </div>
          </div>
        </div>

        {b.desc_long && <section className="stack"><h2>O książce</h2><div style={{ whiteSpace: "pre-line", lineHeight: 1.7 }}>{b.desc_long}</div></section>}

        {b.products.length > 0 && (
          <section className="stack">
            <h2>Z motywem książki</h2>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "1rem" }}>
              {b.products.map((p) => (
                <Link key={p.id} to={`/sklep/${p.id}`} className="card stack" style={{ gap: ".3rem", color: "var(--text)", textDecoration: "none" }}>
                  {p.design_url && <img src={p.design_url} alt={p.title} style={{ width: "100%", aspectRatio: "1", objectFit: "contain", background: "#fff", borderRadius: 6 }} />}
                  <b>{p.title}</b><span className="muted small">{p.catalog_label}</span><span>{p.price.toFixed(2)} zł</span>
                </Link>
              ))}
            </div>
          </section>
        )}

        {b.authors_bio.some((a) => a.bio) && (
          <section className="stack"><h2>{b.authors_bio.length > 1 ? "O autorach" : "O autorze"}</h2>
            {b.authors_bio.filter((a) => a.bio).map((a) => <div key={a.name}><b>{a.name}</b><p style={{ whiteSpace: "pre-line" }}>{a.bio}</p></div>)}
          </section>
        )}

        {(b.contributors.length > 0 || b.editions.some((e) => e.isbn)) && (
          <section className="muted small stack" style={{ gap: ".2rem" }}>
            {b.contributors.map((c) => <span key={c.name + c.role}>{c.role}: {c.name}</span>)}
            {b.editions.filter((e) => e.isbn).map((e) => <span key={e.isbn}>ISBN {e.isbn} ({e.format})</span>)}
            <span>Wydawca: {b.publisher}</span>
          </section>
        )}

        {b.more.length > 0 && <section className="stack"><h2>Inne książki</h2><Grid ws={ws!} books={b.more} /></section>}
      </article>
    </Shell>
  );
}
