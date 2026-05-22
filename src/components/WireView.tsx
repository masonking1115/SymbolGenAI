import React from "react";
import type { Point, Wire } from "@/types/schematic";

interface Props {
  wire?: Wire;
  points?: Point[];
  selected?: boolean;
  preview?: boolean;
  onMouseDown?: (e: React.MouseEvent) => void;
}

export const WireView: React.FC<Props> = ({
  wire,
  points,
  selected,
  preview,
  onMouseDown,
}) => {
  const pts = wire?.points ?? points ?? [];
  if (pts.length < 2) return null;
  const d = pts
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`)
    .join(" ");

  return (
    <g
      className={[
        "wire",
        selected ? "is-selected" : "",
        preview ? "is-preview" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      onMouseDown={onMouseDown}
    >
      {/* Fat invisible hit target */}
      <path d={d} className="wire__hit" />
      {/* Visible stroke */}
      <path d={d} className="wire__stroke" />
      {/* Junction dots at each interior vertex (T junctions get drawn later) */}
      {!preview &&
        pts.slice(1, -1).map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r={1.2} className="wire__corner" />
        ))}
    </g>
  );
};
