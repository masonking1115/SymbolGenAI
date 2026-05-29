// Lay out a parsed SPICE Circuit as an LTspice-style schematic: real device
// glyphs placed on a grid, connected by orthogonal (Manhattan) wires, with
// ground symbols and net labels. Pure geometry — the React component renders
// the result. No layout library.
//
// Strategy
// --------
//  - Each element becomes a GLYPH with named PINS (local anchor + the direction
//    the wire leaves the body). Glyph geometry mirrors test1/altium/glyphs.py.
//  - PLACEMENT: rank elements by BFS hop-distance from ground (supply→load flows
//    left→right), one column per rank, stacked vertically within a column.
//  - ROUTING: for each net, gather every pin on it and draw a vertical "net
//    trunk" with horizontal stubs to each pin (a classic schematic bus-stub).
//    Ground nets don't get a trunk — each ground pin gets its own GND symbol.

import type { Circuit, CircuitElement } from "../types";

export type PinDir = "up" | "down" | "left" | "right";

export interface GlyphPin {
  name: string;       // terminal role: "1"/"2", "G"/"D"/"S", "+"/"-"/"out", …
  net: string;        // the net this pin connects to
  x: number;          // local anchor (within the glyph box)
  y: number;
  dir: PinDir;        // direction the wire leaves the body
}

export type GlyphShape =
  | "resistor" | "capacitor" | "inductor" | "diode"
  | "mosfet" | "opamp" | "source" | "box";

export interface PlacedGlyph {
  ref: string;
  shape: GlyphShape;
  value: string;
  note: string;
  el: CircuitElement;
  // world-space box
  x: number; y: number; w: number; h: number;
  pins: GlyphPin[];   // world-space pin anchors
  label?: string;     // subckt box title
}

export interface Wire { x1: number; y1: number; x2: number; y2: number; net: string; }
export interface Junction { x: number; y: number; net: string; }
export interface GndSym { x: number; y: number; net: string; }
export interface NetLabel { x: number; y: number; text: string; anchor?: "start" | "middle"; }

export interface Schematic {
  glyphs: PlacedGlyph[];
  wires: Wire[];
  junctions: Junction[];
  grounds: GndSym[];
  labels: NetLabel[];
  W: number; H: number;
}

const GND = new Set(["0", "gnd", "gnd!"]);
const isGnd = (n: string) => GND.has(n.toLowerCase());

// ---- glyph templates: box size + local pin anchors -------------------------
// Two-terminal parts are authored VERTICAL (pin 1 top, pin 2 bottom), matching
// glyphs.py. The router rotates nothing; instead it routes orthogonally to
// whichever side the net trunk sits on.

interface Template {
  shape: GlyphShape;
  w: number; h: number;
  // pins by index in the element's node list → local anchor + leave direction.
  // `ports` are the subckt's declared port NAMES (parser: circuit.subckts[x].ports),
  // index-aligned to nodes — used to label pins with the real schematic name
  // (IN/OUT/EN/GND, IN+/IN-) instead of a bare number.
  pins: (nodes: string[], ports?: string[]) => GlyphPin[];
}

// Normalize a subckt port name to the symbol's conventional pin label.
function pinLabel(port: string | undefined, fallback: string): string {
  if (!port) return fallback;
  const p = port.toUpperCase();
  if (p === "INP" || p === "IN+" || p === "VINP" || p === "NIN") return "IN+";
  if (p === "INN" || p === "IN-" || p === "VINN" || p === "PIN") return "IN-";
  if (p === "VCC" || p === "VDD" || p === "V+" || p === "VS+") return "V+";
  if (p === "VEE" || p === "VSS" || p === "V-" || p === "VS-") return "V-";
  return port;   // already a real name (IN, OUT, EN, GND, NR, VIN, VOUT, …)
}

