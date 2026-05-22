import React from "react";

import { GRID } from "@/lib/geometry";
import type { SymbolDefinition } from "@/types/schematic";

interface Props {
  def: SymbolDefinition;
}

/**
 * Renders one symbol centered on its bounding box. The SVG viewBox is sized
 * so the symbol fills the available space with comfortable padding. Pins are
 * shown as labeled dots — pin id is drawn close to the dot, name slightly
 * offset for clarity.
 */
export const SymbolEditorCanvas: React.FC<Props> = ({ def }) => {
  // Pad the bounding box so labels don't clip.
  const PAD = 60;
  const { x, y, width, height } = def.bbox;
  const minX = x - PAD;
  const minY = y - PAD;
  const w = width + PAD * 2;
  const h = height + PAD * 2;

  // Visible grid extent (one major grid past the padded area).
  const gridMin = Math.floor(minX / GRID) * GRID;
  const gridMax = Math.ceil((minX + w) / GRID) * GRID;
  const gridMinY = Math.floor(minY / GRID) * GRID;
  const gridMaxY = Math.ceil((minY + h) / GRID) * GRID;

  return (
    <div className="sym-editor-canvas">
      <svg
        className="sym-editor-canvas__svg"
        viewBox={`${minX} ${minY} ${w} ${h}`}
        preserveAspectRatio="xMidYMid meet"
      >
        {/* Grid dots */}
        <g className="sym-editor-canvas__grid">
          {gridDots(gridMin, gridMax, gridMinY, gridMaxY, GRID)}
        </g>

        {/* Origin crosshair */}
        <g className="sym-editor-canvas__origin">
          <line x1={-12} y1={0} x2={12} y2={0} />
          <line x1={0} y1={-12} x2={0} y2={12} />
        </g>

        {/* Symbol body */}
        <g className="sym-editor-canvas__body">{def.body}</g>

        {/* Pins with labels */}
        <g className="sym-editor-canvas__pins">
          {def.pins.map((p) => (
            <g key={p.id}>
              <circle cx={p.x} cy={p.y} r={2.2} className="pin-dot" />
              <text
                x={pinLabelX(p.x, def)}
                y={p.y - 4}
                textAnchor={pinLabelAnchor(p.x, def)}
                className="sym-editor-canvas__pin-id"
              >
                {p.id}
              </text>
              <text
                x={pinLabelX(p.x, def)}
                y={p.y + 9}
                textAnchor={pinLabelAnchor(p.x, def)}
                className="sym-editor-canvas__pin-name"
              >
                {p.name}
              </text>
            </g>
          ))}
        </g>
      </svg>

      <div className="sym-editor-canvas__caption">
        {def.name} · {def.refPrefix}
        {def.defaultValue ? ` · ${def.defaultValue}` : ""}
      </div>
    </div>
  );
};

function pinLabelX(pinX: number, def: SymbolDefinition): number {
  // Place labels outside the bbox so they don't overlap the body.
  const midX = def.bbox.x + def.bbox.width / 2;
  return pinX < midX ? pinX - 5 : pinX + 5;
}

function pinLabelAnchor(pinX: number, def: SymbolDefinition): "start" | "end" {
  const midX = def.bbox.x + def.bbox.width / 2;
  return pinX < midX ? "end" : "start";
}

function gridDots(
  minX: number,
  maxX: number,
  minY: number,
  maxY: number,
  step: number,
): React.ReactNode[] {
  const dots: React.ReactNode[] = [];
  for (let gx = minX; gx <= maxX; gx += step) {
    for (let gy = minY; gy <= maxY; gy += step) {
      dots.push(<circle key={`${gx},${gy}`} cx={gx} cy={gy} r={0.4} />);
    }
  }
  return dots;
}
