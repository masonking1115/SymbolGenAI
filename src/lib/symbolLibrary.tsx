import React from "react";
import type { SymbolDefinition } from "@/types/schematic";

// All bodies are drawn in the symbol's local coordinate system; the canvas
// applies position + rotation transforms. Stroke uses `currentColor` so theme
// changes flow through. Pins are positioned on the grid (multiples of 10).

const Body: React.FC<React.SVGProps<SVGGElement> & { children: React.ReactNode }> = ({
  children,
  ...rest
}) => (
  <g
    fill="none"
    stroke="currentColor"
    strokeWidth={1.5}
    strokeLinecap="round"
    strokeLinejoin="round"
    {...rest}
  >
    {children}
  </g>
);

const Resistor: SymbolDefinition = {
  id: "resistor",
  name: "Resistor",
  category: "Passive",
  refPrefix: "R",
  defaultValue: "10k",
  bbox: { x: -30, y: -10, width: 60, height: 20 },
  pins: [
    { id: "1", name: "1", x: -30, y: 0, electricalType: "passive" },
    { id: "2", name: "2", x: 30, y: 0, electricalType: "passive" },
  ],
  body: (
    <Body>
      {/* Leads */}
      <line x1={-30} y1={0} x2={-20} y2={0} />
      <line x1={20} y1={0} x2={30} y2={0} />
      {/* Zigzag body */}
      <polyline points="-20,0 -16,-7 -12,7 -8,-7 -4,7 0,-7 4,7 8,-7 12,7 16,-7 20,0" />
    </Body>
  ),
};

const Capacitor: SymbolDefinition = {
  id: "capacitor",
  name: "Capacitor",
  category: "Passive",
  refPrefix: "C",
  defaultValue: "100nF",
  bbox: { x: -10, y: -20, width: 20, height: 40 },
  pins: [
    { id: "1", name: "1", x: 0, y: -20, electricalType: "passive" },
    { id: "2", name: "2", x: 0, y: 20, electricalType: "passive" },
  ],
  body: (
    <Body>
      <line x1={0} y1={-20} x2={0} y2={-5} />
      <line x1={0} y1={5} x2={0} y2={20} />
      <line x1={-10} y1={-5} x2={10} y2={-5} />
      <line x1={-10} y1={5} x2={10} y2={5} />
    </Body>
  ),
};

const Inductor: SymbolDefinition = {
  id: "inductor",
  name: "Inductor",
  category: "Passive",
  refPrefix: "L",
  defaultValue: "10uH",
  bbox: { x: -30, y: -8, width: 60, height: 12 },
  pins: [
    { id: "1", name: "1", x: -30, y: 0, electricalType: "passive" },
    { id: "2", name: "2", x: 30, y: 0, electricalType: "passive" },
  ],
  body: (
    <Body>
      <line x1={-30} y1={0} x2={-20} y2={0} />
      <line x1={20} y1={0} x2={30} y2={0} />
      {/* Four humps */}
      <path d="M -20 0 A 5 5 0 0 1 -10 0 A 5 5 0 0 1 0 0 A 5 5 0 0 1 10 0 A 5 5 0 0 1 20 0" />
    </Body>
  ),
};

const Diode: SymbolDefinition = {
  id: "diode",
  name: "Diode",
  category: "Active",
  refPrefix: "D",
  defaultValue: "1N4148",
  bbox: { x: -20, y: -10, width: 40, height: 20 },
  pins: [
    { id: "A", name: "Anode", x: -20, y: 0, electricalType: "passive" },
    { id: "K", name: "Cathode", x: 20, y: 0, electricalType: "passive" },
  ],
  body: (
    <Body>
      <line x1={-20} y1={0} x2={-10} y2={0} />
      <line x1={10} y1={0} x2={20} y2={0} />
      <polygon points="-10,-8 -10,8 10,0" />
      <line x1={10} y1={-8} x2={10} y2={8} />
    </Body>
  ),
};

const LED: SymbolDefinition = {
  id: "led",
  name: "LED",
  category: "Active",
  refPrefix: "D",
  defaultValue: "LED",
  bbox: { x: -20, y: -16, width: 44, height: 28 },
  pins: [
    { id: "A", name: "Anode", x: -20, y: 0, electricalType: "passive" },
    { id: "K", name: "Cathode", x: 20, y: 0, electricalType: "passive" },
  ],
  body: (
    <Body>
      <line x1={-20} y1={0} x2={-10} y2={0} />
      <line x1={10} y1={0} x2={20} y2={0} />
      <polygon points="-10,-8 -10,8 10,0" />
      <line x1={10} y1={-8} x2={10} y2={8} />
      {/* Light arrows */}
      <line x1={2} y1={-10} x2={8} y2={-16} />
      <polyline points="8,-12 8,-16 4,-16" />
      <line x1={-4} y1={-10} x2={2} y2={-16} />
      <polyline points="2,-12 2,-16 -2,-16" />
    </Body>
  ),
};

