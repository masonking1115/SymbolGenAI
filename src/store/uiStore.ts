import { create } from "zustand";

export type ViewKey = "schematic" | "symbol-editor";

/**
 * What the Symbol Editor is currently showing.
 * - `builtin`: one of the library catalog symbols (resistor, capacitor, ...)
 * - `library`: an uploaded library file (.SchLib, etc.) — actual rendering
 *   waits on the parser landing in milestone 2.
 */
export type EditingSource =
  | { type: "builtin"; symbolId: string }
  | { type: "library"; fileId: string }
  | null;

interface UiState {
  activeView: ViewKey;
  editingSource: EditingSource;

  setActiveView: (v: ViewKey) => void;
  openInEditor: (src: EditingSource) => void;
  clearEditor: () => void;
}

export const useUiStore = create<UiState>((set) => ({
  activeView: "schematic",
  editingSource: null,

  setActiveView: (v) => set({ activeView: v }),

  openInEditor: (src) =>
    set({ editingSource: src, activeView: "symbol-editor" }),

  clearEditor: () => set({ editingSource: null }),
}));
