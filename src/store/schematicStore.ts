import { create } from "zustand";
import { nanoid } from "nanoid";

import { getSymbol } from "@/lib/symbolLibrary";
import { nextRotation, pinWorldPosition } from "@/lib/geometry";
import type {
  PinRef,
  PlacedSymbol,
  Point,
  Rotation,
  Schematic,
  Selection,
  Tool,
  Viewport,
  Wire,
} from "@/types/schematic";

/** Transient state for the wire-drawing tool. */
export interface WireDraft {
  /** Anchor for the segment currently being drawn. */
  anchor: Point;
  /** Cursor position in schematic coords, snapped to grid. */
  cursor: Point;
  /** Committed corner points behind the anchor (not yet finalized as a wire). */
  trail: Point[];
  /** Pin the wire originated from, if any. */
  startPin?: PinRef;
  /** Horizontal-first vs vertical-first bend for the current leg. */
  bendAxis: "h" | "v";
}

interface StoreState {
  schematic: Schematic;
  viewport: Viewport;
  tool: Tool;
  selection: Selection;

  /** Cursor position in schematic units, snapped to grid (for status bar). */
  cursor: Point;

  /** Symbol id queued for placement (from palette). Null = no placement. */
  placingSymbolId: string | null;
  placingRotation: Rotation;

  wireDraft: WireDraft | null;

  // --- Actions --------------------------------------------------------------

  setTool: (tool: Tool) => void;
  setViewport: (v: Partial<Viewport>) => void;
  setCursor: (p: Point) => void;

  beginPlacement: (symbolId: string) => void;
  cancelPlacement: () => void;
  rotatePlacement: () => void;
  commitPlacement: (at: Point) => void;

  placeSymbol: (symbolId: string, at: Point, rotation?: Rotation) => string;
  moveSymbol: (id: string, to: Point) => void;
  rotateSymbol: (id: string) => void;
  updateSymbol: (id: string, patch: Partial<PlacedSymbol>) => void;

  beginWire: (at: Point, startPin?: PinRef) => void;
  updateWireCursor: (at: Point) => void;
  commitWireVertex: (at: Point, endPin?: PinRef) => void;
  toggleWireBend: () => void;
  cancelWire: () => void;

  selectOnly: (sel: Partial<Selection>) => void;
  addToSelection: (sel: Partial<Selection>) => void;
  clearSelection: () => void;

  deleteSelection: () => void;
}

const initialSchematic: Schematic = { symbols: {}, wires: {} };
const initialViewport: Viewport = { panX: 0, panY: 0, zoom: 1.5 };
const emptySelection: Selection = { symbolIds: [], wireIds: [] };

// Track the next ref-designator suffix per prefix so placements auto-name.
function nextDesignator(
  symbols: Record<string, PlacedSymbol>,
  prefix: string,
): string {
  if (!prefix || /^(GND|VCC)$/i.test(prefix)) return prefix;
  let max = 0;
  for (const s of Object.values(symbols)) {
    const m = s.designator.match(new RegExp(`^${prefix}(\\d+)$`));
    if (m) max = Math.max(max, parseInt(m[1], 10));
  }
  return `${prefix}${max + 1}`;
}