const NpnBjt: SymbolDefinition = {
  id: "bjt-npn",
  name: "NPN BJT",
  category: "Active",
  refPrefix: "Q",
  defaultValue: "2N3904",
  bbox: { x: -30, y: -30, width: 50, height: 60 },
  pins: [
    { id: "B", name: "Base", x: -30, y: 0, electricalType: "input" },
    { id: "C", name: "Collector", x: 20, y: -30, electricalType: "passive" },
    { id: "E", name: "Emitter", x: 20, y: 30, electricalType: "passive" },
  ],
  body: (
    <Body>
      <circle cx={0} cy={0} r={20} />
      {/* Base lead */}
      <line x1={-30} y1={0} x2={-10} y2={0} />
      {/* Body vertical bar */}
      <line x1={-10} y1={-12} x2={-10} y2={12} />
      {/* Collector */}
      <line x1={-10} y1={-6} x2={20} y2={-30} />
      {/* Emitter with arrow */}
      <line x1={-10} y1={6} x2={20} y2={30} />
      <polygon points="10,18 18,22 14,14" fill="currentColor" stroke="none" />
    </Body>
  ),
};

const PnpBjt: SymbolDefinition = {
  id: "bjt-pnp",
  name: "PNP BJT",
  category: "Active",
  refPrefix: "Q",
  defaultValue: "2N3906",
  bbox: { x: -30, y: -30, width: 50, height: 60 },
  pins: [
    { id: "B", name: "Base", x: -30, y: 0, electricalType: "input" },
    { id: "E", name: "Emitter", x: 20, y: -30, electricalType: "passive" },
    { id: "C", name: "Collector", x: 20, y: 30, electricalType: "passive" },
  ],
  body: (
    <Body>
      <circle cx={0} cy={0} r={20} />
      <line x1={-30} y1={0} x2={-10} y2={0} />
      <line x1={-10} y1={-12} x2={-10} y2={12} />
      <line x1={-10} y1={-6} x2={20} y2={-30} />
      <line x1={-10} y1={6} x2={20} y2={30} />
      {/* Inward arrow on emitter (top for PNP) */}
      <polygon points="-4,-12 4,-16 0,-22" fill="currentColor" stroke="none" />
    </Body>
  ),
};

const Ground: SymbolDefinition = {
  id: "gnd",
  name: "Ground",
  category: "Power",
  refPrefix: "GND",
  bbox: { x: -10, y: 0, width: 20, height: 20 },
  pins: [{ id: "1", name: "GND", x: 0, y: 0, electricalType: "ground" }],
  body: (
    <Body>
      <line x1={0} y1={0} x2={0} y2={6} />
      <line x1={-10} y1={6} x2={10} y2={6} />
      <line x1={-6} y1={11} x2={6} y2={11} />
      <line x1={-2} y1={16} x2={2} y2={16} />
    </Body>
  ),
};

const Vcc: SymbolDefinition = {
  id: "vcc",
  name: "VCC",
  category: "Power",
  refPrefix: "VCC",
  bbox: { x: -10, y: -20, width: 20, height: 20 },
  pins: [{ id: "1", name: "VCC", x: 0, y: 0, electricalType: "power" }],
  body: (
    <Body>
      <line x1={0} y1={0} x2={0} y2={-10} />
      <circle cx={0} cy={-14} r={4} />
      <text
        x={0}
        y={-24}
        textAnchor="middle"
        fontSize={8}
        fill="currentColor"
        stroke="none"
      >
        VCC
      </text>
    </Body>
  ),
};

const Header2: SymbolDefinition = {
  id: "hdr-1x2",
  name: "Header 1x2",
  category: "Connector",
  refPrefix: "J",
  bbox: { x: -10, y: -20, width: 20, height: 40 },
  pins: [
    { id: "1", name: "1", x: -10, y: -10, electricalType: "passive" },
    { id: "2", name: "2", x: -10, y: 10, electricalType: "passive" },
  ],
  body: (
    <Body>
      <rect x={-6} y={-18} width={12} height={36} />
      <line x1={-10} y1={-10} x2={-6} y2={-10} />
      <line x1={-10} y1={10} x2={-6} y2={10} />
    </Body>
  ),
};

export const SYMBOL_LIBRARY: SymbolDefinition[] = [
  Resistor,
  Capacitor,
  Inductor,
  Diode,
  LED,
  NpnBjt,
  PnpBjt,
  Ground,
  Vcc,
  Header2,
];

const BY_ID: Record<string, SymbolDefinition> = Object.fromEntries(
  SYMBOL_LIBRARY.map((s) => [s.id, s]),
);

export function getSymbol(id: string): SymbolDefinition | undefined {
  return BY_ID[id];
}

export function symbolsByCategory(): Record<string, SymbolDefinition[]> {
  const out: Record<string, SymbolDefinition[]> = {};
  for (const s of SYMBOL_LIBRARY) {
    (out[s.category] ??= []).push(s);
  }
  return out;
}
