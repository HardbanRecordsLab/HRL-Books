import { useCallback, useEffect, useState } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import Link from "@tiptap/extension-link";
import { ApiError, api } from "../lib/api";

type ChapterRow = { id: string; title: string; position: number; status: string; status_label: string; words: number; chars: number };
type ChapterFull = ChapterRow & { body: string; version_id: string | null };
type Version = { id: string; words: number; origin: string; note: string; created_at: string; body: string };

const STATUSES: Record<string, string> = { draft: "szkic", to_edit: "do redakcji", edited: "zredagowany", approved: "zatwierdzony" };
const ORIGIN: Record<string, string> = { human: "ręcznie", ai: "AI", import: "import" };

function Toolbar({ editor }: { editor: ReturnType<typeof useEditor> }) {
  if (!editor) return null;
  const b = (label: string, active: boolean, run: () => void, title: string) => (
    <button type="button" title={title} className={active ? "" : "ghost"} style={{ padding: ".3rem .6rem", minWidth: 34 }}
      onMouseDown={(e) => { e.preventDefault(); run(); }}>{label}</button>
  );
  const c = () => editor.chain().focus();
  return (
    <div className="row" style={{ gap: ".3rem" }}>
      {b("H2", editor.isActive("heading", { level: 2 }), () => c().toggleHeading({ level: 2 }).run(), "Nagłówek")}
      {b("H3", editor.isActive("heading", { level: 3 }), () => c().toggleHeading({ level: 3 }).run(), "Podnagłówek")}
      {b("B", editor.isActive("bold"), () => c().toggleBold().run(), "Pogrubienie")}
      {b("I", editor.isActive("italic"), () => c().toggleItalic().run(), "Kursywa")}
      {b("U", editor.isActive("underline"), () => c().toggleUnderline().run(), "Podkreślenie")}
      {b("•", editor.isActive("bulletList"), () => c().toggleBulletList().run(), "Lista")}
      {b("1.", editor.isActive("orderedList"), () => c().toggleOrderedList().run(), "Lista numerowana")}
      {b("„”", editor.isActive("blockquote"), () => c().toggleBlockquote().run(), "Cytat")}
      {b("↶", false, () => c().undo().run(), "Cofnij")}
      {b("↷", false, () => c().redo().run(), "Ponów")}
    </div>
  );
}

