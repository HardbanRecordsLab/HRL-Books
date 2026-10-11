import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useWorkspace } from "../App";
import { api } from "../lib/api";
import type { Product } from "./ProductsTab";

type Order = {
  id: string; product_title: string; quantity: number; status: string; status_label: string; amount: number;
  customer_name: string; customer_email: string; shipping: Record<string, string>; tracking: { code: string; url: string }[];
  error: string; created_at: string;
};

export default function Shop() {
  const { ws } = useParams();
  const workspace = useWorkspace();
  const [products, setProducts] = useState<Product[]>([]);
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [error, setError] = useState("");

  const load = () => {
    api<Product[]>(`/workspaces/${ws}/shop/products`).then(setProducts).catch((e) => setError(e.message));
    api<Order[]>(`/workspaces/${ws}/shop/orders`).then(setOrders).catch((e) => setError(e.message));
  };
  useEffect(load, [ws]);

  const retry = async (id: string) => {
    await api(`/workspaces/${ws}/shop/orders/${id}/retry`, { method: "POST" }).catch((e) => setError(e.message));
    load();
  };

  return (
    <div className="stack">
      <Link to={`/w/${ws}`} className="small">← {workspace?.name}</Link>
      <h1>Sklep i druk na żądanie</h1>
      {error && <div className="error">{error}</div>}
      <div className="card">
        <h3>Zamówienia</h3>
        {orders === null ? <div className="muted">Ładowanie…</div> : orders.length === 0 ? (
          <div className="empty">Jeszcze nie ma zamówień.</div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead><tr><th>Data</th><th>Produkt</th><th>Klient</th><th>Kwota</th><th>Status</th></tr></thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.id}>
                    <td className="small">{new Date(o.created_at).toLocaleString("pl-PL")}</td>
                    <td>{o.product_title} × {o.quantity}</td>
                    <td className="small">{o.customer_name || "—"}<div className="muted">{o.customer_email}{o.shipping?.city ? ` · ${o.shipping.city}` : ""}</div></td>
                    <td>{o.amount.toFixed(2)} zł</td>
                    <td className="small">
                      <span className={o.status === "failed" ? "error" : o.status === "delivered" ? "ok" : ""}>{o.status_label}</span>
                      {o.tracking.map((t) => <div key={t.code}><a href={t.url} target="_blank" rel="noopener noreferrer">śledź {t.code}</a></div>)}
                      {o.error && <div className="muted">{o.error.slice(0, 140)}</div>}
                      {o.status === "failed" && <button className="ghost small" onClick={() => retry(o.id)}>Ponów</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="card">
        <h3>Produkty</h3>
        {products.length === 0 ? <div className="muted small">Produkty dodajesz w karcie książki, w zakładce „Produkty i druk”.</div> : (
          <table>
            <tbody>
              {products.map((p) => (
                <tr key={p.id}>
                  <td><b>{p.title}</b><div className="muted small">{p.catalog_label}</div></td>
                  <td>{p.price.toFixed(2)} zł</td>
                  <td className="small">{p.active ? <a href={p.public_url} target="_blank" rel="noopener noreferrer">strona produktu ↗</a> : <span className="muted">wyłączony</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