// Which body side a named IC pin belongs on, by function: power up, ground down,
// enable/inputs left, outputs right. Keeps a generic IC box reading like a real
// symbol rather than pins dumped down both edges by index.
type Side = "left" | "right" | "top" | "bottom";
function portSide(port: string): Side {
  const p = port.toUpperCase();
  if (/^(VCC|VDD|VIN|IN|V\+|VS\+|AVDD|DVDD)$/.test(p)) return "top";
  if (/^(GND|VEE|VSS|V-|VS-|AGND|DGND|PAD|EP)$/.test(p)) return "bottom";
  if (/^(OUT|VOUT|DOUT|Q)$/.test(p)) return "right";
  return "left";    // EN, NR, FB, SET, control, everything else → left
}

const TWO_TERM = (shape: GlyphShape): Template => ({
  shape, w: 36, h: 64,
  pins: (nodes) => [
    { name: "1", net: nodes[0] ?? "", x: 18, y: 0, dir: "up" },
    { name: "2", net: nodes[1] ?? "", x: 18, y: 64, dir: "down" },
  ],
});

// MOSFET: gate left, drain top, source bottom (matches the deck's M-line order
// D G S B → we map node[0]=D node[1]=G node[2]=S).
const MOSFET: Template = {
  shape: "mosfet", w: 60, h: 72,
  pins: (n) => [
    { name: "D", net: n[0] ?? "", x: 46, y: 0, dir: "up" },
    { name: "G", net: n[1] ?? "", x: 0, y: 40, dir: "left" },
    { name: "S", net: n[2] ?? "", x: 46, y: 72, dir: "down" },
  ],
};

// Op-amp: + and - on the left, out on the right, optional rails top/bottom.
// Subckt port order for OPA2388 is OUT INP INN VCC VEE → element node order
// follows the X-line: nodes[0]=OUT nodes[1]=INP(+) nodes[2]=INN(-) nodes[3]=VCC nodes[4]=VEE.
const OPAMP: Template = {
  shape: "opamp", w: 76, h: 72,
  // OPA2388 subckt ports: OUT INP INN VCC VEE (index-aligned to nodes). Label
  // each pin with its real symbol name (IN+/IN-/OUT/V+/V-).
  pins: (n, ports) => {
    const nm = (i: number, fb: string) => pinLabel(ports?.[i], fb);
    const pins: GlyphPin[] = [
      { name: nm(1, "IN+"), net: n[1] ?? "", x: 0, y: 22, dir: "left" },
      { name: nm(2, "IN-"), net: n[2] ?? "", x: 0, y: 50, dir: "left" },
      { name: nm(0, "OUT"), net: n[0] ?? "", x: 76, y: 36, dir: "right" },
    ];
    if (n[3]) pins.push({ name: nm(3, "V+"), net: n[3], x: 30, y: 0, dir: "up" });
    if (n[4] && !isGnd(n[4])) pins.push({ name: nm(4, "V-"), net: n[4], x: 30, y: 72, dir: "down" });
    return pins;
  },
};

function classify(el: CircuitElement): GlyphShape {
  switch (el.kind) {
    case "resistor": return "resistor";
    case "capacitor": return "capacitor";
    case "inductor": return "inductor";
    case "diode": return "diode";
    case "mosfet": return "mosfet";
    case "vsource":
    case "isource":
    case "bsource": return "source";
    case "subckt": {
      // op-amp-like subckt → triangle; else a generic box.
      const name = (el.subckt ?? "").toUpperCase();
      if (/OPA|OP_?AMP|AMP|LMV|TLV|ADA/.test(name) && el.nodes.length >= 3) return "opamp";
      return "box";
    }
    default: return "box";
  }
}

