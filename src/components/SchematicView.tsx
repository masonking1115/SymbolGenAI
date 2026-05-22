import React from "react";

import { Canvas } from "./Canvas";
import { PlaceToolbar } from "./PlaceToolbar";

export const SchematicView: React.FC = () => (
  <>
    <PlaceToolbar />
    <div className="editor__canvas">
      <Canvas />
    </div>
  </>
);
