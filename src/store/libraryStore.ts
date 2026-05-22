import { create } from "zustand";
import { nanoid } from "nanoid";

export type LibraryFileKind = "pdf" | "md" | "schlib" | "pcblib" | "other";

export interface LibraryFile {
  id: string;
  name: string;
  kind: LibraryFileKind;
  size: number;
  /** Browser-side Blob; kept in memory for now, will be persisted later. */
  blob: Blob;
  addedAt: number;
  /** Folder this file belongs to (undefined = loose / uploaded individually). */
  folderId?: string;
  /** Path within the folder, e.g. "subdir/foo.SchLib". */
  relativePath?: string;
}

export interface LibraryFolder {
  id: string;
  name: string;
  addedAt: number;
}

/** Browser File objects gain a webkitRelativePath when picked via webkitdirectory. */
type FileWithPath = File & { webkitRelativePath?: string };

interface LibraryState {
  files: Record<string, LibraryFile>;
  folders: Record<string, LibraryFolder>;
  selectedFileId: string | null;

  addFiles: (input: FileList | File[]) => LibraryFile[];
  addFolder: (input: FileList | File[]) => {
    folder: LibraryFolder | null;
    files: LibraryFile[];
  };
  removeFile: (id: string) => void;
  removeFolder: (id: string) => void;
  selectFile: (id: string | null) => void;
  clear: () => void;
}

function classify(name: string): LibraryFileKind {
  const ext = name.toLowerCase().split(".").pop() ?? "";
  if (ext === "pdf") return "pdf";
  if (ext === "md" || ext === "markdown") return "md";
  if (ext === "schlib") return "schlib";
  if (ext === "pcblib") return "pcblib";
  return "other";
}

function topFolderName(file: FileWithPath): string {
  const rel = file.webkitRelativePath;
  if (rel && rel.includes("/")) return rel.split("/")[0];
  return "Uploaded folder";
}

export const useLibraryStore = create<LibraryState>((set) => ({
  files: {},
  folders: {},
  selectedFileId: null,

  addFiles: (input) => {
    const arr = Array.from(input);
    const created: LibraryFile[] = arr.map((f) => ({
      id: nanoid(8),
      name: f.name,
      kind: classify(f.name),
      size: f.size,
      blob: f,
      addedAt: Date.now(),
    }));
    set((s) => {
      const next = { ...s.files };
      for (const lf of created) next[lf.id] = lf;
      return { files: next };
    });
    return created;
  },

  addFolder: (input) => {
    const arr = Array.from(input) as FileWithPath[];
    if (arr.length === 0) return { folder: null, files: [] };
    const folderId = nanoid(8);
    const folder: LibraryFolder = {
      id: folderId,
      name: topFolderName(arr[0]),
      addedAt: Date.now(),
    };
    const created: LibraryFile[] = arr.map((f) => ({
      id: nanoid(8),
      name: f.name,
      kind: classify(f.name),
      size: f.size,
      blob: f,
      addedAt: Date.now(),
      folderId,
      relativePath: f.webkitRelativePath || f.name,
    }));
    set((s) => {
      const nextFiles = { ...s.files };
      for (const lf of created) nextFiles[lf.id] = lf;
      return {
        folders: { ...s.folders, [folderId]: folder },
        files: nextFiles,
      };
    });
    return { folder, files: created };
  },

  removeFile: (id) =>
    set((s) => {
      const next = { ...s.files };
      delete next[id];
      return {
        files: next,
        selectedFileId: s.selectedFileId === id ? null : s.selectedFileId,
      };
    }),

  removeFolder: (id) =>
    set((s) => {
      const folders = { ...s.folders };
      delete folders[id];
      const files = { ...s.files };
      for (const fid of Object.keys(files)) {
        if (files[fid].folderId === id) delete files[fid];
      }
      return {
        folders,
        files,
        selectedFileId:
          s.selectedFileId && !files[s.selectedFileId]
            ? null
            : s.selectedFileId,
      };
    }),

  selectFile: (id) => set({ selectedFileId: id }),

  clear: () => set({ files: {}, folders: {}, selectedFileId: null }),
}));

/** Human-readable file size, e.g. "12.4 kB" or "3.1 MB". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} kB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export const FILE_KIND_LABEL: Record<LibraryFileKind, string> = {
  schlib: "Schematic Library Documents",
  pcblib: "PCB Library Documents",
  pdf: "Datasheets",
  md: "Notes & Markdown",
  other: "Other",
};

/** Display order for sections in the library tree. */
export const FILE_KIND_ORDER: LibraryFileKind[] = [
  "schlib",
  "pcblib",
  "pdf",
  "md",
  "other",
];
