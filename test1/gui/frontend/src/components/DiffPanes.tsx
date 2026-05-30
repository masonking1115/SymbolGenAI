/* DiffPanes — image-pane renderer for the right-side schematic pane (replaces
 * PngViewer in App.tsx when a Review-tab loop has completed but is not yet
 * accepted/rejected). State (active sheet, mode, diff data) lives in App.tsx.
 *
 * Side-by-side: BEFORE (snapshot) | AFTER (current). Overlay: AFTER with all
 * boxes superimposed. Sheet-tab strip across the top so this pane can be
 * navigated without going through Review's content column.
 */
import { DiffOverlay, type DiffBox } from "./DiffOverlay";

export type DiffMode = "side" | "overlay";

interface DiffSheetData {
  viewBox: string;
  added: Record<string, { x: number; y: number; kind: "added" }>;
  removed: Record<string, { x: number; y: number; kind: "removed" }>;
  changed: Record<string, { x: number; y: number; kind: "changed"; from_value: string; to_value: string }>;
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
  const boxes: DiffBox[] = current
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
        <div className="ml-auto flex items-center gap-1 text-[11px]">
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

      <div className="flex-1 min-h-0 overflow-auto p-3">
        {current ? (
          mode === "side" ? (
            <div className="grid grid-cols-2 gap-3 h-full min-h-0">
              <DiffPane title="BEFORE (snapshot)"
                src={`/api/png_snapshot/${loopId}/${activeSheet}`}
                boxes={boxes.filter(b => b.kind === "removed" || b.kind === "changed")}
                viewBox={current.viewBox} />
              <DiffPane title="AFTER (current)"
                src={`/api/png/${activeSheet}`}
                boxes={boxes.filter(b => b.kind === "added" || b.kind === "changed")}
                viewBox={current.viewBox} />
            </div>
          ) : (
            <DiffPane title="OVERLAY"
              src={`/api/png/${activeSheet}`}
              boxes={boxes}
              viewBox={current.viewBox} />
          )
        ) : (
          <div className="text-sm text-ink-500 p-8 text-center">No sheet selected.</div>
        )}
      </div>
    </div>
  );
}

function DiffPane({ title, src, boxes, viewBox }:
  { title: string; src: string; boxes: DiffBox[]; viewBox: string }) {
  return (
    <div className="rounded border border-edge bg-white flex flex-col min-h-0">
      <div className="text-[10px] uppercase tracking-wide text-ink-500 px-2 py-1 border-b border-edge">{title}</div>
      <div className="relative flex-1 min-h-0 overflow-auto">
        <img src={src} alt={title} className="w-full block" />
        <DiffOverlay boxes={boxes} viewBox={viewBox}
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }} />
      </div>
    </div>
  );
}
