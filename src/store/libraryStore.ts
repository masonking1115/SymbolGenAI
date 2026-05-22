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
}

interface LibraryState {
  files: Record<string, LibraryFile>;
  selectedFileId: string | null;
  addFiles: (input: FileList | File[]) => LibraryFile[];
  removeFile: (id: string) => void;
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

export const useLibraryStore = create<LibraryState>((set) => ({
  files: {},
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

  removeFile: (id) =>
    set((s) => {
      const next = { ...s.files };
      delete next[id];
      return {
        files: next,
        selectedFileId: s.selectedFileId === id ? null : s.selectedFileId,
      };
    }),

  selectFile: (id) => set({ selectedFileId: id }),

  clear: () => set({ files: {}, selectedFileId: null }),
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
