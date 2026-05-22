// Shared schematic data model. All coordinates are in schematic units; one
// schematic unit is one grid step at zoom = 1. Symbols are designed around a
// local origin so they rotate cleanly about their center.

export type Point = { x: number; y: number };

export type Rotation = 0 | 90 | 180 | 270;

export type Orientation = "horizontal" | "vertical";

/** Electrical type used later for ERC. Optional for the MVP renderer. */
export type PinElectricalType =
  | "passive"
  | "input"
  | "output"
  | "bidirectional"
  | "power"
  | "ground"
  | "unspecified";

export interface PinDef {
  /** Stable id within the symbol, e.g. "1", "A", "K". */
  id: string;
  /** Human-readable name shown in the properties panel. */
  name: string;
  /** Pin endpoint in the symbol's local coordinates. Must land on the grid. */
  x: number;
  y: number;
  electricalType?: PinElectricalType;
}

export interface SymbolDefinition {
  /** Library-unique id, e.g. "resistor", "cap-polar". */
  id: string;
  name: string;
  category: "Passive" | "Active" | "Power" | "Connector" | "Other";
  /** Default reference designator prefix, e.g. "R", "C", "U". */
  refPrefix: string;
  /** Suggested default value, e.g. "10k", "100nF". */
  defaultValue?: string;
  /** Bounding box in local coordinates (used for hit testing/preview). */
  bbox: { x: number; y: number; width: number; height: number };
  /** Connection points. Local coordinates, rotated with the symbol instance. */
  pins: PinDef[];
  /**
   * SVG body of the symbol drawn in local coordinates. Should not include
   * pin endpoints (those are rendered by the canvas) and should be styled
   * with currentColor so themes apply.
   */
  body: React.ReactNode;
}

/** An instance of a library symbol placed on the schematic. */
export interface PlacedSymbol {
  id: string;
  symbolId: string;
  position: Point;
  rotation: Rotation;
  designator: string;
  value: string;
}

/**
 * A wire is an ordered polyline of grid points. Two consecutive points must
 * be axis-aligned (Manhattan routing). Endpoints may optionally pin into a
 * symbol pin via PinRef.
 */
export interface Wire {
  id: string;
  points: Point[];
  /** Endpoint connections (start = points[0], end = last point). */
  startPin?: PinRef;
  endPin?: PinRef;
}

export interface PinRef {
  symbolInstanceId: string;
  pinId: string;
}

export type Tool = "select" | "wire" | "pan";

/** Selection can hold any number of symbol or wire ids. */
export interface Selection {
  symbolIds: string[];
  wireIds: string[];
}

export interface Viewport {
  /** Pan offset in screen pixels. */
  panX: number;
  panY: number;
  /** Zoom multiplier; 1 means 1 schematic unit = 1 px. */
  zoom: number;
}

export interface Schematic {
  symbols: Record<string, PlacedSymbol>;
  wires: Record<string, Wire>;
}
