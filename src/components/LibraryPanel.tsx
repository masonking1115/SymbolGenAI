import React, { useRef, useState } from "react";

import {
  FILE_KIND_LABEL,
  FILE_KIND_ORDER,
  formatBytes,
  useLibraryStore,
  type LibraryFile,
  type LibraryFileKind,
  type LibraryFolder,
} from "@/store/libraryStore";
import { useUiStore } from "@/store/uiStore";

import { PropertiesPanel } from "./PropertiesPanel";

const ACCEPT = ".pdf,.md,.markdown,.schlib,.SchLib,.pcblib,.PcbLib";

export const LibraryPanel: React.FC = () => {
  const files = useLibraryStore((s) => s.files);
  const folders = useLibraryStore((s) => s.folders);
  const selectedFileId = useLibraryStore((s) => s.selectedFileId);
  const addFiles = useLibraryStore((s) => s.addFiles);
  const addFolder = useLibraryStore((s) => s.addFolder);
  const removeFile = useLibraryStore((s) => s.removeFile);
  const removeFolder = useLibraryStore((s) => s.removeFolder);
  const selectFile = useLibraryStore((s) => s.selectFile);

  const openInEditor = useUiStore((s) => s.openInEditor);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const looseFiles = Object.values(files).filter((f) => !f.folderId);
  const looseGrouped = groupByKind(looseFiles);
  const folderList = Object.values(folders).sort((a, b) =>
    a.name.localeCompare(b.name),
  );

  const onPickFiles = () => fileInputRef.current?.click();
  const onPickFolder = () => folderInputRef.current?.click();

  const onFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    addFiles(e.target.files);
    e.target.value = "";
  };

  const onFolderInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    addFolder(e.target.files);
    e.target.value = "";
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
  };

  // Clicking a file: select it, and if it's a .schlib, open it in Symbol Editor.
  const onClickFile = (f: LibraryFile) => {
    selectFile(f.id);
    if (f.kind === "schlib") {
      openInEditor({ type: "library", fileId: f.id });
    }
  };

  const onRemoveFile = (id: string) => {
    removeFile(id);
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
        <div className="library__upload-group">
          <button
            type="button"
            className="btn btn--primary"
            onClick={onPickFiles}
            title="Upload one or more files"
          >
            Files…
          </button>
          <button
            type="button"
            className="btn"
            onClick={onPickFolder}
            title="Upload a folder (with all contained files)"
          >
            Folder…
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPT}
            style={{ display: "none" }}
            onChange={onFileInputChange}
          />
          <input
            ref={folderInputRef}
            type="file"
            // webkitdirectory enables folder selection in Chromium/Electron.
            {...({
              webkitdirectory: "true",
              directory: "true",
              mozdirectory: "true",
            } as React.InputHTMLAttributes<HTMLInputElement>)}
            multiple
            style={{ display: "none" }}
            onChange={onFolderInputChange}
          />
        </div>
      </div>

      <div className="library__hint">
        Drop files here, or use <b>Files…</b> for individual uploads / <b>Folder…</b> for a whole directory.
      </div>

      <div className="library__tree">
        {/* Folders first */}
        {folderList.map((folder) => {
          const items = Object.values(files).filter(
            (f) => f.folderId === folder.id,
          );
          return (
            <FolderNode
              key={folder.id}
              folder={folder}
              files={items}
              selectedFileId={selectedFileId}
              onClickFile={onClickFile}
              onRemoveFile={onRemoveFile}
              onRemoveFolder={() => removeFolder(folder.id)}
            />
          );
        })}

        {/* Loose (non-folder) files grouped by kind */}
        {FILE_KIND_ORDER.map((kind) => {
          const items = looseGrouped[kind] ?? [];
          if (items.length === 0) return null;
          return (
            <TreeSection
              key={kind}
              title={FILE_KIND_LABEL[kind]}
              kind={kind}
              count={items.length}
            >
              {items.map((f) => (
                <TreeFile
                  key={f.id}
                  file={f}
                  selected={selectedFileId === f.id}
                  onClick={() => onClickFile(f)}
                  onRemove={() => onRemoveFile(f.id)}
                />
              ))}
            </TreeSection>
          );
        })}

        {Object.keys(files).length === 0 && folderList.length === 0 && (
          <div className="library__empty">
            <p>No library files yet.</p>
            <p>
              Uploaded datasheets and library files appear here, grouped by type.
              .SchLib files render in the <b>Symbol Editor</b> tab when clicked.
            </p>
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

interface FolderNodeProps {
  folder: LibraryFolder;
  files: LibraryFile[];
  selectedFileId: string | null;
  onClickFile: (f: LibraryFile) => void;
  onRemoveFile: (id: string) => void;
  onRemoveFolder: () => void;
}

const FolderNode: React.FC<FolderNodeProps> = ({
  folder,
  files,
  selectedFileId,
  onClickFile,
  onRemoveFile,
  onRemoveFolder,
}) => {
  const [open, setOpen] = useState(true);
  const grouped = groupByKind(files);
  return (
    <div className="tree-folder">
      <div className="tree-folder__head">
        <button
          type="button"
          className="tree-folder__toggle"
          onClick={() => setOpen((o) => !o)}
        >
          <span className={`tree-caret ${open ? "is-open" : ""}`}>▸</span>
          <FolderIcon />
          <span className="tree-folder__name" title={folder.name}>
            {folder.name}
          </span>
          <span className="tree-folder__count">{files.length}</span>
        </button>
        <button
          type="button"
          className="tree-folder__remove"
          title="Remove folder and all its files"
          onClick={onRemoveFolder}
        >
          ×
        </button>
      </div>
      {open && (
        <div className="tree-folder__body">
          {FILE_KIND_ORDER.map((kind) => {
            const items = grouped[kind] ?? [];
            if (items.length === 0) return null;
            return (
              <TreeSection
                key={kind}
                title={FILE_KIND_LABEL[kind]}
                kind={kind}
                count={items.length}
                nested
              >
                {items.map((f) => (
                  <TreeFile
                    key={f.id}
                    file={f}
                    selected={selectedFileId === f.id}
                    onClick={() => onClickFile(f)}
                    onRemove={() => onRemoveFile(f.id)}
                  />
                ))}
              </TreeSection>
            );
          })}
          {files.length === 0 && (
            <div className="tree-folder__empty">(empty)</div>
          )}
        </div>
      )}
    </div>
  );
};

interface TreeSectionProps {
  title: string;
  kind: LibraryFileKind;
  count: number;
  nested?: boolean;
  children: React.ReactNode;
}

const TreeSection: React.FC<TreeSectionProps> = ({
  title,
  kind,
  count,
  nested,
  children,
}) => {
  const [open, setOpen] = useState(true);
  return (
    <div
      className={`tree-section tree-section--${kind} ${nested ? "is-nested" : ""}`}
    >
      <button
        type="button"
        className="tree-section__head"
        onClick={() => setOpen((o) => !o)}
      >
        <span className={`tree-caret ${open ? "is-open" : ""}`}>▸</span>
        <KindIcon kind={kind} />
        <span className="tree-section__title">{title}</span>
        <span className="tree-section__count">{count}</span>
      </button>
      {open && <ul className="tree-section__list">{children}</ul>}
    </div>
  );
};

interface TreeFileProps {
  file: LibraryFile;
  selected: boolean;
  onClick: () => void;
  onRemove: () => void;
}

const TreeFile: React.FC<TreeFileProps> = ({
  file,
  selected,
  onClick,
  onRemove,
}) => (
  <li
    className={`tree-file ${selected ? "is-selected" : ""}`}
    onClick={onClick}
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

const FolderIcon: React.FC = () => (
  <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden>
    <path
      d="M1.5 3 A1.5 1.5 0 0 1 3 1.5 H6 L8 3.5 H13 A1.5 1.5 0 0 1 14.5 5 V12.5 A1.5 1.5 0 0 1 13 14 H3 A1.5 1.5 0 0 1 1.5 12.5 Z"
      fill="#e7c14c"
      opacity="0.95"
    />
  </svg>
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
