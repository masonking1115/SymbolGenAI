// Thin React wrapper around CodeMirror 6 (no react-codemirror dep — we drive
// the EditorView directly). Syntax highlighting + line numbers per file
// extension. Controlled-ish: the parent owns `value`; we push external changes
// into the view and report edits via onChange. `readOnly` renders a viewer.
import { useEffect, useRef } from "react";
import { EditorState, Compartment } from "@codemirror/state";
import { EditorView, keymap, lineNumbers, highlightActiveLine,
  highlightActiveLineGutter } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { syntaxHighlighting, defaultHighlightStyle, indentOnInput,
  bracketMatching } from "@codemirror/language";
import { searchKeymap, highlightSelectionMatches } from "@codemirror/search";
import { markdown } from "@codemirror/lang-markdown";
import { yaml } from "@codemirror/lang-yaml";
import { json } from "@codemirror/lang-json";

// Pick a language extension from the filename. CSV/TSV/txt get no language
// (plain text is fine — still gets line numbers + the editor chrome).
function langFor(filename: string) {
  const ext = filename.toLowerCase().split(".").pop() ?? "";
  if (ext === "md" || ext === "markdown") return markdown();
  if (ext === "yaml" || ext === "yml") return yaml();
  if (ext === "json") return json();
  return [];
}

export function CodeEditor({
  value,
  filename,
  readOnly = false,
  onChange,
  onSave,
}: {
  value: string;
  filename: string;
  readOnly?: boolean;
  onChange?: (v: string) => void;
  onSave?: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  // Keep the latest onChange/onSave without re-creating the editor each render.
  const onChangeRef = useRef(onChange);
  const onSaveRef = useRef(onSave);
  onChangeRef.current = onChange;
  onSaveRef.current = onSave;
  const langComp = useRef(new Compartment());
  const roComp = useRef(new Compartment());

  // Create the view once.
  useEffect(() => {
    if (!host.current) return;
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightActiveLine(),
        history(),
        indentOnInput(),
        bracketMatching(),
        highlightSelectionMatches(),
        syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
        keymap.of([
          // Cmd/Ctrl-S to save (preventDefault so the browser save dialog
          // doesn't fire).
          { key: "Mod-s", preventDefault: true, run: () => { onSaveRef.current?.(); return true; } },
          ...defaultKeymap, ...historyKeymap, ...searchKeymap, indentWithTab,
        ]),
        langComp.current.of(langFor(filename)),
        roComp.current.of(EditorState.readOnly.of(readOnly)),
        EditorView.editable.of(!readOnly),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) onChangeRef.current?.(u.state.doc.toString());
        }),
        EditorView.theme({
          "&": { height: "100%", fontSize: "12.5px" },
          ".cm-scroller": { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", overflow: "auto" },
          ".cm-content": { padding: "8px 0" },
          "&.cm-focused": { outline: "none" },
          ".cm-gutters": { background: "#FBFBFD", border: "none", color: "#9CA3AF" },
        }),
      ],
    });
    const v = new EditorView({ state, parent: host.current });
    view.current = v;
    return () => { v.destroy(); view.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Push external value changes (e.g. switching files) into the view without
  // clobbering local edits when they already match.
  useEffect(() => {
    const v = view.current;
    if (!v) return;
    const cur = v.state.doc.toString();
    if (cur !== value) {
      v.dispatch({ changes: { from: 0, to: cur.length, insert: value } });
    }
  }, [value]);

  // Reconfigure language when the filename changes.
  useEffect(() => {
    view.current?.dispatch({ effects: langComp.current.reconfigure(langFor(filename)) });
  }, [filename]);

  // Reconfigure read-only when it toggles.
  useEffect(() => {
    view.current?.dispatch({
      effects: roComp.current.reconfigure(EditorState.readOnly.of(readOnly)),
    });
  }, [readOnly]);

  return <div ref={host} className="h-full overflow-hidden" />;
}
