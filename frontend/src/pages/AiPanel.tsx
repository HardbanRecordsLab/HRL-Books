import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../lib/api";

export type Suggestion = { original: string; suggestion: string; reason: string };
export type Job = {
  id: string; kind: string; kind_label: string; chapter_id: string | null; status: string; error: string;
  params: Record<string, string>; result: { suggestions?: Suggestion[]; report?: string; text?: string; truncated?: boolean;
    new_chapter_title?: string; applied?: number[]; skipped?: number[] };
  model: string; tokens_in: number; tokens_out: number; created_at: string;
};
type Status = { enabled: boolean; configured: boolean; used_today: number; limit: number; jobs: Job[] };

const RUNNING = ["queued", "running"];

/** Start a job and poll it until it finishes. */
function useJob(base: string, onDone?: (j: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const timer = useRef<number>();
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const poll = (id: string) => {
    timer.current = window.setTimeout(async () => {
      const j = await api<Job>(`${base}/ai/jobs/${id}`).catch(() => null);
      if (!j) return poll(id);
      setJob(j);
      if (RUNNING.includes(j.status)) poll(id);
      else onDone?.(j);
    }, 2500);
  };
  const start = async (path: string, body: unknown) => {
    setError(""); window.clearTimeout(timer.current);
    try {
      const j = await api<Job>(`${base}/ai/${path}`, { method: "POST", body });
      setJob(j);
      poll(j.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Nie udało się uruchomić zadania.");
    }
  };
  return { job, setJob, error, start, busy: !!job && RUNNING.includes(job.status) };
}

function Report({ text }: { text: string }) {
  return (
    <div className="stack" style={{ gap: ".3rem" }}>
      {text.split("\n").map((line, i) =>
        line.startsWith("## ") ? <h4 key={i} style={{ margin: ".6rem 0 0" }}>{line.slice(3)}</h4>
          : line.trim() ? <div key={i} style={{ whiteSpace: "pre-wrap" }}>{line.replace(/\*\*/g, "")}</div> : null)}
    </div>
  );
}

function Busy({ job }: { job: Job }) {
  return <div className="muted small">⏳ {job.kind_label}: AI pracuje… (dłuższe rozdziały zajmują do kilku minut — możesz pisać dalej)</div>;
}

/** Panel under the chapter editor: proofreading with accept/reject and translation into a new chapter. */
export function ChapterAi({ base, chapter, dirty, reload, enabled, ws }: {
  base: string; chapter: { id: string; title: string }; dirty: boolean; reload: () => void; enabled: boolean; ws: string }) {
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [msg, setMsg] = useState("");
  const { job, setJob, error, start, busy } = useJob(base, (j) => {
    if (j.kind === "proofread") setPicked(new Set((j.result.suggestions || []).map((_, i) => i)));
    if (j.kind === "translate" && j.status === "done") { setMsg(`Gotowe — nowy rozdział „${j.result.new_chapter_title}”. Oryginał bez zmian.`); reload(); }
  });
  useEffect(() => { setJob(null); setMsg(""); }, [chapter.id]);

  if (!enabled) return <div className="card muted small">Asystent AI jest wyłączony. Właściciel może go włączyć w <Link to={`/w/${ws}/ustawienia`}>Ustawieniach</Link>.</div>;
  const suggestions = job?.kind === "proofread" && job.status === "done" ? job.result.suggestions || [] : [];

  const applyPicked = async () => {
    if (!job) return;
    const r = await api<{ applied: number; skipped: number }>(`${base}/ai/jobs/${job.id}/apply`, { method: "POST", body: { accept: [...picked] } });
    setMsg(`Zastosowano ${r.applied} poprawek${r.skipped ? `, pominięto ${r.skipped} (tekst zmienił się w międzyczasie)` : ""}. Poprzednia wersja jest w historii.`);
    setJob(null);
    reload();
  };

  return (
    <div className="card stack">
      <div className="row spread">
        <h3 style={{ margin: 0 }}>Asystent AI</h3>
        <div className="row">
          <button className="ghost" disabled={busy || dirty} onClick={() => start("proofread", { chapter_id: chapter.id })}>Korekta</button>
          <button className="ghost" disabled={busy || dirty} onClick={() => start("translate", { chapter_id: chapter.id, target: "en" })}>Tłumacz na EN</button>
          <button className="ghost" disabled={busy || dirty} onClick={() => start("translate", { chapter_id: chapter.id, target: "pl" })}>Tłumacz na PL</button>
          <button className="ghost" disabled={busy || dirty} onClick={() => start("beta-read", { chapter_id: chapter.id })}>Beta-czytanie</button>
        </div>
      </div>
      {dirty && <div className="muted small">Zapisz rozdział, zanim użyjesz AI — AI pracuje na zapisanej wersji.</div>}
      <div className="muted small">AI niczego nie nadpisuje: poprawki akceptujesz sam, tłumaczenie trafia do nowego rozdziału, każda zmiana zostaje w historii wersji.</div>
      {error && <div className="error">{error}</div>}
      {msg && <div className="ok">{msg}</div>}
      {job && busy && <Busy job={job} />}
      {job?.status === "failed" && <div className="error">{job.error || "Zadanie AI się nie udało."}</div>}

      {job?.kind === "proofread" && job.status === "done" && (
        suggestions.length === 0 ? <div className="ok">Korekta nie znalazła błędów.</div> : (
          <div className="stack">
            <div className="row spread">
              <b>Propozycje poprawek ({suggestions.length})</b>
              <span className="row">
                <button className="ghost small" onClick={() => setPicked(new Set(suggestions.map((_, i) => i)))}>zaznacz wszystkie</button>
                <button className="ghost small" onClick={() => setPicked(new Set())}>odznacz</button>
              </span>
            </div>
            {suggestions.map((s, i) => (
              <label key={i} className="row" style={{ flexDirection: "row", alignItems: "flex-start", color: "var(--text)", borderTop: "1px solid var(--line)", paddingTop: ".4rem" }}>
                <input type="checkbox" checked={picked.has(i)} onChange={(e) => {
                  const n = new Set(picked); if (e.target.checked) n.add(i); else n.delete(i); setPicked(n);
                }} />
                <span className="stack" style={{ gap: ".1rem" }}>
                  <span><s className="muted">{s.original}</s> → <b>{s.suggestion}</b></span>
                  {s.reason && <span className="muted small">{s.reason}</span>}
                </span>
              </label>
            ))}
            <div className="row"><button onClick={applyPicked} disabled={picked.size === 0}>Zastosuj zaznaczone ({picked.size})</button>
              <button className="ghost" onClick={() => setJob(null)}>Odrzuć wszystkie</button></div>
          </div>
        )
      )}
      {job?.kind === "beta_read" && job.status === "done" && job.result.report && <Report text={job.result.report} />}
    </div>
  );
}

const MARKETING: [string, string][] = [["blurb", "Opis książki"], ["social", "Posty do social media"], ["newsletter", "Newsletter"], ["keywords", "Słowa kluczowe i kategorie"]];

/** Book-level tab: beta-read of the whole book, marketing drafts, job log. */
export function AiTab({ base, ws, canUse }: { base: string; ws: string; canUse: boolean }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [lang, setLang] = useState("pl");
  const [open, setOpen] = useState<string | null>(null);
  const [copied, setCopied] = useState("");
  const load = () => api<Status>(`${base}/ai`).then(setStatus);
  const { job, error, start, busy } = useJob(base, (j) => { load(); setOpen(j.id); });
  useEffect(() => { load(); }, [base]);

  if (!status) return <div className="muted">Ładowanie…</div>;
  if (!status.enabled) return (
    <div className="card empty"><h3>Asystent AI jest wyłączony</h3>
      <p>AI w HRL Books jest opcjonalne. Właściciel przestrzeni może je włączyć w <Link to={`/w/${ws}/ustawienia`}>Ustawieniach</Link>.</p>
      <p className="small muted">Teksty wysyłamy do modelu przez OpenRouter tylko do dostawców, którzy nie zapisują danych i nie trenują na nich modeli.</p></div>
  );

  const copy = (id: string, text: string) => { navigator.clipboard.writeText(text).then(() => { setCopied(id); setTimeout(() => setCopied(""), 1500); }); };
  const body = (j: Job) => j.result.report || j.result.text || (j.result.suggestions ? `${j.result.suggestions.length} propozycji poprawek` : "")
    || (j.result.new_chapter_title ? `Nowy rozdział: ${j.result.new_chapter_title}` : "");

  return (
    <div className="stack">
      <div className="grid grid-2">
        <div className="card stack">
          <h3>Beta-czytanie całej książki</h3>
          <p className="small muted">Raport jak od wnikliwego czytelnika: mocne strony, co osłabia tekst, tempo, jasność i 5 najważniejszych poprawek. Pojedyncze rozdziały — w zakładce Rękopis.</p>
          <div><button disabled={!canUse || busy} onClick={() => start("beta-read", {})}>Przeczytaj książkę</button></div>
        </div>
        <div className="card stack">
          <h3>Teksty marketingowe</h3>
          <p className="small muted">Szkice na podstawie metadanych i początku rękopisu. To punkt wyjścia — przeczytaj i popraw przed publikacją.</p>
          <div className="row">
            <select value={lang} onChange={(e) => setLang(e.target.value)}><option value="pl">po polsku</option><option value="en">po angielsku</option></select>
            {MARKETING.map(([k, label]) => <button key={k} className="ghost" disabled={!canUse || busy} onClick={() => start("marketing", { kind: k, lang })}>{label}</button>)}
          </div>
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      {job && busy && <Busy job={job} />}

      <div className="card stack">
        <div className="row spread"><h3 style={{ margin: 0 }}>Historia zadań AI</h3>
          <span className="muted small">Dziś: {status.used_today} / {status.limit}</span></div>
        {status.jobs.length === 0 && <div className="muted">Brak zadań.</div>}
        {status.jobs.map((j) => (
          <div key={j.id} className="stack" style={{ borderTop: "1px solid var(--line)", paddingTop: ".5rem", gap: ".3rem" }}>
            <div className="row spread">
              <a style={{ cursor: "pointer" }} onClick={() => setOpen(open === j.id ? null : j.id)}>
                <b>{j.kind_label}</b>{j.params.label && ` · ${j.params.label}`}{j.params.chapter_title && ` · ${j.params.chapter_title}`}
              </a>
              <span className="muted small">{new Date(j.created_at).toLocaleString("pl-PL")} · {
                j.status === "failed" ? "błąd" : RUNNING.includes(j.status) ? "w toku" : j.status === "applied" ? "zastosowano" : "gotowe"}</span>
            </div>
            {open === j.id && (j.status === "failed" ? <div className="error">{j.error}</div> : (
              <div className="stack">
                {j.result.truncated && <div className="muted small">Książka jest długa — AI przeczytało pierwsze ok. 120 tys. znaków.</div>}
                {(j.result.report || j.result.text) ? <Report text={j.result.report || j.result.text || ""} /> : <div>{body(j)}</div>}
                <div className="row">
                  {(j.result.report || j.result.text) && <button className="ghost small" onClick={() => copy(j.id, body(j))}>{copied === j.id ? "Skopiowano" : "Kopiuj"}</button>}
                  <span className="muted small">{j.model}{j.tokens_in ? ` · ${j.tokens_in + j.tokens_out} tokenów` : ""}</span>
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
