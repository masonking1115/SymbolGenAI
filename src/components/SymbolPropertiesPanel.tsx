import React, { useState } from "react";

import { getSymbol } from "@/lib/symbolLibrary";
import { formatBytes, useLibraryStore } from "@/store/libraryStore";
import { useUiStore } from "@/store/uiStore";
import type { PinDef, SymbolDefinition } from "@/types/schematic";

type Tab = "general" | "pins";

/**
 * Right-side panel sitting between the symbol editor canvas and the chat.
 * Mirrors Altium's component-properties panel: General + Pins tabs.
 */
export const SymbolPropertiesPanel: React.FC = () => {
  const editing = useUiStore((s) => s.editingSource);
  const fileMap = useLibraryStore((s) => s.files);
  const folderMap = useLibraryStore((s) => s.folders);
  const [tab, setTab] = useState<Tab>("general");

  const def =
    editing?.type === "builtin" ? getSymbol(editing.symbolId) : undefined;
  const file =
    editing?.type === "library" ? fileMap[editing.fileId] : undefined;
  const folder = file?.folderId ? folderMap[file.folderId] : undefined;

  return (
    <aside className="sym-props">
      <header className="sym-props__head">
        <h2>Properties</h2>
        <div className="sym-props__head-sub">
          {def
            ? `Built-in · ${def.name}`
            : file
              ? `Library · ${file.name}`
              : "Nothing selected"}
        </div>
      </header>

      <div className="sym-props__tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "general"}
          className={`sym-props__tab ${tab === "general" ? "is-active" : ""}`}
          onClick={() => setTab("general")}
        >
          General
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "pins"}
          className={`sym-props__tab ${tab === "pins" ? "is-active" : ""}`}
          onClick={() => setTab("pins")}
        >
          Pins {def ? `(${def.pins.length})` : ""}
        </button>
      </div>

      <div className="sym-props__body">
        {!editing && <EmptyState />}
        {def && tab === "general" && <GeneralForBuiltin def={def} />}
        {def && tab === "pins" && <PinsTable pins={def.pins} />}
        {file && tab === "general" && (
          <GeneralForLibraryFile
            fileName={file.name}
            size={file.size}
            relativePath={file.relativePath}
            folderName={folder?.name}
          />
        )}
        {file && tab === "pins" && <PinsPending />}
      </div>
    </aside>
  );
};

// ----- Empty state ---------------------------------------------------------

const EmptyState: React.FC = () => (
  <div className="sym-props__empty">
    <p>Select a .SchLib in the Libraries panel, or pick a built-in part from the toolbar above the canvas.</p>
  </div>
);

// ----- General tab: built-in -----------------------------------------------

const GeneralForBuiltin: React.FC<{ def: SymbolDefinition }> = ({ def }) => (
  <div className="sym-props__form">
    <Field label="Design Item ID" value={`SYM_${def.id.toUpperCase()}`} />
    <Field label="Designator" value={`${def.refPrefix}?`} />
    <Field label="Comment" value={def.defaultValue ?? ""} placeholder="(none)" />
    <RowFields>
      <Field label="Part" value="1" small />
      <Field label="of Parts" value="1" small />
    </RowFields>
    <Field
      label="Description"
      value={`${def.category} · ${def.name}`}
      multiline
    />
    <Field label="Type" value="Standard" readonly />
    <Section title="Bounding box">
      <RowFields>
        <Field label="X" value={String(def.bbox.x)} small />
        <Field label="Y" value={String(def.bbox.y)} small />
        <Field label="W" value={String(def.bbox.width)} small />
        <Field label="H" value={String(def.bbox.height)} small />
      </RowFields>
    </Section>
    <p className="sym-props__note">
      Built-in symbols are defined in code today; edits aren't persisted yet.
      In milestone 2 these will load from the SQLite library and be saveable
      back to .SchLib.
    </p>
  </div>
);

// ----- General tab: uploaded library file ----------------------------------

const GeneralForLibraryFile: React.FC<{
  fileName: string;
  size: number;
  relativePath?: string;
  folderName?: string;
}> = ({ fileName, size, relativePath, folderName }) => (
  <div className="sym-props__form">
    <Field label="File name" value={fileName} readonly />
    <Field label="Folder" value={folderName ?? "—"} readonly />
    {relativePath && (
      <Field label="Path in folder" value={relativePath} readonly />
    )}
    <Field label="Size" value={formatBytes(size)} readonly />
    <Field label="Type" value="Schematic Library (.SchLib)" readonly />
    <p className="sym-props__note">
      The .SchLib parser lands in milestone 2. Once it does, this panel will
      populate Design Item ID, Designator, Comment, Description, parameters,
      and the pin list from the file content.
    </p>
  </div>
);

// ----- Pins tab ------------------------------------------------------------

const PinsTable: React.FC<{ pins: PinDef[] }> = ({ pins }) => (
  <div className="sym-props__pins">
    <div className="sym-props__pins-head">
      <span>ID</span>
      <span>Name</span>
      <span>X</span>
      <span>Y</span>
      <span>Type</span>
    </div>
    {pins.map((p) => (
      <div key={p.id} className="sym-props__pins-row">
        <span className="mono">{p.id}</span>
        <span>{p.name}</span>
        <span className="mono">{p.x}</span>
        <span className="mono">{p.y}</span>
        <span className="sym-props__pin-type">
          {p.electricalType ?? "passive"}
        </span>
      </div>
    ))}
    {pins.length === 0 && (
      <div className="sym-props__empty">
        <p>This symbol has no pins.</p>
      </div>
    )}
  </div>
);

const PinsPending: React.FC = () => (
  <div className="sym-props__empty">
    <p>Pin list will appear here once the .SchLib parser lands (milestone 2).</p>
  </div>
);

// ----- Form primitives ------------------------------------------------------

interface FieldProps {
  label: string;
  value: string;
  placeholder?: string;
  readonly?: boolean;
  multiline?: boolean;
  small?: boolean;
}

const Field: React.FC<FieldProps> = ({
  label,
  value,
  placeholder,
  readonly,
  multiline,
  small,
}) => {
  // Edits are in-memory only for now; using state means the inputs work
  // properly without needing a persisted backing store.
  const [val, setVal] = useState(value);
  React.useEffect(() => setVal(value), [value]);
  return (
    <label className={`sym-props__field ${small ? "is-small" : ""}`}>
      <span className="sym-props__label">{label}</span>
      {multiline ? (
        <textarea
          rows={2}
          value={val}
          placeholder={placeholder}
          readOnly={readonly}
          onChange={(e) => setVal(e.target.value)}
        />
      ) : (
        <input
          value={val}
          placeholder={placeholder}
          readOnly={readonly}
          onChange={(e) => setVal(e.target.value)}
        />
      )}
    </label>
  );
};

const RowFields: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="sym-props__row">{children}</div>
);

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({
  title,
  children,
}) => (
  <div className="sym-props__section">
    <div className="sym-props__section-head">{title}</div>
    {children}
  </div>
);
