import React from "react";

import { useUiStore, type ViewKey } from "@/store/uiStore";

const TABS: { id: ViewKey; label: string; hint: string }[] = [
  { id: "schematic", label: "Schematic", hint: "Place symbols and route wires" },
  {
    id: "symbol-editor",
    label: "Symbol Editor",
    hint: "Edit a single symbol from a .SchLib or the built-in catalog",
  },
];

export const ViewTabs: React.FC = () => {
  const activeView = useUiStore((s) => s.activeView);
  const setActiveView = useUiStore((s) => s.setActiveView);

  return (
    <div className="view-tabs" role="tablist">
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={activeView === t.id}
          className={`view-tab ${activeView === t.id ? "is-active" : ""}`}
          onClick={() => setActiveView(t.id)}
          title={t.hint}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
};