export const useSchematicStore = create<StoreState>((set, get) => ({
  schematic: initialSchematic,
  viewport: initialViewport,
  tool: "select",
  selection: emptySelection,
  cursor: { x: 0, y: 0 },
  placingSymbolId: null,
  placingRotation: 0,
  wireDraft: null,

  setTool: (tool) =>
    set((s) => ({
      tool,
      // Switching tools clears in-progress operations.
      placingSymbolId: null,
      wireDraft: null,
      selection: tool === "select" ? s.selection : emptySelection,
    })),

  setViewport: (v) =>
    set((s) => ({ viewport: { ...s.viewport, ...v } })),

  setCursor: (p) => set({ cursor: p }),

  beginPlacement: (symbolId) =>
    set({
      placingSymbolId: symbolId,
      placingRotation: 0,
      tool: "select",
      wireDraft: null,
    }),

  cancelPlacement: () => set({ placingSymbolId: null, placingRotation: 0 }),

  rotatePlacement: () =>
    set((s) => ({ placingRotation: nextRotation(s.placingRotation) })),

  commitPlacement: (at) => {
    const { placingSymbolId, placingRotation } = get();
    if (!placingSymbolId) return;
    get().placeSymbol(placingSymbolId, at, placingRotation);
    // Stay in placement mode so the user can place multiples; press Esc to exit.
  },

  placeSymbol: (symbolId, at, rotation = 0) => {
    const def = getSymbol(symbolId);
    if (!def) return "";
    const id = nanoid(8);
    set((s) => {
      const designator = nextDesignator(s.schematic.symbols, def.refPrefix);
      const placed: PlacedSymbol = {
        id,
        symbolId,
        position: at,
        rotation,
        designator,
        value: def.defaultValue ?? "",
      };
      return {
        schematic: {
          ...s.schematic,
          symbols: { ...s.schematic.symbols, [id]: placed },
        },
      };
    });
    return id;
  },

  moveSymbol: (id, to) =>
    set((s) => {
      const existing = s.schematic.symbols[id];
      if (!existing) return s;
      return {
        schematic: {
          ...s.schematic,
          symbols: {
            ...s.schematic.symbols,
            [id]: { ...existing, position: to },
          },
        },
      };
    }),

  rotateSymbol: (id) =>
    set((s) => {
      const existing = s.schematic.symbols[id];
      if (!existing) return s;
      return {
        schematic: {
          ...s.schematic,
          symbols: {
            ...s.schematic.symbols,
            [id]: { ...existing, rotation: nextRotation(existing.rotation) },
          },
        },
      };
    }),

  updateSymbol: (id, patch) =>
    set((s) => {
      const existing = s.schematic.symbols[id];
      if (!existing) return s;
      return {
        schematic: {
          ...s.schematic,
          symbols: {
            ...s.schematic.symbols,
            [id]: { ...existing, ...patch },
          },
        },
      };
    }),

  beginWire: (at, startPin) =>
    set({
      tool: "wire",
      placingSymbolId: null,
      wireDraft: {
        anchor: at,
        cursor: at,
        trail: [],
        startPin,
        bendAxis: "h",
      },
    }),

  updateWireCursor: (at) =>
    set((s) => {
      if (!s.wireDraft) return s;
      return { wireDraft: { ...s.wireDraft, cursor: at } };
    }),

  toggleWireBend: () =>
    set((s) => {
      if (!s.wireDraft) return s;
      return {
        wireDraft: {
          ...s.wireDraft,
          bendAxis: s.wireDraft.bendAxis === "h" ? "v" : "h",
        },
      };
    }),

  commitWireVertex: (at, endPin) => {
    const draft = get().wireDraft;
    if (!draft) return;

    // If user clicked on the current anchor (no movement) and we have nothing
    // to commit, ignore. If they clicked on a pin or pressed Enter equivalent,
    // we finalize the wire.
    const finalize = !!endPin || (at.x === draft.anchor.x && at.y === draft.anchor.y && draft.trail.length === 0);

    if (finalize && draft.trail.length === 0 && draft.anchor.x === at.x && draft.anchor.y === at.y && !endPin) {
      // Single click at the same spot with no movement: cancel.
      set({ wireDraft: null });
      return;
    }

    // Build the polyline that adds this leg's points.
    const leg = buildLeg(draft.anchor, at, draft.bendAxis);
    const trail = [...draft.trail];
    if (trail.length === 0) trail.push(draft.anchor);
    for (const pt of leg.slice(1)) trail.push(pt);

    if (endPin || finalize) {
      // Finalize the wire.
      const id = nanoid(8);
      const wire: Wire = {
        id,
        points: simplifyPolyline(trail),
        startPin: draft.startPin,
        endPin,
      };
      set((s) => ({
        schematic: {
          ...s.schematic,
          wires: { ...s.schematic.wires, [id]: wire },
        },
        wireDraft: null,
      }));
      return;
    }

    // Continue drawing: advance the anchor to the new point.
    set({
      wireDraft: {
        anchor: at,
        cursor: at,
        trail,
        startPin: draft.startPin,
        bendAxis: draft.bendAxis,
      },
    });
  },

  cancelWire: () => set({ wireDraft: null }),

  selectOnly: (sel) =>
    set({
      selection: {
        symbolIds: sel.symbolIds ?? [],
        wireIds: sel.wireIds ?? [],
      },
    }),

  addToSelection: (sel) =>
    set((s) => ({
      selection: {
        symbolIds: dedup([...s.selection.symbolIds, ...(sel.symbolIds ?? [])]),
        wireIds: dedup([...s.selection.wireIds, ...(sel.wireIds ?? [])]),
      },
    })),

  clearSelection: () => set({ selection: emptySelection }),

  deleteSelection: () =>
    set((s) => {
      const symbols = { ...s.schematic.symbols };
      const wires = { ...s.schematic.wires };
      const deletedSyms = new Set(s.selection.symbolIds);
      for (const id of deletedSyms) delete symbols[id];
      for (const id of s.selection.wireIds) delete wires[id];
      // Also drop pin references on remaining wires that pointed at deleted symbols.
      for (const w of Object.values(wires)) {
        if (w.startPin && deletedSyms.has(w.startPin.symbolInstanceId)) {
          wires[w.id] = { ...w, startPin: undefined };
        }
        if (w.endPin && deletedSyms.has(w.endPin.symbolInstanceId)) {
          wires[w.id] = { ...wires[w.id], endPin: undefined };
        }
      }
      return {
        schematic: { symbols, wires },
        selection: emptySelection,
      };
    }),
}));

// --- helpers ---------------------------------------------------------------

function buildLeg(a: Point, b: Point, bendAxis: "h" | "v"): Point[] {
  if (a.x === b.x || a.y === b.y) return [a, b];
  const corner: Point =
    bendAxis === "h" ? { x: b.x, y: a.y } : { x: a.x, y: b.y };
  return [a, corner, b];
}

function simplifyPolyline(pts: Point[]): Point[] {
  if (pts.length < 3) return pts;
  const out: Point[] = [pts[0]];
  for (let i = 1; i < pts.length - 1; i++) {
    const a = out[out.length - 1];
    const b = pts[i];
    const c = pts[i + 1];
    const colinear =
      (a.x === b.x && b.x === c.x) || (a.y === b.y && b.y === c.y);
    if (!colinear) out.push(b);
  }
  out.push(pts[pts.length - 1]);
  return out;
}

function dedup<T>(arr: T[]): T[] {
  return Array.from(new Set(arr));
}

// --- selectors -------------------------------------------------------------

/**
 * Helper used by the canvas to test whether a clicked point is on a pin. Pins
 * within `tolerance` schematic units snap.
 */
export function findPinAt(
  state: StoreState,
  p: Point,
  tolerance = 5,
): PinRef | undefined {
  for (const sym of Object.values(state.schematic.symbols)) {
    const def = getSymbol(sym.symbolId);
    if (!def) continue;
    for (const pin of def.pins) {
      const world = pinWorldPosition(sym.position, sym.rotation, pin);
      if (Math.hypot(world.x - p.x, world.y - p.y) <= tolerance) {
        return { symbolInstanceId: sym.id, pinId: pin.id };
      }
    }
  }
  return undefined;
}
