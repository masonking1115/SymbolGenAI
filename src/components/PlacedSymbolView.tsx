import React from "react";
import type { PlacedSymbol, SymbolDefinition } from "@/types/schematic";

interface Props {
  placed: PlacedSymbol;
  def: SymbolDefinition;
  selected?: boolean;
  ghost?: boolean;
  onMouseDown?: (e: React.MouseEvent) => void;
  onPinMouseDown?: (pinId: string, e: React.MouseEvent) => void;
}

const PIN_DOT_R = 1.6;

export const PlacedSymbolView: React.FC<Props> = ({
  placed,
  def,
  selected,
  ghost,
  onMouseDown,
  onPinMouseDown,
}) => {
  const { position, rotation, designator, value } = placed;
  const transform = `translate(${position.x} ${position.y}) rotate(${rotation})`;

  return (
    <g
      transform={transform}
      onMouseDown={onMouseDown}
      className={[
        "placed-symbol",
        selected ? "is-selected" : "",
        ghost ? "is-ghost" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {/* Selection halo / hit area */}
      <rect
        x={def.bbox.x - 4}
        y={def.bbox.y - 4}
        width={def.bbox.width + 8}
        height={def.bbox.height + 8}
        className="placed-symbol__hitbox"
      />

      {/* Symbol body */}
      <g className="placed-symbol__body">{def.body}</g>

      {/* Pins */}
      <g className="placed-symbol__pins">
        {def.pins.map((pin) => (
          <circle
            key={pin.id}
            cx={pin.x}
            cy={pin.y}
            r={PIN_DOT_R}
            className="pin-dot"
            onMouseDown={(e) => {
              e.stopPropagation();
              onPinMouseDown?.(pin.id, e);
            }}
          />
        ))}
      </g>

      {/* Designator + value, drawn upright relative to body */}
      {!ghost && (
        <g
          className="placed-symbol__labels"
          // Counter-rotate so text stays horizontal even when symbol is rotated.
          transform={`rotate(${-rotation})`}
        >
          <text
            x={0}
            y={def.bbox.y - 8}
            textAnchor="middle"
            className="label-designator"
          >
            {designator}
          </text>
          {value && (
            <text
              x={0}
              y={def.bbox.y + def.bbox.height + 14}
              textAnchor="middle"
              className="label-value"
            >
              {value}
            </text>
          )}
        </g>
      )}
    </g>
  );
};
