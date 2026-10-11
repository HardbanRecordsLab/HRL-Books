import { FormEvent, useEffect, useState } from "react";
import { useSession } from "../App";
import { ApiError, api, Workspace } from "../lib/api";

type AdminWs = Workspace & { titles: number };

export default function Admin() {
  const { reload } = useSession();
  const [list, setList] = useState<AdminWs[]>([]);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [owner, setOwner] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const load = () => api<AdminWs[]>("/admin/workspaces").then(setList).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setMsg("");
    try {
      await api("/admin/workspaces", { method: "POST", body: { name, slug, owner_email: owner } });
      setMsg(`Utworzono „${name}”. Zaproszenie dla właściciela wysłane na ${owner}.`);
      setName(""); setSlug(""); setOwner("");
      load();
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Nie udało się utworzyć przestrzeni.");
    }
  };

  const autoSlug = (v: string) =>
    v.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ł/g, "l").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 80);

  return (
    <div className="stack">
      <h1>Administracja</h1>
      <div className="grid grid-2">
        <div className="card">
          <h3>Przestrzenie (wydawnictwa i autorzy)</h3>
          <table>
            <thead><tr><th>Nazwa</th><th>Tytuły</th><th>Status</th></tr></thead>
            <tbody>
              {list.map((w) => (
                <tr key={w.id}><td>{w.name}<div className="muted small">{w.slug}</div></td><td>{w.titles}</td><td>{w.status}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <form className="card stack" onSubmit={create}>
          <h3>Nowa przestrzeń</h3>
          <label>Nazwa<input value={name} onChange={(e) => { setName(e.target.value); setSlug(autoSlug(e.target.value)); }} required /></label>
          <label>Adres (slug)<input value={slug} onChange={(e) => setSlug(e.target.value)} pattern="[a-z0-9-]{2,80}" required /></label>
          <label>E-mail właściciela<input type="email" value={owner} onChange={(e) => setOwner(e.target.value)} required /></label>
          <button>Utwórz i zaproś</button>
          {msg && <div className="ok">{msg}</div>}
          {error && <div className="error">{error}</div>}
        </form>
      </div>
    </div>
  );
}
