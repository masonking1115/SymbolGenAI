import React from "react";

import { useSchematicStore } from "@/store/schematicStore";
import type { Tool } from "@/types/schematic";

const TOOLS: { id: Tool; label: string; hint: string }[] = [
  { id: "select", label: "Select", hint: "S" },
  { id: "wire", label: "Wire", hint: "W" },
  { id: "pan", label: "Pan", hint: "Hold Space" },
];

export const Toolbar: React.FC = () => {
  const tool = useSchematicStore((s) => s.tool);
  const setTool = useSchematicStore((s) => s.setTool);
  const placingSymbolId = useSchematicStore((s) => s.placingSymbolId);
  const cancelPlacement = useSchematicStore((s) => s.cancelPlacement);
  const deleteSelection = useSchematicStore((s) => s.deleteSelection);
  const selection = useSchematicStore((s) => s.selection);
  const rotatePlacement = useSchematicStore((s) => s.rotatePlacement);
  const rotateSymbol = useSchematicStore((s) => s.rotateSymbol);
  const viewport = useSchematicStore((s) => s.viewport);
  const setViewport = useSchematicStore((s) => s.setViewport);

  const hasSelection =
    selection.symbolIds.length + selection.wireIds.length > 0;

  return (
    <header className="toolbar">
      <div className="toolbar__brand">
        <span className="toolbar__logo">⚡︎</span>
        <span>Symbol Library AI</span>
        <span className="toolbar__chip">Schematic MVP</span>
      </div>

      <div className="toolbar__group">
        {TOOLS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={["btn", tool === t.id ? "is-active" : ""].join(" ")}
            onClick={() => setTool(t.id)}
            title={`${t.label} (${t.hint})`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="toolbar__group">
        <button
          type="button"
          className="btn"
          onClick={() => {
            if (placingSymbolId) rotatePlacement();
            else selection.symbolIds.forEach(rotateSymbol);
          }}
          disabled={!placingSymbolId && selection.symbolIds.length === 0}
          title="Rotate 90° (R)"
        >
          Rotate
        </button>
        <button
          type="button"
          className="btn"
          onClick={deleteSelection}
          disabled={!hasSelection}
          title="Delete (Del)"
        >
          Delete
        </button>
        {placingSymbolId && (
          <button
            type="button"
            className="btn btn--warn"
            onClick={cancelPlacement}
            title="Cancel placement (Esc)"
          >
            Cancel placement
          </button>
        )}
      </div>

      <div className="toolbar__spacer" />

      <div className="toolbar__group">
        <button
          type="button"
          className="btn"
          onClick={() => setViewport({ panX: 0, panY: 0, zoom: 1.5 })}
          title="Reset view"
        >
          Reset view
        </button>
        <span className="toolbar__zoom">{Math.round(viewport.zoom * 100)}%</span>
      </div>
    </header>
  );
};