function template(el: CircuitElement, subcktPorts?: string[]): Template {
  const shape = classify(el);
  if (shape === "mosfet") return MOSFET;
  if (shape === "opamp") return OPAMP;
  if (shape === "box") {
    // generic IC (e.g. the LDO / load switch): a box with FUNCTION-PLACED, NAMED
    // pins — IN/VIN up top, GND/VEE on the bottom, OUT on the right, EN/control on
    // the left — read from the subckt's declared ports. Reads like a real symbol
    // instead of pins dumped down both edges by index.
    const n = el.nodes.length;
    const W = 96;
    const ports = subcktPorts;   // captured from buildSchematic (may be undefined)
    const sideOf = (i: number): Side =>
      ports?.[i] ? portSide(ports[i]) : (i < Math.ceil(n / 2) ? "left" : "right");
    // size from the busiest vertical side so pins never crowd — computed ONCE
    // here (not inside pins()) so the body box height matches the pin layout.
    const groups0: Record<Side, number[]> = { left: [], right: [], top: [], bottom: [] };
    el.nodes.forEach((_net, i) => groups0[sideOf(i)].push(i));
    const maxVert = Math.max(groups0.left.length, groups0.right.length, 1);
    const h = Math.max(64, 20 + maxVert * 22);
    return {
      shape: "box", w: W, h,
      pins: (nodes, ports) => {
        const groups: Record<Side, number[]> = { left: [], right: [], top: [], bottom: [] };
        nodes.forEach((_net, i) => groups[(ports?.[i] ? portSide(ports[i]) : (i < Math.ceil(n / 2) ? "left" : "right"))].push(i));
        const out: GlyphPin[] = [];
        const place = (idxs: number[], side: Side) => {
          idxs.forEach((i, k) => {
            const name = pinLabel(ports?.[i], String(i + 1));
            const net = nodes[i] ?? "";
            if (side === "left" || side === "right") {
              const y = ((k + 1) * h) / (idxs.length + 1);
              out.push({ name, net, x: side === "left" ? 0 : W, y, dir: side });
            } else {
              const x = ((k + 1) * W) / (idxs.length + 1);
              out.push({ name, net, x, y: side === "top" ? 0 : h, dir: side === "top" ? "up" : "down" });
            }
          });
        };
        place(groups.left, "left"); place(groups.right, "right");
        place(groups.top, "top"); place(groups.bottom, "bottom");
        return out;
      },
    };
  }
  return TWO_TERM(shape);
}

// ---- placement + routing ---------------------------------------------------
// Structure-aware: detect series CHAINS (decap legs, rail chains) and lay each
// out as one aligned vertical stack; parallel legs sharing the same two anchor
// nets form a comb (a PDN becomes a rail with identical legs). Everything else
// falls back to a generic BFS-rank placer. Lanes route in gutters and dodge
// glyph bodies. Mirrors what an engineer would draw for these decks.
const GLYPH_GAP = 30;       // vertical gap between parts inside a leg/column
const REST_GAP = 64;        // vertical gap in the generic (non-leg) region
const MARGIN = 60;
const LANE_PITCH = 16;      // x-spacing of adjacent net lanes in a gutter
const GUTTER_PAD = 28;
const MAX_PER_COL = 5;
const LABEL_PAD = 150;
const LEG_PITCH = 120;      // x-spacing of parallel comb legs
const OPAMP_CLEARANCE = 48; // extra gutter after an op-amp/IC column
const BODY_CLEAR = 10;      // min gap a lane must keep from any glyph body edge

const SERIES_KINDS = new Set(["resistor", "capacitor", "inductor", "diode"]);
function is2term(el: CircuitElement): boolean {
  const k = classify(el);
  if (SERIES_KINDS.has(k)) return true;
  return (el.kind === "vsource" || el.kind === "isource" || el.kind === "bsource")
    && el.nodes.length === 2;
}

interface Chain { chain: string[]; top: string; bot: string; }

