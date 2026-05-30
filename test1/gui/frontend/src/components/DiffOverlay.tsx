/* Diff overlay — generalization of the simulated-region overlay pattern
 * in PngViewer. Same SVG-mask approach: dim the whole sheet, cut holes
 * for each highlighted refdes, stroke the cutouts in a color matching
 * the change kind (added=green, removed=red, changed=amber).
 *
 * Used in side-by-side mode by DiffAndAccept. Sized to match the host
 * SVG's viewBox via the parent's natural-size context.
 */
import type { CSSProperties } from "react";

export interface DiffBox {
  x: number;
  y: number;
  kind: "added" | "removed" | "changed";
  refdes?: string;
}

const COLOR: Record<DiffBox["kind"], string> = {
  added:   "#16a34a",   // green-600
  removed: "#dc2626",   // red-600
  changed: "#d97706",   // amber-600
};

const BOX_W = 150;
const BOX_H = 120;
const BOX_DX = -70;
const BOX_DY = -30;

interface Props {
  boxes: DiffBox[];
  viewBox: string;       // matches the host SVG viewBox
  style?: CSSProperties;
}

export function DiffOverlay({ boxes, viewBox, style }: Props) {
  const maskId = "diff-mask-" + Math.random().toString(36).slice(2, 8);
  return (
    <svg viewBox={viewBox} style={style} preserveAspectRatio="xMidYMid meet">
      <defs>
        <mask id={maskId}>
          <rect x="0" y="0" width="100%" height="100%" fill="white" opacity="0.35" />
          {boxes.map((b, i) => (
            <rect key={i}
              x={b.x + BOX_DX} y={b.y + BOX_DY}
              width={BOX_W} height={BOX_H}
              fill="black" />
          ))}
        </mask>
      </defs>
      <rect x="0" y="0" width="100%" height="100%" fill="white" opacity="0" mask={`url(#${maskId})`} />
      {boxes.map((b, i) => (
        <g key={i}>
          <rect x={b.x + BOX_DX} y={b.y + BOX_DY}
            width={BOX_W} height={BOX_H}
            fill="none" stroke={COLOR[b.kind]} strokeWidth={6}
            opacity={0.95} />
          {b.refdes && (
            <text x={b.x + BOX_DX + 4} y={b.y + BOX_DY - 6}
              fontSize="20" fill={COLOR[b.kind]} fontFamily="monospace">
              {b.refdes}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}
