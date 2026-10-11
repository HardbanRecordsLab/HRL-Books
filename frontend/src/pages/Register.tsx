import { FormEvent, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, api, ROLE_LABELS, saveTokens, Tokens } from "../lib/api";

type Invite = { email: string; role: string; workspace_id: string };

export default function Register() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [invite, setInvite] = useState<Invite | null>(null);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    api<Invite>(`/auth/invitation/${encodeURIComponent(token)}`)
      .then(setInvite)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Zaproszenie jest nieważne."));
  }, [token]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      saveTokens(await api<Tokens>("/auth/register", { method: "POST", body: { token, password, display_name: name } }));
      navigate(invite ? `/w/${invite.workspace_id}` : "/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Nie udało się utworzyć konta.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="center">
      <form className="card auth stack" onSubmit={submit}>
        <div className="brand">HRL <span>Books</span></div>
        {!invite && !error && <p className="muted">Sprawdzam zaproszenie…</p>}
        {invite && (
          <>
            <p className="small">
              Zaproszenie dla <b>{invite.email}</b> jako <b>{ROLE_LABELS[invite.role] || invite.role}</b>.
              Jeśli masz już konto z tym adresem, podaj jego hasło.
            </p>
            <label>Imię i nazwisko<input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></label>
            <label>Hasło (min. 10 znaków)<input type="password" minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" required /></label>
            <button disabled={busy}>{busy ? "Zapisywanie…" : "Przyjmij zaproszenie"}</button>
          </>
        )}
        {error && <div className="error">{error}</div>}
      </form>
    </div>
  );
}
