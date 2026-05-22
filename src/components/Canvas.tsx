import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { GRID, snapPoint, pinWorldPosition } from "@/lib/geometry";
import { getSymbol } from "@/lib/symbolLibrary";
import {
  findPinAt,
  useSchematicStore,
  type WireDraft,
} from "@/store/schematicStore";
import type {
  PlacedSymbol,
  Point,
  Viewport,
  Wire,
} from "@/types/schematic";

import { PlacedSymbolView } from "./PlacedSymbolView";
import { WireView } from "./WireView";

interface DragState {
  symbolIds: string[];
  /** Symbol id -> initial position at drag start. */
  startPositions: Record<string, Point>;
  /** World point where the mouse went down. */
  startWorld: Point;
}

interface PanState {
  startScreen: Point;
  startPanX: number;
  startPanY: number;
}

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 8;
const PIN_SNAP_RADIUS_WORLD = 6;

function screenToWorld(p: Point, vp: Viewport): Point {
  return { x: (p.x - vp.panX) / vp.zoom, y: (p.y - vp.panY) / vp.zoom };
}

export const Canvas: React.FC = () => {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Slices of the store; small selectors keep re-renders tight.
  const symbols = useSchematicStore((s) => s.schematic.symbols);
  const wires = useSchematicStore((s) => s.schematic.wires);
  const viewport = useSchematicStore((s) => s.viewport);
  const tool = useSchematicStore((s) => s.tool);
  const selection = useSchematicStore((s) => s.selection);
  const placingSymbolId = useSchematicStore((s) => s.placingSymbolId);
  const placingRotation = useSchematicStore((s) => s.placingRotation);
  const wireDraft = useSchematicStore((s) => s.wireDraft);
  const cursor = useSchematicStore((s) => s.cursor);

  // Container size for full-bleed background.
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const r = el.getBoundingClientRect();
      setSize({ w: r.width, h: r.height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Transient interaction state.
  const dragRef = useRef<DragState | null>(null);
  const panRef = useRef<PanState | null>(null);
  const [spaceDown, setSpaceDown] = useState(false);

  // ---- helpers -----------------------------------------------------------

  const getScreenPoint = useCallback(
    (e: { clientX: number; clientY: number }): Point => {
      const el = svgRef.current;
      if (!el) return { x: 0, y: 0 };
      const r = el.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    },
    [],
  );

  const getWorldPoint = useCallback(
    (e: { clientX: number; clientY: number }, snap = true): Point => {
      const screen = getScreenPoint(e);
      const world = screenToWorld(screen, viewport);
      return snap ? snapPoint(world) : world;
    },
    [getScreenPoint, viewport],
  );

  // ---- mouse handlers ---------------------------------------------------

  const onMouseDownBackground = (e: React.MouseEvent<SVGSVGElement>) => {
    // Always allow panning with middle mouse, or with the Pan tool / Space held.
    if (
      e.button === 1 ||
      tool === "pan" ||
      (e.button === 0 && spaceDown)
    ) {
      const screen = getScreenPoint(e);
      panRef.current = {
        startScreen: screen,
        startPanX: viewport.panX,
        startPanY: viewport.panY,
      };
      e.preventDefault();
      return;
    }

    if (e.button !== 0) return;

    const world = getWorldPoint(e);

    // Placement mode: drop the queued symbol.
    if (placingSymbolId) {
      useSchematicStore.getState().commitPlacement(world);
      return;
    }

    // Wire tool: begin / continue wire.
    if (tool === "wire") {
      const store = useSchematicStore.getState();
      const pin = findPinAt(store, world, PIN_SNAP_RADIUS_WORLD);
      const at = pin
        ? pinWorldPosition(
            store.schematic.symbols[pin.symbolInstanceId].position,
            store.schematic.symbols[pin.symbolInstanceId].rotation,
            getSymbol(
              store.schematic.symbols[pin.symbolInstanceId].symbolId,
            )!.pins.find((p) => p.id === pin.pinId)!,
          )
        : world;

      if (!store.wireDraft) {
        store.beginWire(at, pin);
      } else {
        store.commitWireVertex(at, pin);
      }
      return;
    }

    // Select tool: clicked empty canvas → clear selection.
    useSchematicStore.getState().clearSelection();
  };

  const onMouseDownSymbol = (id: string) => (e: React.MouseEvent) => {
    if (tool !== "select" || placingSymbolId) return;
    e.stopPropagation();
    const store = useSchematicStore.getState();
    const multi = e.shiftKey;
    let nextSelectionSymbolIds: string[];
    if (multi) {
      const set = new Set(store.selection.symbolIds);
      if (set.has(id)) set.delete(id);
      else set.add(id);
      nextSelectionSymbolIds = Array.from(set);
      store.selectOnly({ symbolIds: nextSelectionSymbolIds });
    } else if (!store.selection.symbolIds.includes(id)) {
      nextSelectionSymbolIds = [id];
      store.selectOnly({ symbolIds: [id] });
    } else {
      nextSelectionSymbolIds = store.selection.symbolIds;
    }

    // Start drag for every selected symbol.
    const startWorld = getWorldPoint(e);
    const startPositions: Record<string, Point> = {};
    for (const sid of nextSelectionSymbolIds) {
      const sym = store.schematic.symbols[sid];
      if (sym) startPositions[sid] = sym.position;
    }
    dragRef.current = {
      symbolIds: nextSelectionSymbolIds,
      startPositions,
      startWorld,
    };
  };

  const onMouseDownPin =
    (symbolInstanceId: string, pinId: string) => (e: React.MouseEvent) => {
      if (placingSymbolId) return;
      e.stopPropagation();
      const store = useSchematicStore.getState();
      const sym = store.schematic.symbols[symbolInstanceId];
      const def = sym && getSymbol(sym.symbolId);
      const pin = def?.pins.find((p) => p.id === pinId);
      if (!sym || !def || !pin) return;
      const at = pinWorldPosition(sym.position, sym.rotation, pin);
      if (store.tool === "wire" && store.wireDraft) {
        store.commitWireVertex(at, { symbolInstanceId, pinId });
      } else {
        // Clicking a pin in any other tool starts a wire (auto-switch to wire tool).
        store.beginWire(at, { symbolInstanceId, pinId });
      }
    };

  const onMouseDownWire = (id: string) => (e: React.MouseEvent) => {
    if (tool !== "select" || placingSymbolId) return;
    e.stopPropagation();
    const store = useSchematicStore.getState();
    if (e.shiftKey) {
      const set = new Set(store.selection.wireIds);
      if (set.has(id)) set.delete(id);
      else set.add(id);
      store.selectOnly({
        symbolIds: store.selection.symbolIds,
        wireIds: Array.from(set),
      });
    } else {
      store.selectOnly({ wireIds: [id] });
    }
  };

  const onMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const store = useSchematicStore.getState();
    const screen = getScreenPoint(e);
    const world = snapPoint(screenToWorld(screen, viewport));
    store.setCursor(world);

    // Pan in progress.
    if (panRef.current) {
      const dx = screen.x - panRef.current.startScreen.x;
      const dy = screen.y - panRef.current.startScreen.y;
      store.setViewport({
        panX: panRef.current.startPanX + dx,
        panY: panRef.current.startPanY + dy,
      });
      return;
    }

    // Drag in progress.
    if (dragRef.current) {
      const dx = world.x - dragRef.current.startWorld.x;
      const dy = world.y - dragRef.current.startWorld.y;
      for (const id of dragRef.current.symbolIds) {
        const start = dragRef.current.startPositions[id];
        if (!start) continue;
        store.moveSymbol(id, { x: start.x + dx, y: start.y + dy });
      }
      return;
    }

    // Wire preview: snap to pin if cursor is near one.
    if (store.tool === "wire" && store.wireDraft) {
      const pin = findPinAt(store, world, PIN_SNAP_RADIUS_WORLD);
      const at = pin
        ? pinWorldPosition(
            store.schematic.symbols[pin.symbolInstanceId].position,
            store.schematic.symbols[pin.symbolInstanceId].rotation,
            getSymbol(
              store.schematic.symbols[pin.symbolInstanceId].symbolId,
            )!.pins.find((p) => p.id === pin.pinId)!,
          )
        : world;
      store.updateWireCursor(at);
    }
  };

  const onMouseUp = () => {
    panRef.current = null;
    dragRef.current = null;
  };

  const onContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    const store = useSchematicStore.getState();
    // Right-click cancels wire-in-progress / placement, otherwise no-op.
    if (store.wireDraft) {
      store.cancelWire();
    } else if (store.placingSymbolId) {
      store.cancelPlacement();
    }
  };

  const onWheel = (e: React.WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    const screen = getScreenPoint(e);
    const worldBefore = screenToWorld(screen, viewport);
    const factor = Math.exp(-e.deltaY * 0.0015);
    const newZoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, viewport.zoom * factor));
    // Hold the world point under the cursor in place.
    const panX = screen.x - worldBefore.x * newZoom;
    const panY = screen.y - worldBefore.y * newZoom;
    useSchematicStore.getState().setViewport({ zoom: newZoom, panX, panY });
  };

  // Disable native page wheel scroll over the canvas (passive listener fix).
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => e.preventDefault();
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, []);

  // ---- keyboard shortcuts ------------------------------------------------

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Don't capture keys when a form input is focused.
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;

      const store = useSchematicStore.getState();
      if (e.key === " " && !spaceDown) {
        setSpaceDown(true);
        e.preventDefault();
      }
      if (e.key === "Escape") {
        if (store.wireDraft) store.cancelWire();
        else if (store.placingSymbolId) store.cancelPlacement();
        else store.clearSelection();
      }
      if (e.key === "Delete" || e.key === "Backspace") {
        store.deleteSelection();
      }
      if (e.key === "r" || e.key === "R") {
        if (store.placingSymbolId) {
          store.rotatePlacement();
        } else {
          for (const id of store.selection.symbolIds) store.rotateSymbol(id);
        }
      }
      if (e.key === "w" || e.key === "W") {
        store.setTool("wire");
      }
      if (e.key === "s" || e.key === "S") {
        store.setTool("select");
      }
      if (e.key === "Tab" && store.wireDraft) {
        e.preventDefault();
        store.toggleWireBend();
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.key === " ") setSpaceDown(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [spaceDown]);

  // ---- render -----------------------------------------------------------

  const cursorStyle = useMemo(() => {
    if (panRef.current || tool === "pan" || spaceDown) return "grab";
    if (placingSymbolId || tool === "wire") return "crosshair";
    return "default";
  }, [tool, placingSymbolId, spaceDown]);

  const placingDef = placingSymbolId ? getSymbol(placingSymbolId) : undefined;
  const ghostSymbol: PlacedSymbol | null =
    placingDef && cursor
      ? {
          id: "__ghost",
          symbolId: placingDef.id,
          position: cursor,
          rotation: placingRotation,
          designator: placingDef.refPrefix,
          value: placingDef.defaultValue ?? "",
        }
      : null;

  const previewPoints = buildPreviewPoints(wireDraft);

  return (
    <div className="canvas" ref={containerRef}>
      <svg
        ref={svgRef}
        className="canvas__svg"
        style={{ cursor: cursorStyle }}
        width="100%"
        height="100%"
        onMouseDown={onMouseDownBackground}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
        onContextMenu={onContextMenu}
        onWheel={onWheel}
      >
        <defs>
          <pattern
            id="grid-dot"
            width={GRID}
            height={GRID}
            patternUnits="userSpaceOnUse"
            patternTransform={`translate(${viewport.panX} ${viewport.panY}) scale(${viewport.zoom})`}
          >
            <circle cx={0} cy={0} r={0.5} className="grid-dot" />
          </pattern>
          <pattern
            id="grid-major"
            width={GRID * 10}
            height={GRID * 10}
            patternUnits="userSpaceOnUse"
            patternTransform={`translate(${viewport.panX} ${viewport.panY}) scale(${viewport.zoom})`}
          >
            <path
              d={`M ${GRID * 10} 0 L 0 0 0 ${GRID * 10}`}
              className="grid-major-line"
              fill="none"
            />
          </pattern>
        </defs>

        <rect width={size.w} height={size.h} fill="url(#grid-dot)" />
        <rect width={size.w} height={size.h} fill="url(#grid-major)" />

        <g
          transform={`translate(${viewport.panX} ${viewport.panY}) scale(${viewport.zoom})`}
        >
          {/* Wires below symbols so pins overlay junctions cleanly. */}
          {Object.values(wires).map((w: Wire) => (
            <WireView
              key={w.id}
              wire={w}
              selected={selection.wireIds.includes(w.id)}
              onMouseDown={onMouseDownWire(w.id)}
            />
          ))}

          {/* Wire preview while drawing */}
          {previewPoints && <WireView points={previewPoints} preview />}

          {/* Placed symbols */}
          {Object.values(symbols).map((sym) => {
            const def = getSymbol(sym.symbolId);
            if (!def) return null;
            return (
              <PlacedSymbolView
                key={sym.id}
                placed={sym}
                def={def}
                selected={selection.symbolIds.includes(sym.id)}
                onMouseDown={onMouseDownSymbol(sym.id)}
                onPinMouseDown={(pinId, e) =>
                  onMouseDownPin(sym.id, pinId)(e)
                }
              />
            );
          })}

          {/* Placement ghost */}
          {ghostSymbol && placingDef && (
            <PlacedSymbolView placed={ghostSymbol} def={placingDef} ghost />
          )}
        </g>
      </svg>
    </div>
  );
};

function buildPreviewPoints(draft: WireDraft | null): Point[] | null {
  if (!draft) return null;
  const { anchor, cursor, trail, bendAxis } = draft;
  const leg =
    anchor.x === cursor.x || anchor.y === cursor.y
      ? [anchor, cursor]
      : bendAxis === "h"
        ? [anchor, { x: cursor.x, y: anchor.y }, cursor]
        : [anchor, { x: anchor.x, y: cursor.y }, cursor];
  if (trail.length === 0) return leg;
  return [...trail, ...leg.slice(1)];
}