export default function ManuscriptTab({ base, canEdit, aiSlot }: { base: string; canEdit: boolean;
  aiSlot?: (chapter: ChapterFull, reload: () => void, dirty: boolean) => React.ReactNode }) {
  const url = `${base}/chapters`;
  const [list, setList] = useState<{ chapters: ChapterRow[]; words: number } | null>(null);
  const [current, setCurrent] = useState<ChapterFull | null>(null);
  const [dirty, setDirty] = useState(false);
  const [versions, setVersions] = useState<Version[] | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const editor = useEditor({
    extensions: [StarterKit.configure({ heading: { levels: [2, 3, 4] } }), Underline, Link.configure({ openOnClick: false })],
    content: "",
    editable: canEdit,
    onUpdate: () => setDirty(true),
  });

  const loadList = () => api<{ chapters: ChapterRow[]; words: number }>(url).then(setList).catch((e) => setError(e.message));
  const open = useCallback(async (id: string) => {
    if (dirty && !confirm("Masz niezapisane zmiany. Przejść bez zapisu?")) return;
    const ch = await api<ChapterFull>(`${url}/${id}`);
    setCurrent(ch);
    setVersions(null);
    editor?.commands.setContent(ch.body || "", false);
    setDirty(false);
  }, [dirty, editor, url]);

  useEffect(() => {
    loadList();
  }, [base]);
  useEffect(() => {
    if (list && !current && list.chapters.length && editor) open(list.chapters[0].id);
  }, [list, editor]);

  const save = useCallback(async () => {
    if (!current || !editor) return;
    setError("");
    try {
      const ch = await api<ChapterFull>(`${url}/${current.id}/content`, { method: "PUT", body: { body: editor.getHTML() } });
      setCurrent(ch);
      setDirty(false);
      setMsg(`Zapisano · ${ch.words} słów`);
      loadList();
      if (versions) loadVersions();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Nie udało się zapisać.");
    }
  }, [current, editor, url, versions]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); save(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save]);

  const loadVersions = () => current && api<Version[]>(`${url}/${current.id}/versions`).then(setVersions);
  const restore = async (v: Version) => {
    if (!current || !confirm("Przywrócić tę wersję? Obecna zostanie w historii.")) return;
    const ch = await api<ChapterFull>(`${url}/${current.id}/versions/${v.id}/restore`, { method: "POST" });
    setCurrent(ch); editor?.commands.setContent(ch.body, false); setDirty(false); loadVersions(); loadList();
  };

  const addChapter = async () => {
    if (!newTitle.trim()) return;
    const ch = await api<ChapterFull>(url, { method: "POST", body: { title: newTitle.trim() } }).catch((e) => { setError(e.message); return null; });
    setNewTitle("");
    await loadList();
    if (ch) open(ch.id);
  };

  const importFile = async (f: File | undefined) => {
    if (!f) return;
    setError(""); setMsg("Importuję…");
    const fd = new FormData();
    fd.append("file", f);
    const r = await fetch(`/api/v1${base}/manuscript/import`, { method: "POST", body: fd,
      headers: { Authorization: `Bearer ${localStorage.getItem("hrlb_access")}` } });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { setMsg(""); setError(typeof data.detail === "string" ? data.detail : "Import się nie udał."); return; }
    setMsg(`Zaimportowano rozdziałów: ${data.chapters}.`);
    loadList();
  };

  const move = async (idx: number, dir: -1 | 1) => {
    if (!list) return;
    const ids = list.chapters.map((c) => c.id);
    const j = idx + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[idx], ids[j]] = [ids[j], ids[idx]];
    await api(`${url}/order`, { method: "PUT", body: { chapter_ids: ids } });
    loadList();
  };

  const patch = async (body: Record<string, string>) => {
    if (!current) return;
    await api(`${url}/${current.id}`, { method: "PATCH", body });
    setCurrent({ ...current, ...body } as ChapterFull);
    loadList();
  };

  const remove = async () => {
    if (!current || !confirm(`Usunąć rozdział „${current.title}” razem z historią wersji?`)) return;
    await api(`${url}/${current.id}`, { method: "DELETE" });
    setCurrent(null); editor?.commands.setContent("", false); loadList();
  };

  return (
    <div className="grid" style={{ gridTemplateColumns: "minmax(200px, 260px) 1fr", alignItems: "start" }}>
      <div className="card stack" style={{ position: "sticky", top: "1rem" }}>
        <div className="row spread"><h3 style={{ margin: 0 }}>Rozdziały</h3><span className="muted small">{list?.words ?? 0} słów</span></div>
        {list?.chapters.map((c, i) => (
          <div key={c.id} className="row spread" style={{ gap: ".3rem" }}>
            <a style={{ flex: 1, color: current?.id === c.id ? "var(--gold-2)" : "var(--text)", cursor: "pointer" }} onClick={() => open(c.id)}>
              {i + 1}. {c.title}<div className="muted small">{c.status_label} · {c.words} sł.</div>
            </a>
            {canEdit && (
              <span className="row" style={{ gap: 0 }}>
                <button className="ghost small" style={{ padding: ".1rem .4rem" }} onClick={() => move(i, -1)}>↑</button>
                <button className="ghost small" style={{ padding: ".1rem .4rem" }} onClick={() => move(i, 1)}>↓</button>
              </span>
            )}
          </div>
        ))}
        {canEdit && (
          <>
            <div className="row"><input style={{ flex: 1, minWidth: 0 }} placeholder="Nowy rozdział" value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addChapter()} />
              <button className="ghost" onClick={addChapter}>+</button></div>
            <label className="small">Import z Worda / TXT / MD
              <input type="file" accept=".docx,.txt,.md" onChange={(e) => importFile(e.target.files?.[0])} />
            </label>
          </>
        )}
      </div>

      <div className="stack">
        {!current ? (
          <div className="card empty">Dodaj pierwszy rozdział albo zaimportuj rękopis z Worda — rozdziały powstaną z nagłówków 1. stopnia.</div>
        ) : (
          <>
            <div className="card stack">
              <div className="row spread">
                <input style={{ flex: 1, fontFamily: "Georgia, serif", fontSize: "1.2rem" }} value={current.title} disabled={!canEdit}
                  onChange={(e) => setCurrent({ ...current, title: e.target.value })} onBlur={(e) => patch({ title: e.target.value })} />
                <select value={current.status} disabled={!canEdit} onChange={(e) => patch({ status: e.target.value })}>
                  {Object.entries(STATUSES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </div>
              {canEdit && <Toolbar editor={editor} />}
              <div className="manuscript"><EditorContent editor={editor} /></div>
              <div className="row spread">
                <span className="muted small">{dirty ? "Niezapisane zmiany (Ctrl+S)" : msg}</span>
                <div className="row">
                  <button className="ghost" onClick={() => (versions ? setVersions(null) : loadVersions())}>{versions ? "Ukryj wersje" : "Historia wersji"}</button>
                  {canEdit && <button className="danger" onClick={remove}>Usuń</button>}
                  {canEdit && <button onClick={save} disabled={!dirty}>Zapisz</button>}
                </div>
              </div>
              {error && <div className="error">{error}</div>}
            </div>
            {aiSlot && current && aiSlot(current, () => { loadList(); open(current.id); }, dirty)}
            {versions && (
              <div className="card stack">
                <h3>Historia wersji</h3>
                {versions.map((v, i) => (
                  <div key={v.id} className="row spread small" style={{ borderTop: "1px solid var(--line)", paddingTop: ".4rem" }}>
                    <span>{new Date(v.created_at).toLocaleString("pl-PL")} · {ORIGIN[v.origin] || v.origin} · {v.words} sł.{v.note && ` · ${v.note}`}</span>
                    {canEdit && i > 0 && <button className="ghost small" onClick={() => restore(v)}>przywróć</button>}
                    {i === 0 && <span className="muted">obecna</span>}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
