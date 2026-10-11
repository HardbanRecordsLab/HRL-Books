import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useWorkspace } from "../App";
import { api } from "../lib/api";
import { LISTING_STATUSES } from "./DistributionTab";

type Board = {
  channels: { key: string; name: string }[];
  rows: { book_id: string; title: string; book_status: string; cells: Record<string, { status: string; url: string }> }[];
};

const COLORS: Record<string, string> = {
  published: "var(--green)", rejected: "var(--red)", in_review: "var(--gold-2)", sent: "var(--gold)",
  ready: "var(--text)", not_ready: "var(--muted)", withdrawn: "var(--muted)",
};

export default function Distribution() {
  const { ws } = useParams();
  const workspace = useWorkspace();
  const navigate = useNavigate();
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Board>(`/workspaces/${ws}/distribution`).then(setBoard).catch((e) => setError(e.message));
  }, [ws]);

  return (
    <div className="stack">
      <Link to={`/w/${ws}`} className="small">← {workspace?.name}</Link>
      <h1>Tablica dystrybucji</h1>
      <p className="muted small">Każda komórka to status książki w danym sklepie. Kliknij wiersz, aby przejść do szczegółów.</p>
      {error && <div className="error">{error}</div>}
      {board && (
        <div className="card" style={{ overflowX: "auto" }}>
          {board.rows.length === 0 ? (
            <div className="empty">Brak tytułów.</div>
          ) : (
            <table>
              <thead>
                <tr><th>Tytuł</th>{board.channels.map((c) => <th key={c.key}>{c.name}</th>)}</tr>
              </thead>
              <tbody>
                {board.rows.map((r) => (
                  <tr key={r.book_id} className="click" onClick={() => navigate(`/w/${ws}/ksiazki/${r.book_id}?tab=Dystrybucja`)}>
                    <td><b>{r.title}</b></td>
                    {board.channels.map((c) => {
                      const cell = r.cells[c.key];
                      return (
                        <td key={c.key} className="small" style={{ color: COLORS[cell.status] }}>
                          {LISTING_STATUSES[cell.status]}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
