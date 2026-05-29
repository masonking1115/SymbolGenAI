// SVG device glyphs for the schematic view — proportions mirror
// test1/altium/glyphs.py (resistor zig-zag, cap plates, inductor humps, diode,
// MOSFET, op-amp triangle) so the sim schematic looks like the Altium symbols.
//
// Each glyph draws in its PlacedGlyph's local box (g.x,g.y → g.x+g.w,g.y+g.h).
// Pins/leads are drawn by the router (stubs to the body edge), so a glyph only
// needs to draw the BODY between its pin anchors.

import type { PlacedGlyph } from "./schematic";

const STROKE = "#0F172A";
const LW = 1.6;

export function Glyph({ g, lit }: { g: PlacedGlyph; lit: boolean }) {
  const stroke = lit ? "#2563eb" : STROKE;
  const body = renderBody(g, stroke);
  const showVal = !!g.value && g.shape !== "box";
  const valTxt = showVal ? fmtValue(g.value, g.shape) : "";
  const rw = Math.max(g.ref.length, valTxt.length) * 6.2 + 4;
  // Op-amp / IC: the right side carries the output pin + net lanes, so the ref
  // label collides there — place it ABOVE the body instead. Two-terminal parts
  // keep their label to the right (the classic schematic spot).
  const above = g.shape === "opamp" || g.shape === "box";
  const tx = above ? g.x : g.x + g.w + 8;
  const refY = above ? g.y - 6 : g.y + 12;
  const valY = above ? g.y - 6 + 12 : g.y + 25;
  return (
    <g>
      {body}
      {/* designator (+ value) over a backing rect so it reads over wires */}
      <rect x={tx - 2} y={(above ? g.y - 16 : g.y + 2)} width={rw} height={showVal && !above ? 26 : 14}
            fill="#FCFCFD" opacity={0.8} />
      <text x={tx} y={refY} fontSize={11} fontWeight={600}
            fontFamily="ui-monospace, monospace" fill="#0F172A">
        {g.ref}
      </text>
      {showVal && !above && (
        <text x={tx} y={valY} fontSize={10}
              fontFamily="ui-monospace, monospace" fill="#64748B">
          {valTxt}
        </text>
      )}
    </g>
  );
}

