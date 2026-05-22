import React from "react";

import { getSymbol } from "@/lib/symbolLibrary";
import { useSchematicStore } from "@/store/schematicStore";

export const PropertiesPanel: React.FC = () => {
  const selection = useSchematicStore((s) => s.selection);
  const symbols = useSchematicStore((s) => s.schematic.symbols);
  const wires = useSchematicStore((s) => s.schematic.wires);

  const symCount = Object.keys(symbols).length;
  const wireCount = Object.keys(wires).length;
  const totalSelected = selection.symbolIds.length + selection.wireIds.length;

  return (
    <div className="properties">
      <h2>Properties</h2>

      {totalSelected === 0 && (
        <div className="properties__empty">
          <p>Select a symbol or wire to edit its properties.</p>
          <p className="properties__stats">
            {symCount} symbol{symCount === 1 ? "" : "s"} · {wireCount} wire
            {wireCount === 1 ? "" : "s"}
          </p>
        </div>
      )}

      {selection.symbolIds.length === 1 && selection.wireIds.length === 0 && (
        <SymbolEditor id={selection.symbolIds[0]} />
      )}

      {totalSelected > 1 && (
        <div className="properties__empty">
          <p>{totalSelected} items selected.</p>
          <p>
            Symbols: {selection.symbolIds.length} · Wires:{" "}
            {selection.wireIds.length}
          </p>
        </div>
      )}

      {totalSelected === 1 && selection.wireIds.length === 1 && (
        <div className="properties__empty">
          <p>Wire selected. Use Delete to remove.</p>
        </div>
      )}
    </div>
  );
};

const SymbolEditor: React.FC<{ id: string }> = ({ id }) => {
  const sym = useSchematicStore((s) => s.schematic.symbols[id]);
  const updateSymbol = useSchematicStore((s) => s.updateSymbol);
  if (!sym) return null;
  const def = getSymbol(sym.symbolId);
  if (!def) return null;

  return (
    <>
      <div className="properties__title">{def.name}</div>
      <div className="properties__field">
        <label>Designator</label>
        <input
          value={sym.designator}
          onChange={(e) => updateSymbol(sym.id, { designator: e.target.value })}
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
          <label>Rot</label>
          <input value={`${sym.rotation}°`} readOnly />
        </div>
      </div>
    </>
  );
};