// Maximal runs of 2-terminal parts joined at PRIVATE (exactly-2-connection,
// non-bus, non-ground) nodes, spanning anchor→anchor. A decap leg
// (rail→L→R→C→gnd) and the source chain (V→R→L→rail) are chains.
function findChains(circuit: Circuit): Chain[] {
  const netMap = new Map<string, string[]>();
  for (const e of circuit.elements)
    for (const nd of e.nodes)
      (netMap.get(nd) ?? netMap.set(nd, []).get(nd)!).push(e.ref);
  const byRef = new Map(circuit.elements.map((e) => [e.ref, e]));
  const isAnchor = (net: string) => isGnd(net) || (netMap.get(net)?.length ?? 0) >= 3;
  const isPrivate = (net: string) => !isAnchor(net) && (netMap.get(net)?.length ?? 0) === 2;

  const used = new Set<string>();
  const chains: Chain[] = [];
  for (const e of circuit.elements) {
    if (used.has(e.ref) || !is2term(e)) continue;
    const [a, b] = e.nodes;
    let startNet: string, nextNet: string;
    if (isAnchor(a)) { startNet = a; nextNet = b; }
    else if (isAnchor(b)) { startNet = b; nextNet = a; }
    else if (isPrivate(a) && isPrivate(b)) { startNet = a; nextNet = b; }
    else continue;
    const seq = [e.ref]; used.add(e.ref);
    let cur = nextNet, prevRef = e.ref;
    while (isPrivate(cur)) {
      const nb = netMap.get(cur)!.find((rr) => rr !== prevRef && !used.has(rr));
      if (!nb) break;
      const nbEl = byRef.get(nb)!;
      if (!is2term(nbEl)) break;
      seq.push(nb); used.add(nb);
      cur = nbEl.nodes.find((x) => x !== cur) ?? cur;
      prevRef = nb;
    }
    if (seq.length >= 2) chains.push({ chain: seq, top: startNet, bot: cur });
    else used.delete(e.ref);
  }
  return chains;
}

