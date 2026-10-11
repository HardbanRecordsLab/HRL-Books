import { createContext, useContext, useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api, clearTokens, isLoggedIn, Me, ROLE_LABELS, Workspace } from "./lib/api";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Books from "./pages/Books";
import BookDetail from "./pages/BookDetail";
import Settings from "./pages/Settings";
import Admin from "./pages/Admin";
import Distribution from "./pages/Distribution";
import Shop from "./pages/Shop";
import { PublicProductPage, ThankYouPage } from "./pages/PublicShop";

type Session = { me: Me; workspaces: Workspace[]; reload: () => Promise<void> };
const SessionCtx = createContext<Session | null>(null);
export const useSession = () => useContext(SessionCtx)!;

function Shell() {
  const [session, setSession] = useState<Session | null>(null);
  const [failed, setFailed] = useState(false);
  const navigate = useNavigate();

  const load = async () => {
    try {
      const [me, workspaces] = await Promise.all([api<Me>("/auth/me"), api<Workspace[]>("/workspaces")]);
      setSession({ me, workspaces, reload: load });
    } catch {
      setFailed(true);
    }
  };
  useEffect(() => {
    load();
  }, []);

  if (failed) return <Navigate to="/logowanie" replace />;
  if (!session) return <div className="center muted">Ładowanie…</div>;

  const logout = async () => {
    const rt = localStorage.getItem("hrlb_refresh");
    await api("/auth/logout", { method: "POST", body: { refresh_token: rt } }).catch(() => undefined);
    clearTokens();
    navigate("/logowanie");
  };

  return (
    <SessionCtx.Provider value={session}>
      <div className="shell">
        <aside className="side">
          <div className="brand">HRL <span>Books</span></div>
          <nav className="nav">
            {session.workspaces.map((w) => (
              <NavLink key={w.id} to={`/w/${w.id}`}>{w.name}</NavLink>
            ))}
            {session.me.is_platform_admin && <NavLink to="/admin">Administracja</NavLink>}
          </nav>
          <div style={{ marginTop: "auto" }} className="stack small">
            <span className="muted">{session.me.email}</span>
            <button className="ghost" onClick={logout}>Wyloguj</button>
          </div>
        </aside>
        <main className="main">
          <Routes>
            <Route index element={<Home />} />
            <Route path="w/:ws" element={<Books />} />
            <Route path="w/:ws/ksiazki/:id" element={<BookDetail />} />
            <Route path="w/:ws/ustawienia" element={<Settings />} />
            <Route path="w/:ws/dystrybucja" element={<Distribution />} />
            <Route path="w/:ws/sklep" element={<Shop />} />
            <Route path="admin" element={session.me.is_platform_admin ? <Admin /> : <Navigate to="/" />} />
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </main>
      </div>
    </SessionCtx.Provider>
  );
}

function Home() {
  const { workspaces, me } = useSession();
  if (workspaces.length === 1) return <Navigate to={`/w/${workspaces[0].id}`} replace />;
  return (
    <div className="stack">
      <h1>Twoje przestrzenie</h1>
      {workspaces.length === 0 && (
        <div className="card empty">
          Nie należysz jeszcze do żadnej przestrzeni.
          {me.is_platform_admin && <> Utwórz ją w <NavLink to="/admin">Administracji</NavLink>.</>}
        </div>
      )}
      <div className="grid grid-2">
        {workspaces.map((w) => (
          <NavLink key={w.id} to={`/w/${w.id}`} className="card">
            <h3>{w.name}</h3>
            <span className="muted small">{ROLE_LABELS[w.role || ""] || w.role}</span>
          </NavLink>
        ))}
      </div>
    </div>
  );
}

export function useWorkspace(): Workspace | undefined {
  const { ws } = useParams();
  return useSession().workspaces.find((w) => w.id === ws);
}

// Checked on every render of the route (not once in App), so a fresh login is seen right away.
function RequireAuth() {
  return isLoggedIn() ? <Shell /> : <Navigate to="/logowanie" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/logowanie" element={<Login />} />
      <Route path="/rejestracja" element={<Register />} />
      <Route path="/sklep/dziekujemy" element={<ThankYouPage />} />
      <Route path="/sklep/:id" element={<PublicProductPage />} />
      <Route path="/*" element={<RequireAuth />} />
    </Routes>
  );
}
