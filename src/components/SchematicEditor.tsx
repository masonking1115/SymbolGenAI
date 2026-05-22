import React from "react";

import { Canvas } from "./Canvas";
import { ChatPanel } from "./ChatPanel";
import { LibraryPanel } from "./LibraryPanel";
import { PlaceToolbar } from "./PlaceToolbar";
import { StatusBar } from "./StatusBar";
import { Toolbar } from "./Toolbar";

export const SchematicEditor: React.FC = () => (
  <div className="editor">
    <Toolbar />
    <div className="editor__body">
      <LibraryPanel />
      <main className="editor__main">
        <PlaceToolbar />
        <div className="editor__canvas">
          <Canvas />
        </div>
      </main>
      <ChatPanel />
    </div>
    <StatusBar />
  </div>
);