export function buildSchematic(circuit: Circuit): Schematic {
  const placed: PlacedGlyph[] = [];
  const colInfo: { x0: number; x1: number }[] = [];

  // A subckt instance's declared port names (index-aligned to its nodes), so a
  // box/op-amp glyph can label its pins with the real schematic name. Undefined
  // for non-subckt elements (they have their own fixed pin names).
  const portsOf = (el: CircuitElement): string[] | undefined =>
    el.subckt ? circuit.subckts[el.subckt]?.ports : undefined;
  // Build the placed glyph for one element at (gx,gy) — single source of truth
  // for template + named pins, used by both the comb and generic placers.
  const placeGlyph = (el: CircuitElement, gx: number, gy: number, t: Template): PlacedGlyph => {
    const ports = portsOf(el);
    const pins = t.pins(el.nodes, ports).map((p) => ({ ...p, x: gx + p.x, y: gy + p.y }));
    return {
      ref: el.ref, shape: t.shape, value: el.value, note: el.note, el,
      x: gx, y: gy, w: t.w, h: t.h, pins,
      label: t.shape === "box" ? (el.subckt ?? el.ref) : undefined,
    };
  };
  const tmpl = (el: CircuitElement): Template => template(el, portsOf(el));

  // --- detect comb groups (parallel legs sharing the same {top,bot}) --------
  const chains = findChains(circuit);
  const groupKey = (c: Chain) => [c.top, c.bot].sort().join("|");
  const groups = new Map<string, Chain[]>();
  for (const c of chains)
    (groups.get(groupKey(c)) ?? groups.set(groupKey(c), []).get(groupKey(c))!).push(c);

  const byRef = new Map(circuit.elements.map((e) => [e.ref, e]));
  let x = MARGIN;
  let legH = 0;
  // largest parallel-leg group first (the decap comb)
  for (const grp of [...groups.values()].sort((a, b) => b.length - a.length)) {
    if (grp.length < 2) continue;            // singles → generic region
    for (const leg of grp) {
      const parts = leg.chain.map((rr) => byRef.get(rr)!);
      const colW = Math.max(...parts.map((p) => tmpl(p).w));
      let y = MARGIN + 30;
      for (const el of parts) {
        const t = tmpl(el);
        const gx = x + (colW - t.w) / 2, gy = y;
        placed.push(placeGlyph(el, gx, gy, t));
        y += t.h + GLYPH_GAP;
      }
      legH = Math.max(legH, y - MARGIN - 30);
      colInfo.push({ x0: x, x1: x + colW });
      x += colW + LEG_PITCH;
    }
  }

  // --- generic region: everything not already placed ------------------------
  const placedRefs = new Set(placed.map((p) => p.ref));
  const remaining = circuit.elements.filter((e) => !placedRefs.has(e.ref));
  const adj = new Map<string, Set<string>>();
  const link = (a: string, b: string) => {
    (adj.get(a) ?? adj.set(a, new Set()).get(a)!).add(b);
    (adj.get(b) ?? adj.set(b, new Set()).get(b)!).add(a);
  };
  for (const el of remaining) for (const nd of el.nodes) link("E:" + el.ref, "N:" + nd);
  const rank = new Map<string, number>();
  const seeds = [...new Set(remaining.flatMap((e) => e.nodes))].filter(isGnd).map((n) => "N:" + n);
  const start = seeds.length ? seeds : remaining[0] ? ["E:" + remaining[0].ref] : [];
  const seen = new Set(start); start.forEach((id) => rank.set(id, 0));
  let frontier = [...start], r = 0;
  while (frontier.length) {
    const next: string[] = [];
    for (const id of frontier)
      for (const nb of adj.get(id) ?? [])
        if (!seen.has(nb)) { seen.add(nb); rank.set(nb, r + 1); next.push(nb); }
    frontier = next; r += 1;
  }
  const maxRank = Math.max(0, ...[...rank.values()]);
  const elemRank = (ref: string) => rank.get("E:" + ref) ?? maxRank + 1;
  const rankGroups = new Map<number, CircuitElement[]>();
  for (const el of remaining) {
    const c = elemRank(el.ref);
    (rankGroups.get(c) ?? rankGroups.set(c, []).get(c)!).push(el);
  }
  const cols: CircuitElement[][] = [];
  for (const c of [...rankGroups.keys()].sort((a, b) => a - b)) {
    const els = rankGroups.get(c)!.sort((a, b) => a.ref.localeCompare(b.ref));
    for (let i = 0; i < els.length; i += MAX_PER_COL) cols.push(els.slice(i, i + MAX_PER_COL));
  }
  const colHeight = (els: CircuitElement[]) =>
    els.reduce((h, el) => h + tmpl(el).h + REST_GAP, -REST_GAP);
  const heights = cols.map(colHeight);
  const maxH = Math.max(legH, ...heights, 0);
  if (x > MARGIN) x += 40;                  // gap between comb and the rest
  const colHasWide = (els: CircuitElement[]) =>
    els.some((el) => { const s = classify(el); return s === "opamp" || s === "box"; });
  cols.forEach((els, ci) => {
    // extra space BEFORE an op-amp/IC column too, so the previous column's
    // right-side ref labels don't run into the triangle/box.
    if (colHasWide(els) && ci > 0) x += OPAMP_CLEARANCE;
    const colW = Math.max(...els.map((el) => tmpl(el).w));
    let y = MARGIN + (maxH - heights[ci]) / 2;
    for (const el of els) {
      const t = tmpl(el);
      const gx = x + (colW - t.w) / 2, gy = y;
      placed.push(placeGlyph(el, gx, gy, t));
      y += t.h + REST_GAP;
    }
    colInfo.push({ x0: x, x1: x + colW });
    // Op-amp / IC columns get a wider gutter AFTER too, so net lanes route well
    // clear of the body instead of hugging it (the op-amp feedback loop is the
    // one shape the generic router crowds).
    x += colW + GUTTER_PAD * 2 + (colHasWide(els) ? OPAMP_CLEARANCE : 0);
  });

  const totalH = MARGIN * 2 + Math.max(legH + 30, maxH);
  return routeSchematic(placed, colInfo, x, totalH);
}

