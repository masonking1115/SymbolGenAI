import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api";
import { I } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import type {
  BomItem,
  DatasheetItem,
  RequirementDoc,
  ResourceSubTab,
  SkillItem,
} from "../types";

const SUBS: { key: ResourceSubTab; label: string }[] = [
  { key: "datasheets", label: "Datasheets" },
  { key: "bom", label: "BOM" },
  { key: "requirements", label: "Design Requirements" },
  { key: "skills", label: "Skills" },
];

/** Read a File into raw base64 (strips the data: URL prefix). Uploads go over
 *  JSON so the backend needs no multipart dependency. */
function readAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => {
      const res = String(r.result);
      const comma = res.indexOf(",");
      resolve(comma >= 0 ? res.slice(comma + 1) : res);
    };
    r.onerror = () => reject(r.error ?? new Error("read failed"));
    r.readAsDataURL(file);
  });
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function Resources() {
  const [sub, setSub] = useState<ResourceSubTab>("datasheets");
  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="px-6 pt-5 shrink-0">
        <PageHeader
          eyebrow="Phase 1 · Design Resources"
          title="Datasheets, BOM, requirements, and skills the pipeline draws on"
        />
        <div className="mt-4 flex items-center gap-1 border-b border-edge">
          {SUBS.map((s) => {
            const on = s.key === sub;
            return (
              <button
                key={s.key}
                onClick={() => setSub(s.key)}
                className={
                  "px-3 py-2 text-sm -mb-px border-b-2 transition " +
                  (on
                    ? "border-ink-900 text-ink-900 font-medium"
                    : "border-transparent text-ink-500 hover:text-ink-900")
                }
              >
                {s.label}
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-auto thin-scroll px-6 py-4">
        <div className="max-w-[900px]">
          {sub === "datasheets" && <DatasheetsPanel />}
          {sub === "bom" && <BomPanel />}
          {sub === "requirements" && <RequirementsPanel />}
          {sub === "skills" && <SkillsPanel />}
          <section className="mt-6 px-3 py-2 rounded border border-edge bg-rail/30 text-[11.5px]">
            <div className="text-ink-500 mb-1">Providers</div>
            <ProvidersBox />
          </section>
        </div>
      </div>
    </div>
  );
}

function ProvidersBox() {
  const [p, setP] = useState<Record<string, string> | null>(null);
  useEffect(() => {
    fetch("/api/review/providers").then(r => r.json()).then(setP).catch(() => {});
  }, []);
  if (!p) return <div className="text-ink-500">loading…</div>;
  return (
    <ul className="grid grid-cols-2 gap-1">
      {Object.entries(p).map(([slot, impl]) => (
        <li key={slot} className="font-mono">
          {slot}: <span className={impl.startsWith("Custom") ? "text-ok" : "text-ink-700"}>{impl}</span>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Datasheets
// ---------------------------------------------------------------------------
function DatasheetsPanel() {
  const [items, setItems] = useState<DatasheetItem[]>([]);
  const [mpn, setMpn] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await api.resourcesDatasheets();
      setItems(r.datasheets);
    } catch {
      // ignore
    }
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);

  const mpns = useMemo(
    () => Array.from(new Set(items.map((i) => i.mpn))).sort(),
    [items],
  );
  const groups = useMemo(() => {
    const m = new Map<string, DatasheetItem[]>();
    for (const it of items) {
      const arr = m.get(it.mpn);
      if (arr) arr.push(it);
      else m.set(it.mpn, [it]);
    }
    return Array.from(m.entries());
  }, [items]);

  const upload = async () => {
    if (!file || !mpn.trim() || busy) return;
    setBusy(true);
    setErr("");
    try {
      const b64 = await readAsBase64(file);
      await api.uploadDatasheet(mpn.trim(), file.name, b64);
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <SectionIntro
        title="Datasheets"
        note="Every datasheet in the parts library, grouped by part. Upload a PDF and assign it to a part — it lands in that part's library folder and shows up across the app."
      />

      <div className="rounded-lg border border-edge bg-rail/40 p-3">
        <div className="text-[11px] uppercase tracking-wide text-ink-500 mb-2">
          Upload datasheet
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            list="ds-mpn-list"
            value={mpn}
            onChange={(e) => setMpn(e.target.value)}
            placeholder="Part / MPN (e.g. OPA2388)"
            className="h-9 px-2.5 text-sm border border-edge rounded-md bg-white w-[220px] focus:outline-none focus:border-ink-300"
          />
          <datalist id="ds-mpn-list">
            {mpns.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm text-ink-700 file:mr-2 file:h-9 file:px-3 file:rounded-md file:border file:border-edge file:bg-white file:text-ink-700 file:text-sm hover:file:border-ink-300"
          />
          <button
            onClick={upload}
            disabled={busy || !file || !mpn.trim()}
            className="h-9 px-3 inline-flex items-center gap-1.5 text-sm font-medium rounded-md bg-ink-900 text-white hover:bg-black disabled:opacity-50"
          >
            <I.Upload size={15} />
            {busy ? "Uploading…" : "Upload"}
          </button>
        </div>
        {err && <div className="mt-2 text-xs text-err">{err}</div>}
      </div>

      <div className="space-y-3">
        {groups.length === 0 ? (
          <Empty>No datasheets in the library yet.</Empty>
        ) : (
          groups.map(([groupMpn, files]) => (
            <div key={groupMpn} className="rounded-lg border border-edge">
              <div className="px-3 py-2 border-b border-edge flex items-center gap-2">
                <span className="font-mono text-[13px] text-ink-900">{groupMpn}</span>
                <span className="text-[11px] text-ink-500">
                  {files.length} file{files.length > 1 ? "s" : ""}
                </span>
              </div>
              <ul className="divide-y divide-edge">
                {files.map((f) => (
                  <li key={f.file} className="px-3 py-2 flex items-center gap-2">
                    <span className="text-ink-500">
                      <I.Datasheet size={16} />
                    </span>
                    <a
                      href={api.datasheetUrl(f.mpn, f.file)}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[13px] text-ink-900 hover:underline truncate"
                      title={`${f.file} — open PDF`}
                    >
                      {f.file}
                    </a>
                    <span className="ml-auto text-[11px] text-ink-500 shrink-0">
                      {fmtSize(f.size)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Design Requirements
// ---------------------------------------------------------------------------
function RequirementsPanel() {
  const [docs, setDocs] = useState<RequirementDoc[]>([]);
  const [activeMd, setActiveMd] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await api.resourcesRequirements();
      setDocs(r.docs);
      setActiveMd(r.active_md_exists);
    } catch {
      // ignore
    }
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);

  const upload = async (file: File) => {
    setBusy(true);
    setErr("");
    try {
      const b64 = await readAsBase64(file);
      await api.uploadRequirement(file.name, b64);
      if (fileRef.current) fileRef.current.value = "";
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <SectionIntro
        title="Design Requirements"
        note="Upload requirement source documents — PDF, Markdown, Word (.docx), PowerPoint (.pptx), Excel (.xlsx/.xls), CSV, or plain text. These are kept alongside the active design_requirements.md spec the pipeline reads."
      />

      <div className="rounded-lg border border-edge bg-rail/40 p-3">
        <div className="text-[11px] uppercase tracking-wide text-ink-500 mb-2">
          Upload requirements document
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx,.doc,.pptx,.ppt,.md,.txt,.xlsx,.xls,.csv,.rtf,.odt"
            disabled={busy}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) upload(f);
            }}
            className="text-sm text-ink-700 file:mr-2 file:h-9 file:px-3 file:rounded-md file:border file:border-edge file:bg-white file:text-ink-700 file:text-sm hover:file:border-ink-300"
          />
          {busy && <span className="text-xs text-ink-500">Uploading…</span>}
        </div>
        {err && <div className="mt-2 text-xs text-err">{err}</div>}
      </div>

      <div className="rounded-lg border border-edge px-3 py-2.5 flex items-center gap-2 text-[13px]">
        <span className={activeMd ? "text-ok" : "text-ink-300"}>
          <I.Datasheet size={16} />
        </span>
        <span className="font-mono text-ink-900">design_requirements.md</span>
        <span className="text-[11px] text-ink-500">
          {activeMd ? "active spec read by the pipeline" : "not present"}
        </span>
      </div>

      <div className="space-y-2">
        <div className="text-[11px] uppercase tracking-wide text-ink-500">
          Uploaded documents
        </div>
        {docs.length === 0 ? (
          <Empty>No requirement documents uploaded yet.</Empty>
        ) : (
          <ul className="rounded-lg border border-edge divide-y divide-edge">
            {docs.map((d) => (
              <li key={d.name} className="px-3 py-2 flex items-center gap-2">
                <span className="text-ink-500">
                  <I.Datasheet size={16} />
                </span>
                <a
                  href={api.requirementFileUrl(d.name)}
                  target="_blank"
                  rel="noreferrer"
                  className="text-[13px] text-ink-900 hover:underline truncate"
                  title={`${d.name} — open`}
                >
                  {d.name}
                </a>
                <span className="ml-auto text-[11px] text-ink-500 shrink-0">
                  {fmtSize(d.size)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// BOM (bill of materials)
// ---------------------------------------------------------------------------
function BomPanel() {
  const [files, setFiles] = useState<BomItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await api.resourcesBom();
      setFiles(r.bom);
    } catch {
      // ignore
    }
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);

  const upload = async (file: File) => {
    setBusy(true);
    setErr("");
    try {
      const b64 = await readAsBase64(file);
      await api.uploadBom(file.name, b64);
      if (fileRef.current) fileRef.current.value = "";
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <SectionIntro
        title="BOM"
        note="Bill of materials for the design. Upload a .xlsx or .csv — the generated test1_bom.xlsx is included to start."
      />

      <div className="rounded-lg border border-edge bg-rail/40 p-3">
        <div className="text-[11px] uppercase tracking-wide text-ink-500 mb-2">
          Upload BOM
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            disabled={busy}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) upload(f);
            }}
            className="text-sm text-ink-700 file:mr-2 file:h-9 file:px-3 file:rounded-md file:border file:border-edge file:bg-white file:text-ink-700 file:text-sm hover:file:border-ink-300"
          />
          {busy && <span className="text-xs text-ink-500">Uploading…</span>}
        </div>
        {err && <div className="mt-2 text-xs text-err">{err}</div>}
      </div>

      <div className="space-y-2">
        <div className="text-[11px] uppercase tracking-wide text-ink-500">
          BOM files
        </div>
        {files.length === 0 ? (
          <Empty>No BOM files yet. Upload a .xlsx or .csv above.</Empty>
        ) : (
          <ul className="rounded-lg border border-edge divide-y divide-edge">
            {files.map((f) => (
              <li key={f.name} className="px-3 py-2 flex items-center gap-2">
                <span className="text-ok">
                  <I.Bom size={16} />
                </span>
                <a
                  href={api.bomFileUrl(f.name)}
                  download
                  className="text-[13px] text-ink-900 hover:underline truncate"
                  title={`${f.name} — download`}
                >
                  {f.name}
                </a>
                <span className="ml-auto text-[11px] text-ink-500 shrink-0">
                  {fmtSize(f.size)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skills
// ---------------------------------------------------------------------------
interface Editing {
  slug?: string;
  title: string;
  content: string;
}

function SkillsPanel() {
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const refresh = useCallback(async () => {
    try {
      const r = await api.resourcesSkills();
      setSkills(r.skills);
    } catch {
      // ignore
    }
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);

  const open = async (slug: string) => {
    setErr("");
    try {
      const r = await api.resourcesSkill(slug);
      const title = skills.find((s) => s.slug === slug)?.title ?? slug;
      setEditing({ slug, title, content: r.content });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const save = async () => {
    if (!editing || !editing.title.trim() || busy) return;
    setBusy(true);
    setErr("");
    try {
      await api.saveSkill(editing.title.trim(), editing.content, editing.slug);
      setEditing(null);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (slug: string) => {
    try {
      await api.deleteSkill(slug);
      if (editing?.slug === slug) setEditing(null);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="space-y-5">
      <SectionIntro
        title="Skills"
        note="Reusable guidance notes for the assistant. These will be used to steer chats and chat sessions — pick which apply when starting a session."
      />

      {editing ? (
        <div className="rounded-lg border border-edge p-3 space-y-2">
          <input
            value={editing.title}
            onChange={(e) => setEditing({ ...editing, title: e.target.value })}
            placeholder="Skill title"
            className="w-full h-9 px-2.5 text-sm border border-edge rounded-md focus:outline-none focus:border-ink-300"
          />
          <textarea
            value={editing.content}
            onChange={(e) => setEditing({ ...editing, content: e.target.value })}
            placeholder="Markdown guidance — what the assistant should know or do…"
            rows={12}
            className="w-full resize-y text-[13px] font-mono border border-edge rounded-md px-2.5 py-2 focus:outline-none focus:border-ink-300"
          />
          {err && <div className="text-xs text-err">{err}</div>}
          <div className="flex items-center gap-2">
            <button
              onClick={save}
              disabled={busy || !editing.title.trim()}
              className="h-9 px-3 text-sm font-medium rounded-md bg-ink-900 text-white hover:bg-black disabled:opacity-50"
            >
              {busy ? "Saving…" : "Save skill"}
            </button>
            <button
              onClick={() => setEditing(null)}
              className="h-9 px-3 text-sm rounded-md border border-edge text-ink-700 hover:border-ink-300"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setEditing({ title: "", content: "" })}
          className="h-9 px-3 inline-flex items-center gap-1.5 text-sm font-medium rounded-md bg-ink-900 text-white hover:bg-black"
        >
          <I.Plus size={15} /> New skill
        </button>
      )}

      {!editing && err && <div className="text-xs text-err">{err}</div>}

      <div className="space-y-2">
        {skills.length === 0 ? (
          <Empty>No skills yet. Create one to guide future chat sessions.</Empty>
        ) : (
          <ul className="rounded-lg border border-edge divide-y divide-edge">
            {skills.map((s) => (
              <li key={s.slug} className="px-3 py-2 flex items-center gap-2 group">
                <span className="text-ink-500">
                  <I.Wrench size={15} />
                </span>
                <button
                  onClick={() => open(s.slug)}
                  className="text-[13px] text-ink-900 hover:underline truncate text-left"
                >
                  {s.title}
                </button>
                <span className="text-[11px] text-ink-500 font-mono">{s.slug}</span>
                <button
                  onClick={() => remove(s.slug)}
                  className="ml-auto opacity-0 group-hover:opacity-100 text-ink-500 hover:text-err shrink-0"
                  title="Delete skill"
                >
                  <I.Trash size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------
function SectionIntro({ title, note }: { title: string; note: string }) {
  return (
    <div>
      <h2 className="text-base font-semibold text-ink-900">{title}</h2>
      <p className="mt-0.5 text-[13px] text-ink-500 leading-[1.5]">{note}</p>
    </div>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-edge px-3 py-6 text-center text-[13px] text-ink-500">
      {children}
    </div>
  );
}
