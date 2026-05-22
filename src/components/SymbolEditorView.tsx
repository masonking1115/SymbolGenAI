import React from "react";

import { getSymbol } from "@/lib/symbolLibrary";
import { useLibraryStore } from "@/store/libraryStore";
import { useUiStore } from "@/store/uiStore";

import { PlaceToolbar } from "./PlaceToolbar";
import { SymbolEditorCanvas } from "./SymbolEditorCanvas";

export const SymbolEditorView: React.FC = () => {
  const editing = useUiStore((s) => s.editingSource);
  const file = useLibraryStore((s) =>
    editing?.type === "library" ? s.files[editing.fileId] : undefined,
  );
  const def =
    editing?.type === "builtin" ? getSymbol(editing.symbolId) : undefined;

  return (
    <>
      <PlaceToolbar />
      <div className="editor__canvas">
        {def && <SymbolEditorCanvas def={def} />}
        {file && file.kind === "schlib" && <SchLibPlaceholder name={file.name} />}
        {!def && !file && <EmptyEditorState />}
        {file && file.kind !== "schlib" && (
          <UnsupportedFile name={file.name} kind={file.kind} />
        )}
      </div>
    </>
  );
};

const EmptyEditorState: React.FC = () => (
  <div className="editor-empty">
    <div className="editor-empty__icon">⌬</div>
    <h2>Symbol Editor</h2>
    <p>
      Pick a part from the toolbar above, or upload a <code>.SchLib</code> file in
      the Libraries panel and select it to edit.
    </p>
  </div>
);

const SchLibPlaceholder: React.FC<{ name: string }> = ({ name }) => (
  <div className="editor-empty">
    <div className="editor-empty__icon editor-empty__icon--pending">…</div>
    <h2>{name}</h2>
    <p>
      Awaiting the <code>.SchLib</code> parser (milestone 2). File metadata is
      visible on the Properties panel to the right.
    </p>
  </div>
);

const UnsupportedFile: React.FC<{ name: string; kind: string }> = ({
  name,
  kind,
}) => (
  <div className="editor-empty">
    <div className="editor-empty__icon editor-empty__icon--warn">!</div>
    <h2>{name}</h2>
    <p>
      The Symbol Editor only renders <code>.SchLib</code> files. This file is
      a <strong>{kind}</strong> — preview it in a future viewer.
    </p>
  </div>
);
