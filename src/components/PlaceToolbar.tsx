import React from "react";

import { getSymbol, SYMBOL_LIBRARY } from "@/lib/symbolLibrary";
import { useSchematicStore } from "@/store/schematicStore";
import { useUiStore } from "@/store/uiStore";
import type { SymbolDefinition } from "@/types/schematic";

/**
 * Order of the quick-place buttons. Matches the Altium convention: passives
 * first, then active parts, then power, then connectors.
 */
const PLACE_ORDER = [
  "resistor",
  "capacitor",
  "inductor",
  "diode",
  "led",
  "bjt-npn",
  "bjt-pnp",
  "gnd",
  "vcc",
  "hdr-1x2",
] as const;

export const PlaceToolbar: React.FC = () => {
  const tool = useSchematicStore((s) => s.tool);
  const placingSymbolId = useSchematicStore((s) => s.placingSymbolId);
  const beginPlacement = useSchematicStore((s) => s.beginPlacement);
  const cancelPlacement = useSchematicStore((s) => s.cancelPlacement);
  const setTool = useSchematicStore((s) => s.setTool);

  const activeView = useUiStore((s) => s.activeView);
  const editing = useUiStore((s) => s.editingSource);
  const openInEditor = useUiStore((s) => s.openInEditor);

  const isEditorMode = activeView === "symbol-editor";

  const items = PLACE_ORDER.map((id) => getSymbol(id)).filter(
    (s): s is SymbolDefinition => !!s,
  );
  const extras = SYMBOL_LIBRARY.filter(
    (s) => !PLACE_ORDER.includes(s.id as (typeof PLACE_ORDER)[number]),
  );

  const editingBuiltinId =
    editing?.type === "builtin" ? editing.symbolId : null;

  const isButtonActive = (id: string) =>
    isEditorMode ? editingBuiltinId === id : placingSymbolId === id;

  const onButton = (def: SymbolDefinition) => {
    if (isEditorMode) {
      openInEditor({ type: "builtin", symbolId: def.id });
    } else if (placingSymbolId === def.id) {
      cancelPlacement();
    } else {
      beginPlacement(def.id);
    }
  };

  const hint = isEditorMode
    ? editing
      ? "Pick another part to edit, or select a .SchLib from the library"
      : "Pick a built-in part to edit, or select a .SchLib from the library"
    : placingSymbolId
      ? "Click on the canvas to place — R rotates, Esc cancels"
      : tool === "wire"
        ? "Click a pin to start a wire — Tab flips bend"
        : "Pick a part above, or hit W for wire mode";

  return (
    <div className="placebar">
      <div className="placebar__label">{isEditorMode ? "Edit" : "Place"}</div>
      <div className="placebar__group">
        {items.map((def) => (
          <PlaceButton
            key={def.id}
            def={def}
            active={isButtonActive(def.id)}
            onClick={() => onButton(def)}
            mode={isEditorMode ? "edit" : "place"}
          />
        ))}
        {extras.map((def) => (
          <PlaceButton
            key={def.id}
            def={def}
            active={isButtonActive(def.id)}
            onClick={() => onButton(def)}
            mode={isEditorMode ? "edit" : "place"}
          />
        ))}
      </div>

      {!isEditorMode && (
        <>
          <div className="placebar__divider" />
          <button
            type="button"
            className={`placebar__tool ${tool === "wire" ? "is-active" : ""}`}
            title="Wire (W) — click pins to connect"
            onClick={() => setTool(tool === "wire" ? "select" : "wire")}
          >
            <WireIcon />
            <span>Wire</span>
          </button>
        </>
      )}

      <div className="placebar__spacer" />
      <div className="placebar__hint">{hint}</div>
    </div>
  );
};

interface PlaceButtonProps {
  def: SymbolDefinition;
  active: boolean;
  onClick: () => void;
  mode: "place" | "edit";
}

const PlaceButton: React.FC<PlaceButtonProps> = ({
  def,
  active,
  onClick,
  mode,
}) => {
  const pad = 8;
  const vb = `${def.bbox.x - pad} ${def.bbox.y - pad} ${def.bbox.width + pad * 2} ${def.bbox.height + pad * 2}`;
  const title =
    mode === "edit"
      ? `Edit ${def.name} (${def.refPrefix}${def.defaultValue ? " · " + def.defaultValue : ""})`
      : `Place ${def.name} (${def.refPrefix}${def.defaultValue ? " · " + def.defaultValue : ""})`;
  return (
    <button
      type="button"
      className={`placebar__btn ${active ? "is-active" : ""}`}
      onClick={onClick}
      title={title}
    >
      <svg viewBox={vb} className="placebar__icon" aria-hidden>
        {def.body}
        {def.pins.map((p) => (
          <circle key={p.id} cx={p.x} cy={p.y} r={1.5} className="pin-dot" />
        ))}
      </svg>
      <span className="placebar__btn-label">{def.refPrefix}</span>
    </button>
  );
};

const WireIcon: React.FC = () => (
  <svg
    viewBox="0 0 24 24"
    width="20"
    height="20"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M3 17 L9 17 L9 7 L15 7 L15 17 L21 17" />
    <circle cx="3" cy="17" r="1.6" fill="currentColor" />
    <circle cx="21" cy="17" r="1.6" fill="currentColor" />
  </svg>
);
