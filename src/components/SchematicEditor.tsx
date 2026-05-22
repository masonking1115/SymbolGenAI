import React from "react";

import { useUiStore } from "@/store/uiStore";

import { ChatPanel } from "./ChatPanel";
import { LibraryPanel } from "./LibraryPanel";
import { SchematicView } from "./SchematicView";
import { StatusBar } from "./StatusBar";
import { SymbolEditorView } from "./SymbolEditorView";
import { SymbolPropertiesPanel } from "./SymbolPropertiesPanel";
import { Toolbar } from "./Toolbar";
import { ViewTabs } from "./ViewTabs";

export const SchematicEditor: React.FC = () => {
  const view = useUiStore((s) => s.activeView);
  const isSymbolEditor = view === "symbol-editor";

  return (
    <div className="editor">
      <Toolbar />
      <ViewTabs />
      <div
        className={`editor__body ${isSymbolEditor ? "is-symbol-editor" : "is-schematic"}`}
      >
        <LibraryPanel />
        <main className="editor__main">
          {isSymbolEditor ? <SymbolEditorView /> : <SchematicView />}
        </main>
        {isSymbolEditor && <SymbolPropertiesPanel />}
        <ChatPanel />
      </div>
      <StatusBar />
    </div>
  );
};
