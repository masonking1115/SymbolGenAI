/* Diff overlay — generalization of the simulated-region overlay pattern
 * in PngViewer. Same SVG-mask approach: dim the whole sheet, cut holes
 * for each highlighted refdes, stroke the cutouts in a color matching
 * the change kind (added=green, removed=red, changed=amber).
 *
 * Used in side-by-side mode by DiffAndAccept. Sized to match the host
 * SVG's viewBox via the parent's natural-size context.
 */
import { useId, type CSSProperties } from "react";

export interface DiffBox {
  x: number;
  y: number;
  kind: "added" | "removed" | "changed";
  refdes?: string;
}

// Pane tone: BEFORE pane boxes are light RED (what was there / removed/changed
// before), AFTER pane boxes are light GREEN (the corrected state). Overlay mode
// keeps per-kind colors. Tones picked to match the requested light swatches.
type Tone = "before" | "after" | "kind";
const PALETTE = {
  red:   { stroke: "#c0392b", fill: "#e74c3c" },  // light red
  green: { stroke: "#5a8f29", fill: "#7cb342" },  // light green
  amber: { stroke: "#d97706", fill: "#f59e0b" },
};
function boxColors(kind: DiffBox["kind"], tone: Tone) {
  if (tone === "before") return PALETTE.red;
  if (tone === "after") return PALETTE.green;
  // overlay: color by kind
  return kind === "added" ? PALETTE.green : kind === "removed" ? PALETTE.red : PALETTE.amber;
}

// Box geometry is sized RELATIVE TO THE SHEET, not a fixed constant. The old
// fixed 170x140 was tuned for the KiCad-era ~15500-mil sheets; on the Altium
// drawable frame (viewBox ~1150-2230 wide) a 170-wide box is ~8% of the sheet —
// so big it swallowed neighboring parts and read as a broken highlight. We now
// derive the box from the viewBox so one part is framed cleanly on every sheet.
//   • size ~ 4% of the sheet's smaller dimension (frames a part + its label),
//   • clamped so it never gets absurdly small/large,
//   • stroke + label font also scale with the box (a 5px stroke on a 60-unit box
//     is a different weight than on a 170-unit one).
function geometryFor(vbW: number, vbH: number) {
  const base = Math.min(vbW, vbH) || 1000;
  const size = Math.max(45, Math.min(120, base * 0.06));
  return {
    w: size,
    h: size * 0.85,
    rx: size * 0.08,
    stroke: Math.max(1.5, size * 0.035),
    font: Math.max(9, size * 0.18),
    pad: size * 0.04,
  };
}

interface Props {
  boxes: DiffBox[];
  viewBox: string;       // matches the host SVG viewBox
  style?: CSSProperties;
  tone?: Tone;           // "before" -> red, "after" -> green, "kind" -> by kind
}

export function DiffOverlay({ boxes, viewBox, style, tone = "kind" }: Props) {
  // useId is stable across renders, so the SVG mask reference doesn't flicker.
  const maskId = "diff-mask-" + useId().replace(/:/g, "");
  const [, , vbWraw, vbHraw] = viewBox.trim().split(/\s+/).map(Number);
  const vbW = vbWraw || 1000;
  const vbH = vbHraw || 1000;
  const g = geometryFor(vbW, vbH);
  // Center the box on the anchor, clamped so a part near an edge keeps its full
  // box on-sheet (the old code let the box — and its label at by-8 — spill off
  // the top/left edge).
  const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
  const bx = (b: DiffBox) => clamp(b.x - g.w / 2, 0, vbW - g.w);
  const by = (b: DiffBox) => clamp(b.y - g.h / 2, g.font + g.pad, vbH - g.h);
  return (
    <svg viewBox={viewBox} style={style} preserveAspectRatio="xMidYMid meet">
      <defs>
        <mask id={maskId}>
          {/* Light dim of the rest of the sheet so the boxed parts stand out,
              but kept gentle (0.18) — a heavy dim made the whole pane look washed
              out / like an error rather than a highlight. */}
          <rect x="0" y="0" width="100%" height="100%" fill="white" opacity="0.18" />
          {boxes.map((b, i) => (
            <rect key={i} x={bx(b)} y={by(b)} width={g.w} height={g.h} rx={g.rx} fill="black" />
          ))}
        </mask>
      </defs>
      <rect x="0" y="0" width="100%" height="100%" fill="white" opacity="0" mask={`url(#${maskId})`} />
      {boxes.map((b, i) => {
        const c = boxColors(b.kind, tone);
        const x = bx(b), y = by(b);
        return (
          <g key={i}>
            <rect x={x} y={y} width={g.w} height={g.h} rx={g.rx}
              fill={c.fill} fillOpacity={0.14}
              stroke={c.stroke} strokeWidth={g.stroke} strokeOpacity={0.95} />
            {b.refdes && (
              <text x={x + g.pad} y={y - g.pad}
                fontSize={g.font} fontWeight="bold" fill={c.stroke} fontFamily="monospace">
                {b.refdes}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
