import React from "react";

import { useSchematicStore } from "@/store/schematicStore";

export const StatusBar: React.FC = () => {
  const cursor = useSchematicStore((s) => s.cursor);
  const tool = useSchematicStore((s) => s.tool);
  const placingSymbolId = useSchematicStore((s) => s.placingSymbolId);
  const wireDraft = useSchematicStore((s) => s.wireDraft);

  let hint = "Ready";
  if (placingSymbolId) hint = `Placing ${placingSymbolId} — click to place, R to rotate, Esc to cancel`;
  else if (wireDraft) hint = "Drawing wire — click to add segment, Tab to flip bend, Esc to cancel";
  else if (tool === "wire") hint = "Wire tool — click a pin or empty point to start";
  else if (tool === "pan") hint = "Pan tool — drag to pan";

  return (
    <footer className="statusbar">
      <span className="statusbar__cursor">
        x: {cursor.x.toFixed(0)} &nbsp; y: {cursor.y.toFixed(0)}
      </span>
      <span className="statusbar__hint">{hint}</span>
    </footer>
  );
};