// Route nets: private leg-nodes connect directly (vertical); multi-pin nets get
// a gutter LANE whose x is searched outward until it clears all glyph bodies
// (and so do its pin stubs); ground pins drop to GND symbols.
function routeSchematic(
  placed: PlacedGlyph[],
  colInfo: { x0: number; x1: number }[],
  x: number,
  totalH: number,
): Schematic {
  const wires: Wire[] = [];
  const junctions: Junction[] = [];
  const grounds: GndSym[] = [];
  const labels: NetLabel[] = [];

  const pinsByNet = new Map<string, GlyphPin[]>();
  for (const g of placed)
    for (const p of g.pins)
      (pinsByNet.get(p.net) ?? pinsByNet.set(p.net, []).get(p.net)!).push(p);

  const colOfX = (px: number) => {
    for (let i = 0; i < colInfo.length; i++)
      if (px <= colInfo[i].x1 + GUTTER_PAD * 2) return i;
    return colInfo.length - 1;
  };
  // A lane must keep BODY_CLEAR from every body's x-extent over its y-span.
  // Op-amp/box bodies get extra clearance so lanes never hug the triangle.
  const laneHitsBody = (lx: number, y0: number, y1: number) =>
    placed.some((g) => {
      const wide = g.shape === "opamp" || g.shape === "box";
      const m = wide ? OPAMP_CLEARANCE / 2 : BODY_CLEAR;
      return lx > g.x - m && lx < g.x + g.w + m &&
        Math.max(y0, g.y) < Math.min(y1, g.y + g.h);
    });
  const stubHitsBody = (p: GlyphPin, lx: number) => {
    const xmin = Math.min(p.x, lx), xmax = Math.max(p.x, lx);
    return placed.some((g) =>
      !g.pins.includes(p) && xmax > g.x + 4 && xmin < g.x + g.w - 4 &&
      p.y > g.y + 2 && p.y < g.y + g.h - 2 &&
      !g.pins.some((q) => Math.abs(q.x - p.x) < 1 && Math.abs(q.y - p.y) < 1));
  };

  const laneCount = new Map<number, number>();
  for (const [net, pins] of pinsByNet) {
    if (isGnd(net) || pins.length === 1) continue;
    // private 2-pin node inside a leg (same x) → direct vertical connect
    if (pins.length === 2 && Math.abs(pins[0].x - pins[1].x) < 2) {
      wires.push({ x1: pins[0].x, y1: pins[0].y, x2: pins[1].x, y2: pins[1].y, net });
      continue;
    }
    const lc = Math.min(...pins.map((p) => colOfX(p.x)));
    const ys = pins.map((p) => p.y);
    const yMin = Math.min(...ys), yMax = Math.max(...ys);
    let used = laneCount.get(lc) ?? 0, laneX = 0, tries = 0;
    do {
      laneX = Math.round(colInfo[lc].x1 + GUTTER_PAD + used * LANE_PITCH);
      used += 1; tries += 1;
    } while (tries < 40 && (laneHitsBody(laneX, yMin, yMax) || pins.some((p) => stubHitsBody(p, laneX))));
    laneCount.set(lc, used);
    if (yMax > yMin) wires.push({ x1: laneX, y1: yMin, x2: laneX, y2: yMax, net });
    for (const p of pins) {
      routePinToLane(p, laneX, placed, wires);
      junctions.push({ x: laneX, y: p.y, net: net });
    }
    labels.push({ x: laneX + 3, y: yMin - 6, text: net, anchor: "start" });
  }
  for (const [net, pins] of pinsByNet) {
    if (!isGnd(net)) continue;
    for (const p of pins) {
      const s = stubEnd(p, 16);
      wires.push({ x1: p.x, y1: p.y, x2: s.x, y2: s.y, net });
      grounds.push({ x: s.x, y: s.y, net });
    }
  }
  for (const [net, pins] of pinsByNet) {
    if (isGnd(net) || pins.length !== 1) continue;
    const s = stubEnd(pins[0], 24);
    wires.push({ x1: pins[0].x, y1: pins[0].y, x2: s.x, y2: s.y, net });
    labels.push({ x: s.x, y: s.y, text: net });
  }

  // Sanity: after ALL routing, every non-ground pin must have a wire endpoint AT
  // it. A dogleg/lane that failed to land on its pin is exactly the "disconnect"
  // defect the user saw — give any such pin a short fallback stub so it's never
  // left floating. (Runs last so it can't double-stub a single-pin net.)
  for (const g of placed)
    for (const p of g.pins) {
      if (isGnd(p.net)) continue;
      const touched = wires.some((w) =>
        (Math.abs(w.x1 - p.x) < 1.5 && Math.abs(w.y1 - p.y) < 1.5) ||
        (Math.abs(w.x2 - p.x) < 1.5 && Math.abs(w.y2 - p.y) < 1.5));
      if (!touched) {
        const s = stubEnd(p, 12);
        wires.push({ x1: p.x, y1: p.y, x2: s.x, y2: s.y, net: p.net });
      }
    }

  const totalW = x - GUTTER_PAD * 2 + MARGIN + LABEL_PAD;
  return { glyphs: placed, wires, junctions, grounds, labels, W: totalW, H: totalH };
}

