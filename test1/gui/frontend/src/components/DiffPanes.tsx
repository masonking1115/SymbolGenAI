/* DiffPanes — image-pane renderer for the right-side schematic pane (replaces
 * PngViewer in App.tsx when a Review-tab loop has completed but is not yet
 * accepted/rejected). State (active sheet, mode, diff data) lives in App.tsx.
 *
 * Side-by-side: BEFORE (snapshot) | AFTER (current). Overlay: AFTER with all
 * boxes superimposed. Each pane uses the SAME pan/zoom Canvas as the main
 * schematic viewer (wheel-zoom-toward-cursor, click-drag pan, fit, +/-/0/F) —
 * just two of them, each independently draggable. The DiffOverlay rides the
 * same transform as the image so the highlight boxes stay aligned at any zoom.
 */
import { DiffOverlay, type DiffBox } from "./DiffOverlay";
import { Canvas, ImgLayer } from "./PngViewer";

export type DiffMode = "side" | "overlay";

interface DiffSheetData {
  viewBox: string;        // current-render viewBox (AFTER pane)
  snapViewBox?: string;   // snapshot-render viewBox (BEFORE pane); may differ if layout moved
  added: Record<string, { x: number; y: number; kind: "added" }>;
  removed: Record<string, { x: number; y: number; kind: "removed" }>;
  // changed parts carry BOTH anchors: x/y = current pos (AFTER), from_x/from_y = snapshot pos (BEFORE)
  changed: Record<string, { x: number; y: number; from_x?: number; from_y?: number; kind: "changed"; from_value: string; to_value: string }>;
  count: number;
}

interface DiffData {
  loop_id: string;
  sheets: Record<string, DiffSheetData>;
}

interface Props {
  loopId: string;
  diff: DiffData;
  activeSheet: string | null;
  setActiveSheet: (s: string) => void;
  mode: DiffMode;
  setMode: (m: DiffMode) => void;
}

export function DiffPanes({ loopId, diff, activeSheet, setActiveSheet, mode, setMode }: Props) {
  const sheets = Object.entries(diff.sheets);
  const current = activeSheet ? diff.sheets[activeSheet] : null;

  // BEFORE pane (snapshot image): removed parts (snapshot coords) + changed parts
  // drawn at their SNAPSHOT position (from_x/from_y). Falls back to x/y when the
  // backend didn't supply a snapshot anchor (older diffs / unmoved part).
  const beforeBoxes: DiffBox[] = current
    ? [
        ...Object.entries(current.removed).map(([rd, b]) => ({ ...b, refdes: rd })),
        ...Object.entries(current.changed).map(([rd, b]) => ({
          ...b, refdes: rd,
          x: b.from_x ?? b.x,
          y: b.from_y ?? b.y,
        })),
      ]
    : [];

  // AFTER pane (current image): added parts + changed parts at their CURRENT position.
  const afterBoxes: DiffBox[] = current
    ? [
        ...Object.entries(current.added).map(([rd, b]) => ({ ...b, refdes: rd })),
        ...Object.entries(current.changed).map(([rd, b]) => ({ ...b, refdes: rd })),
      ]
    : [];

  // Overlay mode draws everything on the current image, so it uses current coords.
  const overlayBoxes: DiffBox[] = current
    ? [
        ...Object.entries(current.added).map(([rd, b]) => ({ ...b, refdes: rd })),
        ...Object.entries(current.removed).map(([rd, b]) => ({ ...b, refdes: rd })),
        ...Object.entries(current.changed).map(([rd, b]) => ({ ...b, refdes: rd })),
      ]
    : [];

  return (
    <div className="h-full min-h-0 flex flex-col bg-rail/20">
      <header className="px-3 py-2 border-b border-edge bg-white flex items-center gap-2 flex-wrap">
        <span className="text-[11px] uppercase tracking-wide text-ink-500 font-medium">Diff</span>
        <span className="text-[11px] text-ink-500">loop {loopId.slice(0, 8)}</span>
        <div className="ml-auto flex items-center gap-2 text-[11px]">
          <button onClick={() => setMode("side")}
            className={mode === "side" ? "text-ink-900 font-medium" : "text-ink-500 hover:text-ink-900"}>
            side-by-side
          </button>
          <span className="text-ink-500">/</span>
          <button onClick={() => setMode("overlay")}
            className={mode === "overlay" ? "text-ink-900 font-medium" : "text-ink-500 hover:text-ink-900"}>
            overlay
          </button>
        </div>
      </header>

      <div className="px-3 py-1.5 flex gap-1 flex-wrap border-b border-edge bg-white">
        {sheets.map(([stem, d]) => (
          <button key={stem}
            onClick={() => setActiveSheet(stem)}
            className={"px-2 py-0.5 text-[11.5px] rounded border " +
              (activeSheet === stem ? "border-ink-700 bg-rail/40" : "border-edge hover:border-ink-300")}>
            {stem} {d.count > 0 && <span className="text-[10px] text-ink-500">·{d.count}</span>}
          </button>
        ))}
      </div>

      <div className="flex-1 min-h-0 p-3">
        {current ? (
          mode === "side" ? (
            <div className="grid grid-cols-2 gap-3 h-full min-h-0">
              <DiffPane key={`before-${activeSheet}`} title="BEFORE (snapshot)" tone="before"
                src={`/api/png_snapshot/${loopId}/${activeSheet}`}
                boxes={beforeBoxes}
                viewBox={current.snapViewBox || current.viewBox} />
              <DiffPane key={`after-${activeSheet}`} title="AFTER (current)" tone="after"
                src={`/api/png/${activeSheet}`}
                boxes={afterBoxes}
                viewBox={current.viewBox} />
            </div>
          ) : (
            <DiffPane key={`overlay-${activeSheet}`} title="OVERLAY" tone="kind"
              src={`/api/png/${activeSheet}`}
              boxes={overlayBoxes}
              viewBox={current.viewBox} />
          )
        ) : (
          <div className="text-sm text-ink-500 p-8 text-center">No sheet selected.</div>
        )}
      </div>
    </div>
  );
}

function DiffPane({ title, src, boxes, viewBox, tone }:
  { title: string; src: string; boxes: DiffBox[]; viewBox: string;
    tone: "before" | "after" | "kind" }) {
  // Parse "minX minY W H" so the overlay SVG can be sized to the image's natural
  // pixel box (it then rides Canvas's transform 1:1 with the image, like
  // RegionOverlay does in PngViewer).
  const parts = viewBox.trim().split(/\s+/).map(Number);
  const w = parts[2] || 0;
  const h = parts[3] || 0;
  return (
    <div className="rounded border border-edge bg-white flex flex-col min-h-0 overflow-hidden">
      <div className="text-[10px] uppercase tracking-wide text-ink-500 px-2 py-1 border-b border-edge shrink-0">{title}</div>
      <div className="relative flex-1 min-h-0">
        <Canvas>
          <ImgLayer src={src} />
          <DiffOverlay boxes={boxes} viewBox={viewBox} tone={tone}
            style={{ position: "absolute", left: 0, top: 0, width: w, height: h,
                     transformOrigin: "0 0", pointerEvents: "none", overflow: "visible" }} />
        </Canvas>
      </div>
    </div>
  );
}
