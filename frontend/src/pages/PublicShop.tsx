import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../lib/api";

type PublicProduct = { id: string; title: string; description: string; catalog_label: string; design_url: string; price: number; book_title: string };
type PublicOrder = { status: string; status_label: string; product_title: string; quantity: number; amount: number; tracking: { code: string; url: string }[] };

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <div className="center">
      <div className="card stack" style={{ width: "100%", maxWidth: 560 }}>
        <div className="brand">HRL <span>Books</span></div>
        {children}
      </div>
    </div>
  );
}

export function PublicProductPage() {
  const { id } = useParams();
  const [p, setP] = useState<PublicProduct | null>(null);
  const [qty, setQty] = useState(1);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<PublicProduct>(`/public/products/${id}`).then(setP).catch((e) => setError(e.message));
  }, [id]);

  const buy = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api<{ url: string }>(`/public/products/${id}/checkout`, { method: "POST", body: { quantity: qty } });
      window.location.href = r.url;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Nie udało się przejść do płatności.");
      setBusy(false);
    }
  };

  if (!p) return <Frame>{error ? <div className="error">{error}</div> : <span className="muted">Ładowanie…</span>}</Frame>;
  return (
    <Frame>
      {p.design_url && <img src={p.design_url} alt={p.title} style={{ width: "100%", borderRadius: 8, background: "#fff" }} />}
      <h1>{p.title}</h1>
      <div className="muted small">{p.catalog_label}{p.book_title ? ` · z motywem książki „${p.book_title}”` : ""}</div>
      {p.description && <p style={{ whiteSpace: "pre-line" }}>{p.description}</p>}
      <div className="row spread">
        <b style={{ fontSize: "1.4rem" }}>{(p.price * qty).toFixed(2)} zł</b>
        <label className="row" style={{ flexDirection: "row" }}>Sztuk
          <input type="number" min={1} max={20} value={qty} style={{ width: 70 }} onChange={(e) => setQty(Math.max(1, Math.min(20, Number(e.target.value) || 1)))} />
        </label>
      </div>
      <p className="muted small">Cena z wysyłką. Produkt drukujemy na zamówienie — zwykle dociera w 5–10 dni roboczych.</p>
      <button onClick={buy} disabled={busy}>{busy ? "Przekierowanie do płatności…" : "Kup teraz"}</button>
      {error && <div className="error">{error}</div>}
      <p className="muted small">
        Płatność obsługuje Stripe. <a href="https://hardbanrecordslab.online/terms/" target="_blank" rel="noopener noreferrer">Regulamin</a> ·{" "}
        <a href="https://hardbanrecordslab.online/privacy/" target="_blank" rel="noopener noreferrer">Polityka prywatności</a>
      </p>
    </Frame>
  );
}

export function ThankYouPage() {
  const [params] = useSearchParams();
  const orderId = params.get("zamowienie") || "";
  const [o, setO] = useState<PublicOrder | null>(null);

  useEffect(() => {
    if (!orderId) return;
    const load = () => api<PublicOrder>(`/public/orders/${orderId}`).then(setO).catch(() => undefined);
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [orderId]);

  return (
    <Frame>
      <h1>Dziękujemy!</h1>
      {o ? (
        <>
          <p>{o.product_title} × {o.quantity} — {o.amount.toFixed(2)} zł</p>
          <p>Status: <b>{o.status_label}</b></p>
          {o.status === "pending_payment" && <p className="muted small">Czekamy na potwierdzenie płatności — strona odświeży się sama.</p>}
          {o.tracking.map((t) => <a key={t.code} href={t.url} target="_blank" rel="noopener noreferrer">Śledź przesyłkę {t.code}</a>)}
          <p className="muted small">Potwierdzenie wysłaliśmy też e-mailem.</p>
        </>
      ) : (
        <p className="muted">Twoje zamówienie przyjęte.</p>
      )}
    </Frame>
  );
}
