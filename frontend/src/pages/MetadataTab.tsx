import { FormEvent, useEffect, useState } from "react";
import { ApiError, api } from "../lib/api";

type Contributor = { person_id: string; display_name: string; role: string; position: number };
type Metadata = {
  desc_long: string; keywords: string[]; categories: string[]; audience: string; series_name: string;
  series_volume: number | null; copyright_holder: string; copyright_year: number | null; territories: string;
  ai_disclosure: { text?: boolean; images?: boolean; translation?: boolean }; contributors: Contributor[];
};
type Person = { id: string; display_name: string; bio_short: string; bio_long: string };
type Price = { market: string; currency: string; amount: number };
type Edition = { id: string; format: string; isbn: string; release_date: string; pages: number | null; drm: boolean; prices: Price[] };
type Checks = { complete: boolean; missing: { field: string; label: string }[]; warnings: string[] };

export const CONTRIBUTOR_ROLES: Record<string, string> = {
  author: "autor", editor: "redaktor", translator: "tłumacz", cover_designer: "projekt okładki",
  illustrator: "ilustrator", narrator: "lektor",
};
const FORMATS: Record<string, string> = {
  ebook_epub: "E-book (EPUB)", ebook_pdf: "E-book (PDF)", paperback: "Miękka oprawa", hardcover: "Twarda oprawa", audiobook: "Audiobook",
};