// Geometric guard: glyph overlaps + wires crossing a body they don't connect to.
// Used as a dev-time regression check (the layout aims for zero); returns the
// list of issues so a caller can warn rather than silently ship a messy render.
export function lintSchematic(s: Schematic): string[] {
  const issues: string[] = [];
  for (let i = 0; i < s.glyphs.length; i++)
    for (let j = i + 1; j < s.glyphs.length; j++) {
      const a = s.glyphs[i], b = s.glyphs[j];
      if (a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y)
        issues.push(`overlap ${a.ref}∩${b.ref}`);
    }
  // A wire crosses a glyph if it enters the body INTERIOR. A wire that merely
  // terminates at one of the glyph's own pins is a legitimate lead — but ONLY
  // the short run from that pin to the nearest body edge is allowed; a wire that
  // starts at a left pin and continues PAST the right edge (straight through the
  // triangle) is a real crossing. So: clip the wire to the body box, then check
  // whether the clipped segment reaches deeper than a pin-stub tolerance.
  const PIN_TOL = 8;
  for (const w of s.wires)
    for (const g of s.glyphs) {
      const x0 = g.x + 3, x1 = g.x + g.w - 3, y0 = g.y + 3, y1 = g.y + g.h - 3;
      const wxmin = Math.min(w.x1, w.x2), wxmax = Math.max(w.x1, w.x2);
      const wymin = Math.min(w.y1, w.y2), wymax = Math.max(w.y1, w.y2);
      // overlap of the wire's bbox with the body interior
      const ox = Math.min(wxmax, x1) - Math.max(wxmin, x0);
      const oy = Math.min(wymax, y1) - Math.max(wymin, y0);
      if (ox <= 0 || oy <= 0) continue;          // no interior overlap
      // Does the wire terminate at one of THIS glyph's pins? If so, allow a
      // stub-length penetration; flag only if it goes deeper than PIN_TOL.
      const endsOnOwnPin = g.pins.some((p) =>
        (Math.abs(p.x - w.x1) < 1 && Math.abs(p.y - w.y1) < 1) ||
        (Math.abs(p.x - w.x2) < 1 && Math.abs(p.y - w.y2) < 1));
      const penetration = Math.max(ox, oy);       // how far it reaches into the body
      if (endsOnOwnPin && penetration <= PIN_TOL) continue;
      issues.push(`wire ${w.net} crosses ${g.ref}`);
    }
  return [...new Set(issues)];
}

