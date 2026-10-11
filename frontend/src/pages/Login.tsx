import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api, saveTokens, Tokens } from "../lib/api";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      saveTokens(await api<Tokens>("/auth/login", { method: "POST", body: { email, password } }));
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Nie udało się zalogować.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="center">
      <form className="card auth stack" onSubmit={submit}>
        <div className="brand">HRL <span>Books</span></div>
        <p className="muted small">Platforma, która prowadzi książkę od researchu po sprzedaż. Dostęp na zaproszenie.</p>
        <label>E-mail<input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
        <label>Hasło<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
        {error && <div className="error">{error}</div>}
        <button disabled={busy}>{busy ? "Logowanie…" : "Zaloguj się"}</button>
      </form>
    </div>
  );
}