export default function MetadataTab({ base, canEdit }: { base: string; canEdit: boolean }) {
  const [meta, setMeta] = useState<Metadata | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [editions, setEditions] = useState<Edition[]>([]);
  const [checks, setChecks] = useState<Checks | null>(null);
  const [kw, setKw] = useState("");
  const [cats, setCats] = useState("");
  const [addPerson, setAddPerson] = useState({ person_id: "", role: "author", newName: "" });
  const [newEd, setNewEd] = useState({ format: "ebook_epub", isbn: "", release_date: "", pages: "", price: "" });
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const ws = base.split("/books/")[0];
  const loadChecks = () => api<Checks>(`${base}/checks`).then(setChecks);
  const load = async () => {
    const [m, p, e] = await Promise.all([
      api<Metadata>(`${base}/metadata`), api<Person[]>(`${ws}/people`), api<Edition[]>(`${base}/editions`),
    ]);
    setMeta(m); setPeople(p); setEditions(e);
    setKw(m.keywords.join(", ")); setCats(m.categories.join("\n"));
    loadChecks();
  };
  useEffect(() => {
    load().catch((e) => setError(e.message));
  }, [base]);

  if (!meta) return <div className="muted">{error || "Ładowanie…"}</div>;

  const fail = (err: unknown) => setError(err instanceof ApiError ? err.message : "Coś poszło nie tak.");

  const save = async (e?: FormEvent, contributors?: { person_id: string; role: string }[]) => {
    e?.preventDefault();
    setError(""); setMsg("");
    try {
      const body = {
        desc_long: meta.desc_long, audience: meta.audience, series_name: meta.series_name,
        series_volume: meta.series_volume || null, copyright_holder: meta.copyright_holder,
        copyright_year: meta.copyright_year || null, territories: meta.territories, ai_disclosure: meta.ai_disclosure,
        keywords: kw.split(",").map((s) => s.trim()).filter(Boolean),
        categories: cats.split("\n").map((s) => s.trim()).filter(Boolean),
        ...(contributors ? { contributors } : {}),
      };
      const m = await api<Metadata>(`${base}/metadata`, { method: "PUT", body });
      setMeta(m);
      setMsg("Zapisano.");
      loadChecks();
    } catch (err) { fail(err); }
  };

  const addContributor = async (e: FormEvent) => {
    e.preventDefault();
    try {
      let pid = addPerson.person_id;
      if (!pid && addPerson.newName.trim()) {
        const p = await api<Person>(`${ws}/people`, { method: "POST", body: { display_name: addPerson.newName.trim() } });
        setPeople([...people, p]);
        pid = p.id;
      }
      if (!pid) return;
      const list = meta.contributors.map((c) => ({ person_id: c.person_id, role: c.role }));
      await save(undefined, [...list, { person_id: pid, role: addPerson.role }]);
      setAddPerson({ person_id: "", role: "author", newName: "" });
    } catch (err) { fail(err); }
  };

  const removeContributor = (i: number) =>
    save(undefined, meta.contributors.filter((_, j) => j !== i).map((c) => ({ person_id: c.person_id, role: c.role })));

  const addEdition = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const body = {
        format: newEd.format, isbn: newEd.isbn.trim(), release_date: newEd.release_date,
        pages: newEd.pages ? Number(newEd.pages) : null,
        prices: newEd.price ? [{ market: "PL", currency: "PLN", amount: Number(newEd.price.replace(",", ".")) }] : [],
      };
      const ed = await api<Edition>(`${base}/editions`, { method: "POST", body });
      setEditions([...editions, ed]);
      setNewEd({ format: "ebook_epub", isbn: "", release_date: "", pages: "", price: "" });
      loadChecks();
    } catch (err) { fail(err); }
  };

  const removeEdition = async (id: string) => {
    if (!confirm("Usunąć to wydanie?")) return;
    await api(`${base}/editions/${id}`, { method: "DELETE" });
    setEditions(editions.filter((e) => e.id !== id));
    loadChecks();
  };

  const set = (patch: Partial<Metadata>) => setMeta({ ...meta, ...patch });

  return (
    <div className="stack">
      {checks && (
        <div className="card">
          {checks.complete ? (
            <span className="ok">Karta kompletna — gotowa do przygotowania wydania.</span>
          ) : (
            <div className="stack small">
              {checks.missing.length > 0 && <div>Brakuje: <b>{checks.missing.map((m) => m.label).join(", ")}</b></div>}
              {checks.warnings.map((w) => <div key={w} className="error">{w}</div>)}
            </div>
          )}
        </div>
      )}

      <div className="grid grid-2">
        <form className="card stack" onSubmit={save}>
          <h3>Dane do sklepów</h3>
          <label>Długi opis<textarea rows={7} value={meta.desc_long} disabled={!canEdit} onChange={(e) => set({ desc_long: e.target.value })} /></label>
          <label>Słowa kluczowe (po przecinku, min. 3)<input value={kw} disabled={!canEdit} onChange={(e) => setKw(e.target.value)} /></label>
          <label>Kategorie (każda w osobnej linii)<textarea rows={3} value={cats} disabled={!canEdit} onChange={(e) => setCats(e.target.value)} /></label>
          <label>Odbiorcy<input value={meta.audience} disabled={!canEdit} onChange={(e) => set({ audience: e.target.value })} placeholder="np. rodzice dzieci 3–10 lat" /></label>
          <div className="row">
            <label style={{ flex: 1 }}>Seria<input value={meta.series_name} disabled={!canEdit} onChange={(e) => set({ series_name: e.target.value })} /></label>
            <label style={{ width: 90 }}>Tom<input type="number" min={1} value={meta.series_volume ?? ""} disabled={!canEdit} onChange={(e) => set({ series_volume: e.target.value ? Number(e.target.value) : null })} /></label>
          </div>
          <div className="row">
            <label style={{ flex: 1 }}>Prawa autorskie — właściciel<input value={meta.copyright_holder} disabled={!canEdit} onChange={(e) => set({ copyright_holder: e.target.value })} /></label>
            <label style={{ width: 100 }}>Rok<input type="number" value={meta.copyright_year ?? ""} disabled={!canEdit} onChange={(e) => set({ copyright_year: e.target.value ? Number(e.target.value) : null })} /></label>
          </div>
          <label>Terytoria sprzedaży<input value={meta.territories} disabled={!canEdit} onChange={(e) => set({ territories: e.target.value })} /></label>
          <fieldset className="stack" style={{ border: "1px solid var(--line)", borderRadius: 8, padding: ".6rem .8rem" }}>
            <legend className="small muted">Treści wygenerowane przez AI (deklaracja dla KDP)</legend>
            {(["text", "images", "translation"] as const).map((k) => (
              <label key={k} className="row" style={{ flexDirection: "row", color: "var(--text)" }}>
                <input type="checkbox" disabled={!canEdit} checked={!!meta.ai_disclosure[k]}
                  onChange={(e) => set({ ai_disclosure: { ...meta.ai_disclosure, [k]: e.target.checked } })} />
                {k === "text" ? "tekst" : k === "images" ? "obrazy (w tym okładka)" : "tłumaczenie"}
              </label>
            ))}
          </fieldset>
          {canEdit && <div className="row"><button>Zapisz</button>{msg && <span className="ok">{msg}</span>}</div>}
          {error && <div className="error">{error}</div>}
        </form>

        <div className="stack">
          <div className="card stack">
            <h3>Twórcy</h3>
            {meta.contributors.length === 0 && <p className="muted small">Brak — dodaj co najmniej autora.</p>}
            {meta.contributors.map((c, i) => (
              <div key={`${c.person_id}-${c.role}`} className="row spread">
                <span>{c.display_name} <span className="muted small">— {CONTRIBUTOR_ROLES[c.role]}</span></span>
                {canEdit && <button className="ghost small" onClick={() => removeContributor(i)}>usuń</button>}
              </div>
            ))}
            {canEdit && (
              <form className="stack" onSubmit={addContributor}>
                <div className="row">
                  <select style={{ flex: 1 }} value={addPerson.person_id} onChange={(e) => setAddPerson({ ...addPerson, person_id: e.target.value })}>
                    <option value="">— nowa osoba —</option>
                    {people.map((p) => <option key={p.id} value={p.id}>{p.display_name}</option>)}
                  </select>
                  <select value={addPerson.role} onChange={(e) => setAddPerson({ ...addPerson, role: e.target.value })}>
                    {Object.entries(CONTRIBUTOR_ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </div>
                {!addPerson.person_id && (
                  <input placeholder="Imię i nazwisko nowej osoby" value={addPerson.newName} onChange={(e) => setAddPerson({ ...addPerson, newName: e.target.value })} />
                )}
                <button className="ghost">Dodaj twórcę</button>
              </form>
            )}
          </div>

          <div className="card stack">
            <h3>Wydania</h3>
            {editions.length === 0 && <p className="muted small">Brak wydań.</p>}
            {editions.map((e) => (
              <div key={e.id} className="row spread">
                <span>
                  <b>{FORMATS[e.format]}</b>
                  <span className="muted small">
                    {e.prices.map((p) => ` · ${p.amount.toFixed(2)} ${p.currency}`).join("")}
                    {e.isbn ? ` · ISBN ${e.isbn}` : ""}{e.release_date ? ` · premiera ${e.release_date}` : ""}
                  </span>
                </span>
                {canEdit && <button className="ghost small" onClick={() => removeEdition(e.id)}>usuń</button>}
              </div>
            ))}
            {canEdit && (
              <form className="stack" onSubmit={addEdition}>
                <div className="row">
                  <select style={{ flex: 1 }} value={newEd.format} onChange={(e) => setNewEd({ ...newEd, format: e.target.value })}>
                    {Object.entries(FORMATS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                  <input style={{ width: 110 }} placeholder="cena PLN" inputMode="decimal" value={newEd.price} onChange={(e) => setNewEd({ ...newEd, price: e.target.value })} />
                </div>
                <div className="row">
                  <input style={{ flex: 1 }} type="date" value={newEd.release_date} onChange={(e) => setNewEd({ ...newEd, release_date: e.target.value })} />
                  <input style={{ width: 90 }} placeholder="stron" inputMode="numeric" value={newEd.pages} onChange={(e) => setNewEd({ ...newEd, pages: e.target.value })} />
                </div>
                <input placeholder="ISBN (opcjonalnie — po nadaniu numerów)" value={newEd.isbn} onChange={(e) => setNewEd({ ...newEd, isbn: e.target.value })} />
                <button className="ghost">Dodaj wydanie</button>
              </form>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
