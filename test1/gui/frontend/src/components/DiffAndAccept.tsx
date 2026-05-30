import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { DiffOverlay, type DiffBox } from "./DiffOverlay";
import { I } from "./Icon";

interface Props {
  loopId: string;
  loopStatus: string;        // "all_clear" | "plateau" | "max_rounds" | "cancelled" | "error"
  onResolved: () => void;     // called after Accept or Reject
}

type Mode = "side" | "overlay";

export function DiffAndAccept({ loopId, loopStatus, onResolved }: Props) {
  const [diff, setDiff] = useState<Awaited<ReturnType<typeof api.loopDiff>> | null>(null);
  const [activeSheet, setActiveSheet] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("side");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const d = await api.loopDiff(loopId);
      setDiff(d);
      if (!activeSheet) {
        // pick the sheet with the most changes
        const entries = Object.entries(d.sheets);
        if (entries.length > 0) {
          const winner = entries.sort((a, b) => b[1].count - a[1].count)[0];
          setActiveSheet(winner[0]);
        }
      }
    } catch (e) {
      console.error(e);
    }
  }, [loopId, activeSheet]);

  useEffect(() => { void refresh(); }, [refresh]);

  const accept = async () => {
    setBusy(true);
    try { await api.loopAccept(loopId); onResolved(); }
    finally { setBusy(false); }
  };
  const reject = async () => {
    setBusy(true);
    try { await api.loopReject(loopId); onResolved(); }
    finally { setBusy(false); }
  };

  if (!diff) return null;
  const sheets = Object.entries(diff.sheets);
  const totalAdded = sheets.reduce((s, [,d]) => s + Object.keys(d.added).length, 0);
  const totalRemoved = sheets.reduce((s, [,d]) => s + Object.keys(d.removed).length, 0);
  const totalChanged = sheets.reduce((s, [,d]) => s + Object.keys(d.changed).length, 0);

  const current = activeSheet ? diff.sheets[activeSheet] : null;
  const boxes: DiffBox[] = current
    ? [
        ...Object.entries(current.added).map(([rd, b]) => ({ ...b, refdes: rd })),
        ...Object.entries(current.removed).map(([rd, b]) => ({ ...b, refdes: rd })),
        ...Object.entries(current.changed).map(([rd, b]) => ({ ...b, refdes: rd })),
      ]
    : [];

  return (
    <section className="mt-5 rounded-md border border-edge bg-white">
      <header className="px-4 py-2.5 flex items-center gap-2 border-b border-edge">
        <I.Diff size={14} />
        <span className="text-sm font-semibold text-ink-900">Diff &amp; Accept</span>
        <span className="text-[11px] text-ink-500">
          loop {loopId.slice(0,8)} · {loopStatus} · +{totalAdded} -{totalRemoved} ~{totalChanged}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <div className="text-[11px] flex items-center gap-1">
            <button onClick={() => setMode("side")} className={mode==="side" ? "text-ink-900 font-medium" : "text-ink-500"}>side-by-side</button>
            <span className="text-ink-500">/</span>
            <button onClick={() => setMode("overlay")} className={mode==="overlay" ? "text-ink-900 font-medium" : "text-ink-500"}>overlay</button>
          </div>
        </div>
      </header>

      <div className="px-4 py-2 flex gap-1 flex-wrap border-b border-edge">
        {sheets.map(([stem, d]) => (
          <button key={stem}
            onClick={() => setActiveSheet(stem)}
            className={"px-2 py-0.5 text-[11.5px] rounded border " +
              (activeSheet === stem ? "border-ink-700 bg-rail/40" : "border-edge hover:border-ink-300")}>
            {stem} {d.count > 0 && <span className="text-[10px] text-ink-500">·{d.count}</span>}
          </button>
        ))}
      </div>

      {current && (
        <div className="p-4">
          {mode === "side" ? (
            <div className="grid grid-cols-2 gap-3">
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
          )}

          <ChangeList sheet={current} />
        </div>
      )}

      <footer className="px-4 py-3 border-t border-edge flex items-center gap-2">
        <button onClick={accept} disabled={busy}
          className="h-8 px-3 inline-flex items-center gap-1.5 rounded bg-ok text-white text-sm font-medium hover:bg-ok/90 disabled:opacity-50">
          <I.Check size={12} /> Accept all
        </button>
        <button onClick={reject} disabled={busy}
          className="h-8 px-3 inline-flex items-center gap-1.5 rounded border border-edge text-ink-700 text-sm hover:border-err hover:text-err disabled:opacity-50">
          ✗ Reject (revert)
        </button>
        <span className="text-[11px] text-ink-500 ml-2">
          Accept keeps the loop's changes. Reject restores the pre-loop state.
        </span>
      </footer>
    </section>
  );
}

function DiffPane({ title, src, boxes, viewBox }:
  { title: string; src: string; boxes: DiffBox[]; viewBox: string }) {
  return (
    <div className="rounded border border-edge bg-white">
      <div className="text-[10px] uppercase tracking-wide text-ink-500 px-2 py-1 border-b border-edge">{title}</div>
      <div className="relative">
        <img src={src} alt={title} className="w-full block" />
        <DiffOverlay boxes={boxes} viewBox={viewBox}
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }} />
      </div>
    </div>
  );
}

function ChangeList({ sheet }:
  { sheet: { added: Record<string, unknown>; removed: Record<string, unknown>; changed: Record<string, { from_value: string; to_value: string }> } }) {
  return (
    <details className="mt-3 text-[11.5px]">
      <summary className="cursor-pointer text-ink-700 hover:text-ink-900">Change list</summary>
      <ul className="mt-1.5 ml-3 space-y-0.5">
        {Object.entries(sheet.added).map(([rd]) => (
          <li key={"a"+rd}><span className="text-ok">+</span> {rd} added</li>
        ))}
        {Object.entries(sheet.removed).map(([rd]) => (
          <li key={"r"+rd}><span className="text-err">-</span> {rd} removed</li>
        ))}
        {Object.entries(sheet.changed).map(([rd, c]) => (
          <li key={"c"+rd}><span className="text-warn">~</span> {rd}: {c.from_value} → {c.to_value}</li>
        ))}
      </ul>
    </details>
  );
}
