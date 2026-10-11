// API client: access token in memory + localStorage, refresh token rotated on 401 (backend: spec FR-ACC-03).
const ACCESS = "hrlb_access";
const REFRESH = "hrlb_refresh";

export type Tokens = { access_token: string; refresh_token: string };

export function saveTokens(t: Tokens) {
  localStorage.setItem(ACCESS, t.access_token);
  localStorage.setItem(REFRESH, t.refresh_token);
}

export function clearTokens() {
  localStorage.removeItem(ACCESS);
  localStorage.removeItem(REFRESH);
}

export function isLoggedIn() {
  return !!localStorage.getItem(REFRESH);
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let refreshing: Promise<boolean> | null = null;

async function refresh(): Promise<boolean> {
  const rt = localStorage.getItem(REFRESH);
  if (!rt) return false;
  const r = await fetch("/api/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: rt }),
  });
  if (!r.ok) {
    clearTokens();
    return false;
  }
  saveTokens(await r.json());
  return true;
}

export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const doFetch = () =>
    fetch(`/api/v1${path}`, {
      method: opts.method || "GET",
      headers: {
        "Content-Type": "application/json",
        ...(localStorage.getItem(ACCESS) ? { Authorization: `Bearer ${localStorage.getItem(ACCESS)}` } : {}),
      },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  let r = await doFetch();
  if (r.status === 401 && localStorage.getItem(REFRESH)) {
    refreshing = refreshing || refresh().finally(() => (refreshing = null));
    if (await refreshing) r = await doFetch();
  }
  if (r.status === 204) return undefined as T;
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail = (data as { detail?: unknown }).detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? "Sprawdź wpisane dane." : `Błąd ${r.status}`;
    if (r.status === 401) clearTokens();
    throw new ApiError(r.status, msg);
  }
  return data as T;
}

export type Me = { id: string; email: string; display_name: string; is_platform_admin: boolean };
export type Workspace = { id: string; name: string; slug: string; ai_enabled: boolean; research_gate_mode: string; status: string; role?: string };
export type Book = {
  id: string; workspace_id: string; title: string; subtitle: string; language: string; status: string;
  desc_short: string; created_at: string;
};

export const STATUS_LABELS: Record<string, string> = {
  idea: "Pomysł", research: "Research", writing: "Pisanie", editing: "Redakcja",
  preparation: "Przygotowanie", distribution: "Dystrybucja", published: "Opublikowana", archived: "Archiwum",
};
export const ROLE_LABELS: Record<string, string> = { owner: "właściciel", editor: "redaktor", author: "autor", reviewer: "recenzent" };