function renderBody(g: PlacedGlyph, stroke: string) {
  const { x, y, w, h } = g;
  const cx = x + w / 2;
  switch (g.shape) {
    case "resistor": {
      // vertical zig-zag between top lead and bottom lead (6 segments)
      const top = y + 14, bot = y + h - 14, a = 9, n = 6;
      const z = (bot - top) / n;
      const pts: string[] = [`${cx},${top}`];
      for (let i = 0; i < n - 1; i++)
        pts.push(`${cx + (i % 2 === 0 ? a : -a)},${top + (i + 1) * z}`);
      pts.push(`${cx},${bot}`);
      return (
        <>
          <line x1={cx} y1={y} x2={cx} y2={top} stroke={stroke} strokeWidth={LW} />
          <polyline points={pts.join(" ")} fill="none" stroke={stroke} strokeWidth={LW} />
          <line x1={cx} y1={bot} x2={cx} y2={y + h} stroke={stroke} strokeWidth={LW} />
        </>
      );
    }
    case "capacitor": {
      // two parallel plates across the middle
      const my = y + h / 2, pw = 16, gap = 6;
      return (
        <>
          <line x1={cx} y1={y} x2={cx} y2={my - gap} stroke={stroke} strokeWidth={LW} />
          <line x1={cx - pw} y1={my - gap} x2={cx + pw} y2={my - gap} stroke={stroke} strokeWidth={LW} />
          <line x1={cx - pw} y1={my + gap} x2={cx + pw} y2={my + gap} stroke={stroke} strokeWidth={LW} />
          <line x1={cx} y1={my + gap} x2={cx} y2={y + h} stroke={stroke} strokeWidth={LW} />
        </>
      );
    }
    case "inductor": {
      // three half-circle humps bulging right
      const top = y + 14, bot = y + h - 14;
      const span = bot - top, r = span / 6;
      const arcs = [];
      for (let i = 0; i < 3; i++) {
        const ay = top + r + i * 2 * r;
        arcs.push(
          <path key={i} d={`M ${cx} ${ay - r} A ${r} ${r} 0 0 1 ${cx} ${ay + r}`}
                fill="none" stroke={stroke} strokeWidth={LW} />,
        );
      }
      return (
        <>
          <line x1={cx} y1={y} x2={cx} y2={top} stroke={stroke} strokeWidth={LW} />
          {arcs}
          <line x1={cx} y1={bot} x2={cx} y2={y + h} stroke={stroke} strokeWidth={LW} />
        </>
      );
    }
    case "diode": {
      const my = y + h / 2, tw = 11;
      return (
        <>
          <line x1={cx} y1={y} x2={cx} y2={my - 8} stroke={stroke} strokeWidth={LW} />
          <polygon points={`${cx - tw},${my - 8} ${cx + tw},${my - 8} ${cx},${my + 8}`}
                   fill="none" stroke={stroke} strokeWidth={LW} />
          <line x1={cx - tw} y1={my + 8} x2={cx + tw} y2={my + 8} stroke={stroke} strokeWidth={LW} />
          <line x1={cx} y1={my + 8} x2={cx} y2={y + h} stroke={stroke} strokeWidth={LW} />
        </>
      );
    }
    case "mosfet": {
      // gate bar on the left; vertical channel bar; drain (top) / source (bottom)
      const chanX = x + 30, gx = x, gateY = y + 40;
      const dTop = y + 8, sBot = y + h - 8;
      return (
        <>
          {/* gate lead + bar */}
          <line x1={gx} y1={gateY} x2={chanX - 12} y2={gateY} stroke={stroke} strokeWidth={LW} />
          <line x1={chanX - 12} y1={gateY - 14} x2={chanX - 12} y2={gateY + 14} stroke={stroke} strokeWidth={LW} />
          {/* channel bar */}
          <line x1={chanX} y1={y + 16} x2={chanX} y2={y + h - 16} stroke={stroke} strokeWidth={LW} />
          {/* drain branch */}
          <line x1={x + 46} y1={dTop} x2={x + 46} y2={y + 24} stroke={stroke} strokeWidth={LW} />
          <line x1={x + 46} y1={y + 24} x2={chanX} y2={y + 24} stroke={stroke} strokeWidth={LW} />
          {/* source branch */}
          <line x1={x + 46} y1={sBot} x2={x + 46} y2={y + h - 24} stroke={stroke} strokeWidth={LW} />
          <line x1={x + 46} y1={y + h - 24} x2={chanX} y2={y + h - 24} stroke={stroke} strokeWidth={LW} />
        </>
      );
    }
    case "opamp": {
      // triangle pointing right; inputs left, output apex right
      const left = x + 6, right = x + w - 6;
      const apexY = y + h / 2;
      return (
        <>
          <polygon points={`${left},${y + 8} ${left},${y + h - 8} ${right},${apexY}`}
                   fill="#fff" stroke={stroke} strokeWidth={LW} />
          {/* + / - markers */}
          <text x={left + 8} y={y + 26} fontSize={11} fill={stroke} fontFamily="monospace">+</text>
          <text x={left + 8} y={y + h - 16} fontSize={13} fill={stroke} fontFamily="monospace">−</text>
        </>
      );
    }
    case "source": {
      // circle with a polarity hint
      const my = y + h / 2, rad = Math.min(w, h) / 2 - 8;
      return (
        <>
          <line x1={cx} y1={y} x2={cx} y2={my - rad} stroke={stroke} strokeWidth={LW} />
          <circle cx={cx} cy={my} r={rad} fill="#fff" stroke={stroke} strokeWidth={LW} />
          <text x={cx} y={my + 4} fontSize={12} textAnchor="middle" fill={stroke} fontFamily="monospace">
            {g.el.kind === "isource" || g.el.kind === "bsource" ? "↕" : "+"}
          </text>
          <line x1={cx} y1={my + rad} x2={cx} y2={y + h} stroke={stroke} strokeWidth={LW} />
        </>
      );
    }
    case "box":
    default: {
      return (
        <>
          <rect x={x} y={y} width={w} height={h} rx={3} fill="#EEF2FF" stroke={stroke} strokeWidth={LW} />
          <text x={x + w / 2} y={y + h / 2} textAnchor="middle" dominantBaseline="central"
                fontSize={10} fontWeight={600} fontFamily="ui-monospace, monospace" fill="#3730A3">
            {g.label ?? g.ref}
          </text>
        </>
      );
    }
  }
}

// Compact value: SPICE source specs can be long; show the leading token.
function fmtValue(v: string, shape: PlacedGlyph["shape"]): string {
  if (shape === "source") {
    const m = v.match(/(?:DC|AC)?\s*([\d.eE+-]+[a-zµμ]*)/);
    return (m?.[1] ?? v).slice(0, 12);
  }
  // R/L/C: prettify exponent to engineering units
  const num = Number(v);
  if (!Number.isNaN(num) && v.trim() !== "") return eng(num);
  return v.slice(0, 14);
}

function eng(x: number): string {
  if (x === 0) return "0";
  const units = [
    [1e9, "G"], [1e6, "M"], [1e3, "k"], [1, ""],
    [1e-3, "m"], [1e-6, "µ"], [1e-9, "n"], [1e-12, "p"], [1e-15, "f"],
  ] as const;
  const a = Math.abs(x);
  for (const [scale, suf] of units) {
    if (a >= scale) {
      const val = x / scale;
      const s = val.toFixed(val < 10 ? 2 : val < 100 ? 1 : 0).replace(/\.?0+$/, "");
      return s + suf;
    }
  }
  return x.toExponential(1);
}
