// Right-hand pane for the Design Resources tab: opens whatever resource file
// the user clicked. Text files (.md/.csv/.txt/.json/.yaml + skills) open in a
// CodeMirror editor with Save/dirty-state; PDFs embed inline (scroll + zoom via
// the browser viewer); other binaries (xlsx/docx/pptx/odt) show an open/
// download card. Closing is owned by the parent (setOpen(null)).
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { I } from "./Icon";
import { CodeEditor } from "./CodeEditor";

// What the parent hands us when a file row is clicked.
export interface OpenFile {
  // Which resource family — picks the content/save endpoints. "active_req" is
  // the project-root design_requirements.md the pipeline reads.
  kind: "requirement" | "bom" | "skill" | "datasheet" | "active_req";
  name: string;          // display name / filename (skills: the slug)
  title?: string;        // optional nicer title (skills)
  url: string;           // download/serve URL (used for binary + the link)
}

const TEXT_EXTS = new Set([
  "md", "markdown", "txt", "csv", "tsv", "rtf", "json", "yaml", "yml",
]);

function extOf(name: string): string {
  return name.toLowerCase().split(".").pop() ?? "";
}
// Skills are always markdown; otherwise classify by extension.
function isText(f: OpenFile): boolean {
  if (f.kind === "skill") return true;
  return TEXT_EXTS.has(extOf(f.name));
}
function isPdf(f: OpenFile): boolean {
  return extOf(f.name) === "pdf";
}

export function ResourceEditor({
  file,
  onClose,
  onSaved,
}: {
  file: OpenFile;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const text = isText(file);

  // ---- text-editor state ----
  const [loaded, setLoaded] = useState<string | null>(null);   // server copy
  const [draft, setDraft] = useState<string>("");
  const [status, setStatus] = useState<"idle" | "loading" | "saving" | "error">("idle");
  const [msg, setMsg] = useState<string>("");
  const dirty = loaded !== null && draft !== loaded;

  // Identify the open file so effects re-run on switch. (skills keyed by name
  // which is the slug.)
  const fileKey = `${file.kind}:${file.name}`;

  const fetchText = useCallback(async () => {
    setStatus("loading"); setMsg("");
    try {
      let content = "";
      if (file.kind === "requirement") content = (await api.requirementContent(file.name)).content;
      else if (file.kind === "bom") content = (await api.bomContent(file.name)).content;
      else if (file.kind === "skill") content = (await api.resourcesSkill(file.name)).content;
      else if (file.kind === "active_req") content = (await api.activeRequirement()).content;
      setLoaded(content); setDraft(content); setStatus("idle");
    } catch (e) {
      setStatus("error");
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }, [file.kind, file.name]);

  useEffect(() => {
    setLoaded(null); setDraft(""); setMsg("");
    if (text) fetchText();
    else setStatus("idle");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileKey]);

  const save = useCallback(async () => {
    if (!dirty || status === "saving") return;
    setStatus("saving"); setMsg("");
    try {
      if (file.kind === "requirement") await api.saveRequirementContent(file.name, draft);
      else if (file.kind === "bom") await api.saveBomContent(file.name, draft);
      else if (file.kind === "skill") await api.saveSkill(file.title || file.name, draft, file.name);
      else if (file.kind === "active_req") await api.saveActiveRequirement(draft);
      setLoaded(draft); setStatus("idle"); setMsg("saved");
      onSaved?.();
      // clear the "saved" flash shortly after
      window.setTimeout(() => setMsg((m) => (m === "saved" ? "" : m)), 1800);
    } catch (e) {
      setStatus("error");
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }, [dirty, status, file, draft, onSaved]);

  return (
    <div className="h-full flex flex-col min-h-0 border-l border-edge bg-white">
      {/* header bar */}
      <div className="shrink-0 flex items-center gap-2 px-3 h-10 border-b border-edge bg-rail/30">
        <I.Datasheet size={14} className="text-ink-500 shrink-0" />
        <span className="text-[12.5px] font-medium text-ink-900 truncate" title={file.name}>
          {file.title || file.name}
        </span>
        {text && dirty && <span className="w-1.5 h-1.5 rounded-full bg-warn shrink-0" title="unsaved changes" />}
        <div className="ml-auto flex items-center gap-1.5">
          {text && (
            <button
              onClick={save}
              disabled={!dirty || status === "saving"}
              className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md bg-ink-900 text-white text-[11.5px] font-medium hover:bg-black disabled:opacity-40"
              title="Save (⌘/Ctrl-S)"
            >
              <I.Check size={12} />
              {status === "saving" ? "Saving…" : dirty ? "Save" : "Saved"}
            </button>
          )}
          <a
            href={file.url}
            target="_blank"
            rel="noreferrer"
            className="h-7 px-2 inline-flex items-center gap-1 rounded-md border border-edge text-ink-600 text-[11.5px] hover:border-ink-300"
            title="Open in a new tab"
          >
            <I.External size={12} />
          </a>
          <button
            onClick={onClose}
            className="h-7 w-7 inline-flex items-center justify-center rounded-md text-ink-500 hover:bg-rail hover:text-ink-900 text-[15px] leading-none"
            title="Close"
          >
            ✕
          </button>
        </div>
      </div>

      {/* status line */}
      {msg && (
        <div className={"shrink-0 px-3 py-1 text-[11px] " +
          (status === "error" ? "text-err bg-err/[0.05]" : "text-ok bg-ok/[0.05]")}>
          {msg}
        </div>
      )}

      {/* body */}
      <div className="flex-1 min-h-0">
        {text ? (
          status === "loading" ? (
            <div className="p-4 text-[12px] text-ink-400">loading…</div>
          ) : status === "error" ? (
            <div className="p-4 text-[12px] text-err">{msg || "could not load file"}</div>
          ) : (
            <CodeEditor value={draft} filename={file.name} onChange={setDraft} onSave={save} />
          )
        ) : isPdf(file) ? (
          // Browser-native PDF viewer: scroll + zoom for free.
          <iframe title={file.name} src={file.url} className="w-full h-full border-0" />
        ) : (
          <BinaryCard file={file} />
        )}
      </div>
    </div>
  );
}

// Non-PDF binary (xlsx/xls/docx/pptx/odt): can't edit or embed reliably — offer
// open + download.
function BinaryCard({ file }: { file: OpenFile }) {
  return (
    <div className="h-full grid place-items-center p-6 text-center">
      <div className="max-w-[360px]">
        <div className="text-sm text-ink-800 font-medium">{file.name}</div>
        <div className="text-[12px] text-ink-500 mt-1.5">
          This is a binary <span className="font-mono">.{extOf(file.name)}</span> file — it can't be
          edited as text. Open it in a new tab or download it.
        </div>
        <div className="mt-3 flex items-center justify-center gap-2">
          <a
            href={file.url}
            target="_blank"
            rel="noreferrer"
            className="h-8 px-3 inline-flex items-center gap-1.5 rounded-md bg-ink-900 text-white text-xs font-medium hover:bg-black"
          >
            <I.External size={13} /> Open
          </a>
          <a
            href={file.url}
            download={file.name}
            className="h-8 px-3 inline-flex items-center gap-1.5 rounded-md border border-edge text-ink-700 text-xs hover:border-ink-300"
          >
            <I.Upload size={13} className="rotate-180" /> Download
          </a>
        </div>
      </div>
    </div>
  );
}
