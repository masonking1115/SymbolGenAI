import React from "react";

import { getSymbol } from "@/lib/symbolLibrary";
import { useSchematicStore } from "@/store/schematicStore";

export const PropertiesPanel: React.FC = () => {
  const selection = useSchematicStore((s) => s.selection);
  const symbols = useSchematicStore((s) => s.schematic.symbols);
  const wires = useSchematicStore((s) => s.schematic.wires);
  const updateSymbol = useSchematicStore((s) => s.updateSymbol);

  const symCount = Object.keys(symbols).length;
  const wireCount = Object.keys(wires).length;

  if (selection.symbolIds.length === 0 && selection.wireIds.length === 0) {
    return (
      <aside className="properties">
        <h2>Properties</h2>
        <div className="properties__empty">
          <p>Nothing selected.</p>
          <ul>
            <li>Click a symbol in the palette, then click on the canvas to place it.</li>
            <li>Press <kbd>W</kbd> or use the toolbar to draw wires.</li>
            <li>Press <kbd>R</kbd> to rotate a selected (or being-placed) symbol.</li>
            <li>Drag with the middle mouse button or hold <kbd>Space</kbd> to pan.</li>
            <li>Use the scroll wheel to zoom toward the cursor.</li>
          </ul>
          <p className="properties__stats">
            {symCount} symbol{symCount === 1 ? "" : "s"} · {wireCount} wire
            {wireCount === 1 ? "" : "s"}
          </p>
        </div>
      </aside>
    );
  }

  if (selection.symbolIds.length === 1) {
    const sym = symbols[selection.symbolIds[0]];
    if (!sym) return null;
    const def = getSymbol(sym.symbolId);
    if (!def) return null;
    return (
      <aside className="properties">
        <h2>{def.name}</h2>
        <div className="properties__field">
          <label>Designator</label>
          <input
            value={sym.designator}
            onChange={(e) =>
              updateSymbol(sym.id, { designator: e.target.value })
            }
          />
        </div>
        <div className="properties__field">
          <label>Value</label>
          <input
            value={sym.value}
            onChange={(e) => updateSymbol(sym.id, { value: e.target.value })}
          />
        </div>
        <div className="properties__row">
          <div className="properties__field">
            <label>X</label>
            <input
              type="number"
              value={sym.position.x}
              onChange={(e) =>
                updateSymbol(sym.id, {
                  position: { ...sym.position, x: Number(e.target.value) },
                })
              }
            />
          </div>
          <div className="properties__field">
            <label>Y</label>
            <input
              type="number"
              value={sym.position.y}
              onChange={(e) =>
                updateSymbol(sym.id, {
                  position: { ...sym.position, y: Number(e.target.value) },
                })
              }
            />
          </div>
          <div className="properties__field">
            <label>Rotation</label>
            <input value={`${sym.rotation}°`} readOnly />
          </div>
        </div>
        <div className="properties__pins">
          <h3>Pins</h3>
          <ul>
            {def.pins.map((p) => (
              <li key={p.id}>
                <strong>{p.id}</strong> {p.name}
                <span className="properties__pin-type">
                  {p.electricalType ?? "passive"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </aside>
    );
  }

  const total = selection.symbolIds.length + selection.wireIds.length;
  return (
    <aside className="properties">
      <h2>{total} items selected</h2>
      <p>
        Symbols: {selection.symbolIds.length} · Wires:{" "}
        {selection.wireIds.length}
      </p>
      <p>
        Use the toolbar to rotate or delete. Multi-edit of properties is not
        supported yet.
      </p>
    </aside>
  );
};
