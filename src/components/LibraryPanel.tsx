import React, { useRef, useState } from "react";

import {
  FILE_KIND_LABEL,
  FILE_KIND_ORDER,
  formatBytes,
  useLibraryStore,
  type LibraryFile,
  type LibraryFileKind,
} from "@/store/libraryStore";

import { PropertiesPanel } from "./PropertiesPanel";

const ACCEPT = ".pdf,.md,.markdown,.schlib,.SchLib,.pcblib,.PcbLib";

export const LibraryPanel: React.FC = () => {
  const files = useLibraryStore((s) => s.files);
  const selectedFileId = useLibraryStore((s) => s.selectedFileId);
  const addFiles = useLibraryStore((s) => s.addFiles);
  const removeFile = useLibraryStore((s) => s.removeFile);
  const selectFile = useLibraryStore((s) => s.selectFile);

  const inputRef = useRef<HTMLInputElement | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const grouped = groupByKind(Object.values(files));

  const onPick = () => inputRef.current?.click();

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    addFiles(e.target.files);
    e.target.value = "";
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
  };

  return (
    <aside
      className={`library ${isDragOver ? "is-dragover" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragOver(true);
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={onDrop}
    >
      <div className="library__header">
        <h2>Libraries</h2>
        <button type="button" className="btn btn--primary" onClick={onPick}>
          Upload…
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT}
          style={{ display: "none" }}
          onChange={onInputChange}
        />
      </div>

      <div className="library__hint">
        Drop .pdf, .md, .SchLib, or .PcbLib here, or click <b>Upload…</b>.
      </div>

      <div className="library__tree">
        {FILE_KIND_ORDER.map((kind) => {
          const items = grouped[kind] ?? [];
          if (items.length === 0) return null;
          return (
            <TreeSection key={kind} title={FILE_KIND_LABEL[kind]} kind={kind}>
              {items.map((f) => (
                <TreeFile
                  key={f.id}
                  file={f}
                  selected={selectedFileId === f.id}
                  onSelect={() => selectFile(f.id)}
                  onRemove={() => removeFile(f.id)}
                />
              ))}
            </TreeSection>
          );
        })}
        {Object.keys(files).length === 0 && (
          <div className="library__empty">
            <p>No library files yet.</p>
            <p>Uploaded datasheets and library files will appear here, grouped by type.</p>
          </div>
        )}
      </div>

      <div className="library__split">
        <PropertiesPanel />
      </div>
    </aside>
  );
};

// ---------------------------------------------------------------------------

interface TreeSectionProps {
  title: string;
  kind: LibraryFileKind;
  children: React.ReactNode;
}

const TreeSection: React.FC<TreeSectionProps> = ({ title, kind, children }) => {
  const [open, setOpen] = useState(true);
  return (
    <div className={`tree-section tree-section--${kind}`}>
      <button
        type="button"
        className="tree-section__head"
        onClick={() => setOpen((o) => !o)}
      >
        <span className={`tree-caret ${open ? "is-open" : ""}`}>▸</span>
        <KindIcon kind={kind} />
        <span className="tree-section__title">{title}</span>
      </button>
      {open && <ul className="tree-section__list">{children}</ul>}
    </div>
  );
};

interface TreeFileProps {
  file: LibraryFile;
  selected: boolean;
  onSelect: () => void;
  onRemove: () => void;
}

const TreeFile: React.FC<TreeFileProps> = ({
  file,
  selected,
  onSelect,
  onRemove,
}) => (
  <li
    className={`tree-file ${selected ? "is-selected" : ""}`}
    onClick={onSelect}
  >
    <FileIcon kind={file.kind} />
    <div className="tree-file__meta">
      <div className="tree-file__name" title={file.name}>
        {file.name}
      </div>
      <div className="tree-file__sub">{formatBytes(file.size)}</div>
    </div>
    <button
      type="button"
      className="tree-file__remove"
      title="Remove"
      onClick={(e) => {
        e.stopPropagation();
        onRemove();
      }}
    >
      ×
    </button>
  </li>
);

const KindIcon: React.FC<{ kind: LibraryFileKind }> = ({ kind }) => {
  const color = kindColor(kind);
  return (
    <svg
      className="tree-section__icon"
      width="14"
      height="14"
      viewBox="0 0 16 16"
      aria-hidden
    >
      <path
        d="M1.5 3 A1.5 1.5 0 0 1 3 1.5 H6 L8 3.5 H13 A1.5 1.5 0 0 1 14.5 5 V12.5 A1.5 1.5 0 0 1 13 14 H3 A1.5 1.5 0 0 1 1.5 12.5 Z"
        fill={color}
        opacity="0.85"
      />
    </svg>
  );
};

const FileIcon: React.FC<{ kind: LibraryFileKind }> = ({ kind }) => {
  const color = kindColor(kind);
  const ext = ({
    pdf: "PDF",
    md: "MD",
    schlib: "Sch",
    pcblib: "Pcb",
    other: "•",
  } as const)[kind];
  return (
    <svg
      className="tree-file__icon"
      width="20"
      height="22"
      viewBox="0 0 20 22"
      aria-hidden
    >
      <path
        d="M2 2 H12 L18 8 V20 H2 Z"
        fill="none"
        stroke={color}
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
      <path
        d="M12 2 V8 H18"
        fill="none"
        stroke={color}
        strokeWidth="1.2"
        strokeLinejoin="round"
      />
      <text
        x="10"
        y="16.5"
        textAnchor="middle"
        fontSize="6"
        fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
        fill={color}
      >
        {ext}
      </text>
    </svg>
  );
};

function kindColor(kind: LibraryFileKind): string {
  switch (kind) {
    case "pdf":
      return "#ef5b6c";
    case "md":
      return "#9aa9bf";
    case "schlib":
      return "#4cc3ff";
    case "pcblib":
      return "#c5e36c";
    default:
      return "#7d8ba3";
  }
}

function groupByKind(
  files: LibraryFile[],
): Partial<Record<LibraryFileKind, LibraryFile[]>> {
  const out: Partial<Record<LibraryFileKind, LibraryFile[]>> = {};
  for (const f of files) {
    (out[f.kind] ??= []).push(f);
  }
  for (const k of Object.keys(out) as LibraryFileKind[]) {
    out[k]!.sort((a, b) => a.name.localeCompare(b.name));
  }
  return out;
}
