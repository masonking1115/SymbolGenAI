import React, { useMemo, useState } from "react";

import { SYMBOL_LIBRARY, symbolsByCategory } from "@/lib/symbolLibrary";
import { useSchematicStore } from "@/store/schematicStore";
import type { SymbolDefinition } from "@/types/schematic";

export const SymbolPalette: React.FC = () => {
  const [filter, setFilter] = useState("");
  const placingSymbolId = useSchematicStore((s) => s.placingSymbolId);
  const beginPlacement = useSchematicStore((s) => s.beginPlacement);

  const grouped = useMemo(() => {
    if (!filter.trim()) return symbolsByCategory();
    const q = filter.trim().toLowerCase();
    const out: Record<string, SymbolDefinition[]> = {};
    for (const s of SYMBOL_LIBRARY) {
      if (
        s.name.toLowerCase().includes(q) ||
        s.refPrefix.toLowerCase().includes(q) ||
        s.id.toLowerCase().includes(q)
      ) {
        (out[s.category] ??= []).push(s);
      }
    }
    return out;
  }, [filter]);

  return (
    <aside className="palette">
      <div className="palette__header">
        <h2>Symbols</h2>
        <input
          className="palette__search"
          placeholder="Filter (e.g. resistor, R, GND)…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      <div className="palette__list">
        {Object.entries(grouped).map(([cat, items]) => (
          <section key={cat} className="palette__group">
            <h3>{cat}</h3>
            <ul>
              {items.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    className={[
                      "palette__item",
                      placingSymbolId === s.id ? "is-active" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    onClick={() => beginPlacement(s.id)}
                    title={`Place ${s.name}`}
                  >
                    <PreviewSvg def={s} />
                    <div className="palette__meta">
                      <div className="palette__name">{s.name}</div>
                      <div className="palette__sub">
                        {s.refPrefix}
                        {s.defaultValue ? ` · ${s.defaultValue}` : ""}
                      </div>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
        {Object.keys(grouped).length === 0 && (
          <div className="palette__empty">No symbols match “{filter}”.</div>
        )}
      </div>
    </aside>
  );
};

const PreviewSvg: React.FC<{ def: SymbolDefinition }> = ({ def }) => {
  const pad = 8;
  const vb = `${def.bbox.x - pad} ${def.bbox.y - pad} ${def.bbox.width + pad * 2} ${def.bbox.height + pad * 2}`;
  return (
    <svg
      className="palette__preview"
      viewBox={vb}
      width={56}
      height={36}
      aria-hidden="true"
    >
      {def.body}
      {def.pins.map((p) => (
        <circle key={p.id} cx={p.x} cy={p.y} r={1.2} className="pin-dot" />
      ))}
    </svg>
  );
};
