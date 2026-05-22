import type { PinDef, Point, Rotation } from "@/types/schematic";

/** Grid step in schematic units. Pins are required to land on multiples. */
export const GRID = 10;

export function snap(value: number, step: number = GRID): number {
  return Math.round(value / step) * step;
}

export function snapPoint(p: Point, step: number = GRID): Point {
  return { x: snap(p.x, step), y: snap(p.y, step) };
}

/** Rotate a point about the origin by the given multiple of 90 degrees. */
export function rotatePoint(p: Point, rotation: Rotation): Point {
  switch (rotation) {
    case 0:
      return { x: p.x, y: p.y };
    case 90:
      return { x: -p.y, y: p.x };
    case 180:
      return { x: -p.x, y: -p.y };
    case 270:
      return { x: p.y, y: -p.x };
  }
}

/** World-space position of a pin given a placed symbol's origin/rotation. */
export function pinWorldPosition(
  origin: Point,
  rotation: Rotation,
  pin: PinDef,
): Point {
  const r = rotatePoint({ x: pin.x, y: pin.y }, rotation);
  return { x: origin.x + r.x, y: origin.y + r.y };
}

/**
 * Manhattan route from a to b with a single bend.
 * `bendAxis` controls whether we go horizontal-first ('h') or vertical-first ('v').
 */
export function manhattanRoute(
  a: Point,
  b: Point,
  bendAxis: "h" | "v" = "h",
): Point[] {
  if (a.x === b.x || a.y === b.y) return [a, b];
  const corner: Point =
    bendAxis === "h" ? { x: b.x, y: a.y } : { x: a.x, y: b.y };
  return [a, corner, b];
}

export function pointsEqual(a: Point, b: Point): boolean {
  return a.x === b.x && a.y === b.y;
}

/** Distance from point p to the segment a-b (axis-aligned segments only). */
export function distanceToSegment(p: Point, a: Point, b: Point): number {
  if (a.x === b.x) {
    const minY = Math.min(a.y, b.y);
    const maxY = Math.max(a.y, b.y);
    const cy = Math.max(minY, Math.min(maxY, p.y));
    return Math.hypot(p.x - a.x, p.y - cy);
  }
  if (a.y === b.y) {
    const minX = Math.min(a.x, b.x);
    const maxX = Math.max(a.x, b.x);
    const cx = Math.max(minX, Math.min(maxX, p.x));
    return Math.hypot(p.x - cx, p.y - a.y);
  }
  // Diagonal fallback (shouldn't happen for Manhattan wires).
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lenSq = dx * dx + dy * dy;
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq));
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

export function nextRotation(r: Rotation): Rotation {
  return ((r + 90) % 360) as Rotation;
}
