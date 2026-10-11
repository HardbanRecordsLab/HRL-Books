import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useSession, useWorkspace } from "../App";
import { ApiError, api, ROLE_LABELS, Workspace } from "../lib/api";

type Member = { user_id: string; email: string; display_name: string; role: string };
type Person = { id: string; display_name: string; bio_short: string; bio_long: string };
type Rule = { canonical: string; forbidden: string[] };

export default function Settings() {
  const { ws } = useParams();
  const workspace = useWorkspace();
  const { reload } = useSession();
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("author");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [people, setPeople] = useState<Person[]>([]);
  const [editing, setEditing] = useState<Person | null>(null);
  const [rules, setRules] = useState<string>("");

  useEffect(() => {
    api<Member[]>(`/workspaces/${ws}/members`).then(setMembers).catch((e) => setError(e.message));
    api<Person[]>(`/workspaces/${ws}/people`).then(setPeople).catch(() => undefined);
  }, [ws]);
  useEffect(() => {
    const r = ((workspace as unknown as { identity_rules?: Rule[] })?.identity_rules) || [];
    setRules(r.map((x) => `${x.canonical} | ${x.forbidden.join(", ")}`).join("\n"));
  }, [workspace]);

  const savePerson = async (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    try {
      const body = { display_name: editing.display_name, bio_short: editing.bio_short, bio_long: editing.bio_long };
      const saved = editing.id
        ? await api<Person>(`/workspaces/${ws}/people/${editing.id}`, { method: "PUT", body })
        : await api<Person>(`/workspaces/${ws}/people`, { method: "POST", body });
      setPeople(editing.id ? people.map((p) => (p.id === saved.id ? saved : p)) : [...people, saved]);
      setEditing(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Nie udało się zapisać osoby.");
    }
  };

  const saveRules = async (e: FormEvent) => {
    e.preventDefault();
    const identity_rules = rules.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
      const [canonical, rest = ""] = l.split("|").map((s) => s.trim());
      return { canonical, forbidden: rest.split(",").map((s) => s.trim()).filter(Boolean) };
    });
    await patch({ identity_rules } as unknown as Partial<Workspace>);
    setMsg("Reguły zapisane.");
  };

  if (!workspace) return null;

  const invite = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setMsg("");
    try {
      await api(`/workspaces/${ws}/invitations`, { method: "POST", body: { email, role } });
      setMsg(`Zaproszenie wysłane do ${email}.`);
      setEmail("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Nie udało się wysłać zaproszenia.");
    }
  };

  const patch = async (body: Partial<Workspace>) => {
    try {
      await api(`/workspaces/${ws}`, { method: "PATCH", body });
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Nie udało się zapisać.");
    }
  };

  return (
    <div className="stack">
      <Link to={`/w/${ws}`} className="small">← {workspace.name}</Link>
      <h1>Ustawienia</h1>
      <div className="grid grid-2">
        <div className="card stack">
          <h3>Zespół</h3>
          <table>
            <tbody>
              {members.map((m) => (
                <tr key={m.user_id}><td>{m.display_name || m.email}<div className="muted small">{m.email}</div></td><td>{ROLE_LABELS[m.role]}</td></tr>
              ))}
            </tbody>
          </table>
          <form className="stack" onSubmit={invite}>
            <label>Zaproś osobę (e-mail)<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
            <label>Rola
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                {Object.entries(ROLE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <button>Wyślij zaproszenie</button>
          </form>
          {msg && <div className="ok">{msg}</div>}
          {error && <div className="error">{error}</div>}
        </div>
        <div className="card stack">
          <h3>Przestrzeń</h3>
          <label className="row" style={{ flexDirection: "row", color: "var(--text)" }}>
            <input type="checkbox" checked={workspace.ai_enabled} onChange={(e) => patch({ ai_enabled: e.target.checked })} />
            Pomoc AI włączona (korekta, tłumaczenie, beta-czytanie)
          </label>
          <label>Przejście z researchu do pisania
            <select value={workspace.research_gate_mode} onChange={(e) => patch({ research_gate_mode: e.target.value })}>
              <option value="soft">Miękkie — można pominąć, podając powód</option>
              <option value="hard">Twarde — najpierw zamknij research</option>
            </select>
          </label>
        </div>
        <div className="card stack">
          <h3>Osoby i biogramy</h3>
          <p className="muted small">Autorzy, redaktorzy i tłumacze — biogram wpisujesz raz i używasz w każdej książce.</p>
          {people.map((p) => (
            <div key={p.id} className="row spread">
              <span>{p.display_name}{!p.bio_short && <span className="muted small"> — brak biogramu</span>}</span>
              <button className="ghost small" onClick={() => setEditing(p)}>edytuj</button>
            </div>
          ))}
          {!editing && <button className="ghost" onClick={() => setEditing({ id: "", display_name: "", bio_short: "", bio_long: "" })}>Dodaj osobę</button>}
          {editing && (
            <form className="stack" onSubmit={savePerson}>
              <label>Imię i nazwisko<input value={editing.display_name} onChange={(e) => setEditing({ ...editing, display_name: e.target.value })} required /></label>
              <label>Biogram krótki<textarea rows={3} value={editing.bio_short} onChange={(e) => setEditing({ ...editing, bio_short: e.target.value })} /></label>
              <label>Biogram długi<textarea rows={5} value={editing.bio_long} onChange={(e) => setEditing({ ...editing, bio_long: e.target.value })} /></label>
              <div className="row"><button>Zapisz</button><button type="button" className="ghost" onClick={() => setEditing(null)}>Anuluj</button></div>
            </form>
          )}
        </div>
        <form className="card stack" onSubmit={saveRules}>
          <h3>Reguła nazwiska</h3>
          <p className="muted small">
            Jedna reguła w linii: <code>poprawna forma | zakazane warianty, po przecinku</code>. Karta książki ostrzeże,
            gdy zakazany wariant pojawi się w tytule, opisach albo biogramach.
          </p>
          <textarea rows={3} value={rules} onChange={(e) => setRules(e.target.value)} placeholder="Kamil Skomra | Skomrakus, K. Skomra" />
          <button>Zapisz reguły</button>
        </form>
      </div>
    </div>
  );
}
