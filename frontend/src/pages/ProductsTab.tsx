import { FormEvent, useEffect, useState } from "react";
import { ApiError, api } from "../lib/api";

type Catalog = { uid: string; label: string; singular: string };
type GelatoProduct = { productUid: string; attributes: Record<string, string> };
type Asset = { id: string; url: string; original_name: string; content_type: string };
type Quote = { product: number; shipping: number; shipping_method: string; delivery_days: (number | null)[] };
export type Product = {
  id: string; title: string; description: string; catalog_label: string; gelato_catalog: string; gelato_product_uid: string;
  design_asset_id: string; design_url: string; price: number; currency: string; active: boolean; public_url: string; book_id: string | null;
};

const ATTR_LABELS: Record<string, string> = {
  GarmentColor: "kolor", GarmentSize: "rozmiar", MugSize: "rozmiar", MugMaterial: "materiał", PaperFormat: "format",
  PaperType: "papier", Orientation: "orientacja", ColorType: "druk", FrameColor: "rama", CoverFinish: "okładka",
};

function describe(p: GelatoProduct) {
  return Object.entries(p.attributes).map(([k, v]) => `${ATTR_LABELS[k] || k}: ${v}`).join(" · ");
}

async function uploadFile(ws: string, file: File, bookId: string): Promise<Asset> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("kind", "design");
  if (bookId) fd.append("book_id", bookId);
  const r = await fetch(`/api/v1/workspaces/${ws}/assets`, {
    method: "POST", body: fd, headers: { Authorization: `Bearer ${localStorage.getItem("hrlb_access")}` },
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Nie udało się wgrać pliku.");
  return data;
}

export default function ProductsTab({ ws, bookId, bookTitle, canManage }: { ws: string; bookId: string; bookTitle: string; canManage: boolean }) {
  const [products, setProducts] = useState<Product[]>([]);
  const [catalogs, setCatalogs] = useState<Catalog[]>([]);
  const [creating, setCreating] = useState(false);
  const [catalog, setCatalog] = useState("");
  const [options, setOptions] = useState<GelatoProduct[]>([]);
  const [filter, setFilter] = useState("");
  const [uid, setUid] = useState("");
  const [asset, setAsset] = useState<Asset | null>(null);
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [price, setPrice] = useState("");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const load = () => api<Product[]>(`/workspaces/${ws}/shop/products?book_id=${bookId}`).then(setProducts).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    if (canManage) api<Catalog[]>(`/workspaces/${ws}/shop/catalogs`).then(setCatalogs).catch(() => undefined);
  }, [ws, bookId]);

  useEffect(() => {
    setOptions([]); setUid(""); setQuote(null);
    if (!catalog) return;
    setBusy("Pobieram produkty z Gelato…");
    api<GelatoProduct[]>(`/workspaces/${ws}/shop/catalogs/${catalog}/products`)
      .then(setOptions).catch((e) => setError(e.message)).finally(() => setBusy(""));
    const name = catalogs.find((c) => c.uid === catalog)?.singular || "";
    if (!title) setTitle(`${name} — ${bookTitle}`.slice(0, 120));
  }, [catalog]);

  useEffect(() => {
    setQuote(null);
    if (!uid || !asset) return;
    setBusy("Liczę koszt druku i wysyłki…");
    api<Quote>(`/workspaces/${ws}/shop/quote?product_uid=${encodeURIComponent(uid)}&asset_id=${asset.id}`)
      .then((q) => { setQuote(q); if (!price) setPrice(String(Math.ceil((q.product + q.shipping) * 1.6))); })
      .catch((e) => setError(e.message)).finally(() => setBusy(""));
  }, [uid, asset]);

  const onFile = async (f: File | undefined) => {
    if (!f) return;
    setError(""); setBusy("Wgrywam projekt…");
    try { setAsset(await uploadFile(ws, f, bookId)); } catch (e) { setError((e as Error).message); } finally { setBusy(""); }
  };

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (!asset || !uid) return setError("Wybierz produkt i wgraj projekt.");
    setError("");
    try {
      await api(`/workspaces/${ws}/shop/products`, { method: "POST", body: {
        title, description: desc, gelato_catalog: catalog, gelato_product_uid: uid, design_asset_id: asset.id,
        price: Number(price.replace(",", ".")), book_id: bookId,
      } });
      setCreating(false); setCatalog(""); setAsset(null); setTitle(""); setDesc(""); setPrice(""); setQuote(null);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Nie udało się zapisać produktu.");
    }
  };

  const toggle = async (p: Product) => {
    await api(`/workspaces/${ws}/shop/products/${p.id}`, { method: "PUT", body: {
      title: p.title, description: p.description, gelato_catalog: p.gelato_catalog, gelato_product_uid: p.gelato_product_uid,
      design_asset_id: p.design_asset_id, price: p.price, book_id: p.book_id, active: !p.active,
    } });
    load();
  };

  const cost = quote ? quote.product + quote.shipping : 0;
  const margin = quote && price ? Number(price.replace(",", ".")) - cost : null;
  const shown = options.filter((o) => !filter || describe(o).toLowerCase().includes(filter.toLowerCase())).slice(0, 80);

  return (
    <div className="stack">
      <div className="card stack">
        <div className="row spread">
          <h3 style={{ margin: 0 }}>Produkty z druku na żądanie</h3>
          {canManage && !creating && <button onClick={() => setCreating(true)}>Nowy produkt</button>}
        </div>
        <p className="muted small">
          Koszulki, kubki, plakaty, notesy, kalendarze i inne z motywem książki. Drukuje Gelato dopiero po zakupie —
          płacisz tylko za sprzedane sztuki. Klient płaci przez Stripe, a zamówienie samo trafia do druku.
        </p>
        {products.length === 0 && !creating && <div className="muted small">Brak produktów dla tej książki.</div>}
        {products.map((p) => (
          <div key={p.id} className="row spread" style={{ borderTop: "1px solid var(--line)", paddingTop: ".6rem" }}>
            <div className="row">
              {p.design_url && <img src={p.design_url} alt="" style={{ width: 48, height: 48, objectFit: "cover", borderRadius: 6 }} />}
              <div>
                <b>{p.title}</b> <span className="muted small">· {p.catalog_label} · {p.price.toFixed(2)} zł</span>
                <div className="small"><a href={p.public_url} target="_blank" rel="noopener noreferrer">Strona produktu ↗</a>
                  {!p.active && <span className="muted"> · wyłączony</span>}</div>
              </div>
            </div>
            {canManage && <button className="ghost small" onClick={() => toggle(p)}>{p.active ? "Wyłącz" : "Włącz"}</button>}
          </div>
        ))}
      </div>

      {creating && (
        <form className="card stack" onSubmit={create}>
          <h3>Nowy produkt</h3>
          <label>1. Rodzaj
            <select value={catalog} onChange={(e) => setCatalog(e.target.value)} required>
              <option value="">— wybierz —</option>
              {catalogs.map((c) => <option key={c.uid} value={c.uid}>{c.label}</option>)}
            </select>
          </label>
          {options.length > 0 && (
            <label>2. Wariant ({options.length} dostępnych)
              <input placeholder="Filtruj, np. white, A3, 11-oz" value={filter} onChange={(e) => setFilter(e.target.value)} />
              <select size={6} value={uid} onChange={(e) => setUid(e.target.value)} required>
                {shown.map((o) => <option key={o.productUid} value={o.productUid}>{describe(o) || o.productUid}</option>)}
              </select>
            </label>
          )}
          <label>3. Projekt do druku (PNG, JPG lub PDF w wysokiej rozdzielczości)
            <input type="file" accept="image/png,image/jpeg,application/pdf" onChange={(e) => onFile(e.target.files?.[0])} />
          </label>
          {asset && asset.content_type.startsWith("image/") && <img src={asset.url} alt="" style={{ maxWidth: 220, borderRadius: 8 }} />}
          <label>Nazwa w sklepie<input value={title} onChange={(e) => setTitle(e.target.value)} required /></label>
          <label>Opis<textarea value={desc} onChange={(e) => setDesc(e.target.value)} /></label>
          <label>Cena dla klienta z wysyłką (zł)<input inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} required /></label>
          {quote && (
            <div className="card small" style={{ background: "var(--panel-2)" }}>
              Koszt Gelato: druk {quote.product.toFixed(2)} zł + wysyłka {quote.shipping.toFixed(2)} zł ({quote.shipping_method},{" "}
              {quote.delivery_days.join("–")} dni) = <b>{cost.toFixed(2)} zł</b>.
              {margin !== null && <> Zostaje Tobie przed opłatą Stripe: <b className={margin > 0 ? "ok" : "error"}>{margin.toFixed(2)} zł</b>.</>}
            </div>
          )}
          {busy && <div className="muted small">{busy}</div>}
          {error && <div className="error">{error}</div>}
          <div className="row">
            <button disabled={!uid || !asset}>Zapisz produkt</button>
            <button type="button" className="ghost" onClick={() => setCreating(false)}>Anuluj</button>
          </div>
        </form>
      )}
      {!creating && error && <div className="error">{error}</div>}
    </div>
  );
}
