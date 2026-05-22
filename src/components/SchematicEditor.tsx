import React from "react";

import { Canvas } from "./Canvas";
import { PropertiesPanel } from "./PropertiesPanel";
import { StatusBar } from "./StatusBar";
import { SymbolPalette } from "./SymbolPalette";
import { Toolbar } from "./Toolbar";

export const SchematicEditor: React.FC = () => (
  <div className="editor">
    <Toolbar />
    <div className="editor__body">
      <SymbolPalette />
      <main className="editor__main">
        <Canvas />
      </main>
      <PropertiesPanel />
    </div>
    <StatusBar />
  </div>
);