// A short stub endpoint in the pin's leave direction.
function stubEnd(p: GlyphPin, len: number): { x: number; y: number } {
  switch (p.dir) {
    case "up": return { x: p.x, y: p.y - len };
    case "down": return { x: p.x, y: p.y + len };
    case "left": return { x: p.x - len, y: p.y };
    case "right": return { x: p.x + len, y: p.y };
  }
}

// Route a pin to a vertical lane at laneX. A straight horizontal stub is used
// when it stays clear of the pin's own body; otherwise (e.g. an op-amp + input
// faces LEFT but its net's lane is to the RIGHT) we dogleg: exit in the pin's
// `dir` to clear the body, jog vertically clear of it, then run across to the
// lane. CRITICAL: two pins on the SAME body (the op-amp's + and - inputs) must
// get DISTINCT corridors, or their doglegs overlap and read as one shorted wire.
// We stagger the exit-x and the jog-y by the pin's index among its same-side
// siblings, and jog a top-half pin UP / a bottom-half pin DOWN so the two never
// share a path.
function routePinToLane(
  p: GlyphPin, laneX: number, placed: PlacedGlyph[], wires: Wire[],
): void {
  const owner = placed.find((g) => g.pins.includes(p));
  const straightCrosses = owner &&
    laneX > owner.x + 3 && laneX < owner.x + owner.w - 3
      ? false                                   // lane inside own body: handled below
      : owner && crossesBody(p.x, p.y, laneX, p.y, owner);
  // If a straight stub would cut through the pin's own body, dogleg around it.
  if (owner && (straightCrosses || sideMismatch(p, laneX, owner))) {
    // siblings facing the SAME way that ALSO have to dogleg to the same side —
    // index this pin among them so each gets its own corridor.
    const sibs = owner.pins
      .filter((q) => q.dir === p.dir)
      .sort((a, b) => a.y - b.y);
    const k = Math.max(0, sibs.indexOf(p));     // 0,1,2… distinct per same-side pin
    const clear = 14 + k * 12;                  // staggered exit distance past the edge
    const exitX = p.dir === "left" ? owner.x - clear
                : p.dir === "right" ? owner.x + owner.w + clear
                : p.x;
    // jog ABOVE the body for a top-half pin, BELOW for a bottom-half pin, each at
    // a per-pin offset so sibling corridors never coincide.
    const mid = owner.y + owner.h / 2;
    const jogY = p.y <= mid
      ? owner.y - 12 - k * 12
      : owner.y + owner.h + 12 + k * 12;
    // 1) out along the pin direction to its own corridor x
    wires.push({ x1: p.x, y1: p.y, x2: exitX, y2: p.y, net: p.net });
    // 2) vertical jog clear of the body (up or down, per-pin level)
    wires.push({ x1: exitX, y1: p.y, x2: exitX, y2: jogY, net: p.net });
    // 3) across to the lane x at that level, then back to the pin's y on the lane
    wires.push({ x1: exitX, y1: jogY, x2: laneX, y2: jogY, net: p.net });
    wires.push({ x1: laneX, y1: jogY, x2: laneX, y2: p.y, net: p.net });
    return;
  }
  wires.push({ x1: p.x, y1: p.y, x2: laneX, y2: p.y, net: p.net });
}

// True when the pin faces away from the lane (left pin, lane to the right, or
// vice-versa) AND the lane is on the far side of the body — i.e. a straight
// stub would have to traverse the body.
function sideMismatch(p: GlyphPin, laneX: number, owner: PlacedGlyph): boolean {
  if (p.dir === "left" && laneX > owner.x + owner.w) return true;
  if (p.dir === "right" && laneX < owner.x) return true;
  return false;
}

function crossesBody(x1: number, y1: number, x2: number, y2: number, g: PlacedGlyph): boolean {
  const xmin = Math.min(x1, x2), xmax = Math.max(x1, x2);
  const ymin = Math.min(y1, y2), ymax = Math.max(y1, y2);
  return xmax > g.x + 6 && xmin < g.x + g.w - 6 && ymax > g.y + 3 && ymin < g.y + g.h - 3;
}
