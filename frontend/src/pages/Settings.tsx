import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useSession, useWorkspace } from "../App";
import { ApiError, api, ROLE_LABELS, Workspace } from "../lib/api";

type Member = { user_id: string; email: string; display_name: string; role: string };

export default function Settings() {
  const { ws } = useParams();
  const workspace = useWorkspace();
  const { reload } = useSession();
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("author");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<Member[]>(`/workspaces/${ws}/members`).then(setMembers).catch((e) => setError(e.message));
  }, [ws]);

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
      </div>
    </div>
  );
}
