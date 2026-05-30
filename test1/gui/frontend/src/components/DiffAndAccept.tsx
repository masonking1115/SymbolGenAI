/* DiffAndAccept — controls bar for the Review tab when a loop has completed.
 *
 * Image panes live in <DiffPanes> in the App.tsx right pane (replaces PngViewer
 * while a completed loop is awaiting accept/reject). This component renders:
 *   • header bar with loop id + counts
 *   • sheet tab strip (sync'd with DiffPanes via lifted state)
 *   • mode toggle (side-by-side / overlay)
 *   • change list (collapsible)
 *   • Accept / Reject buttons
 */
import { useState } from "react";
import { api } from "../api";
import { I } from "./Icon";
import type { DiffMode } from "./DiffPanes";

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
  loopStatus: string;
  diff: DiffData;
  activeSheet: string | null;
  setActiveSheet: (s: string) => void;
  mode: DiffMode;
  setMode: (m: DiffMode) => void;
  hasRealDiff: boolean;
  diffVisible: boolean;
  setDiffVisibleOverride: (v: boolean | null) => void;
  onResolved: () => void;
}

export function DiffAndAccept({
  loopId, loopStatus, diff, activeSheet, setActiveSheet, mode, setMode,
  hasRealDiff, diffVisible, setDiffVisibleOverride, onResolved,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [rejectWarning, setRejectWarning] = useState<string | null>(null);

  const accept = async () => {
    setBusy(true);
    try { await api.loopAccept(loopId); onResolved(); }
    finally { setBusy(false); }
  };
  const reject = async () => {
    setBusy(true);
    setRejectWarning(null);
    try {
      const res = await api.loopReject(loopId);
      // Verify-after-revert guard: if the revert produced a WORSE state, the
      // backend rolls forward (restores the post-loop state) and returns ok=false
      // with a reason. Surface that instead of clearing the loop — the design was
      // NOT left in the bad reverted baseline.
      if (res.ok === false) {
        setRejectWarning(
          (res.rolled_forward
            ? "Revert was unsafe and has been UNDONE (rolled forward to the post-loop state). "
            : "Revert produced a worse state and could NOT be undone — check the design. ") +
          (res.reason ? res.reason + " " : "") +
          (res.rebuild_log_tail ? `Last log: ${res.rebuild_log_tail.slice(-300)}` : ""),
        );
        return; // keep the loop visible so the user sees what happened
      }
      // Legacy guard: a clean ok=true but failed rebuild (shouldn't happen with
      // the new path, but keep the warning for safety).
      if (res.rebuild_status === false) {
        setRejectWarning(
          "Reverted, but the rebuild failed — the schematic may be stale. " +
          "Regenerate from the Generator tab. " +
          (res.rebuild_log_tail ? `Last log: ${res.rebuild_log_tail.slice(-300)}` : ""),
        );
        return;
      }
      onResolved();
    }
    finally { setBusy(false); }
  };
  // Clear the loop's review residue (closed-loop changelog items + snapshot/diff)
  // WITHOUT touching the design. Use when you KEPT the changes but the changelog
  // + diff lingered with no way to dismiss them.
  const clear = async () => {
    setBusy(true);
    setRejectWarning(null);
    try { await api.loopClear(loopId); onResolved(); }
    finally { setBusy(false); }
  };

  const sheets = Object.entries(diff.sheets);
  const totalAdded   = sheets.reduce((s, [, d]) => s + Object.keys(d.added).length, 0);
  const totalRemoved = sheets.reduce((s, [, d]) => s + Object.keys(d.removed).length, 0);
  const totalChanged = sheets.reduce((s, [, d]) => s + Object.keys(d.changed).length, 0);
  const current = activeSheet ? diff.sheets[activeSheet] : null;

  return (
    <section className="mt-5 rounded-md border border-edge bg-white">
      <header className="px-4 py-2.5 flex items-center gap-2 border-b border-edge">
        <I.Diff size={14} />
        <span className="text-sm font-semibold text-ink-900">Diff &amp; Accept</span>
        <span className="text-[11px] text-ink-500">
          loop {loopId.slice(0, 8)} · {loopStatus} · +{totalAdded} -{totalRemoved} ~{totalChanged}
        </span>
        <span className="text-[11px] text-ink-500 ml-2">
          {diffVisible ? "(panes shown in right pane →)" :
            hasRealDiff ? "(panes hidden — toggle right →)" : "(no changes to diff)"}
        </span>
        <div className="ml-auto flex items-center gap-3 text-[11px]">
          {/* Right-pane diff toggle. Auto-on when changes exist, but the user
              can force-show (inspect a clean loop) or force-hide (keep the
              live schematic in view). */}
          <label className="inline-flex items-center gap-1.5 select-none cursor-pointer">
            <input
              type="checkbox"
              checked={diffVisible}
              onChange={(e) => {
                // Setting back to the auto default clears the override.
                const next = e.target.checked;
                setDiffVisibleOverride(next === hasRealDiff ? null : next);
              }}
            />
            <span className={diffVisible ? "text-ink-900" : "text-ink-500"}>diff in right pane</span>
          </label>
          <span className="text-ink-300">·</span>
          <button onClick={() => setMode("side")}
            disabled={!diffVisible}
            className={(mode === "side" ? "text-ink-900 font-medium" : "text-ink-500 hover:text-ink-900") + " disabled:opacity-40 disabled:hover:text-ink-500"}>
            side-by-side
          </button>
          <span className="text-ink-500">/</span>
          <button onClick={() => setMode("overlay")}
            disabled={!diffVisible}
            className={(mode === "overlay" ? "text-ink-900 font-medium" : "text-ink-500 hover:text-ink-900") + " disabled:opacity-40 disabled:hover:text-ink-500"}>
            overlay
          </button>
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

      {current && <ChangeList sheet={current} />}

      <footer className="px-4 py-3 border-t border-edge flex items-center gap-2 flex-wrap">
        <button onClick={accept} disabled={busy}
          className="h-8 px-3 inline-flex items-center gap-1.5 rounded bg-ok text-white text-sm font-medium hover:bg-ok/90 disabled:opacity-50">
          <I.Check size={12} /> Accept all
        </button>
        <button onClick={reject} disabled={busy}
          className="h-8 px-3 inline-flex items-center gap-1.5 rounded border border-edge text-ink-700 text-sm hover:border-err hover:text-err disabled:opacity-50">
          ✗ Reject (revert)
        </button>
        <button onClick={clear} disabled={busy}
          className="h-8 px-3 inline-flex items-center gap-1.5 rounded border border-edge text-ink-500 text-sm hover:border-ink-300 hover:text-ink-900 disabled:opacity-50"
          title="Clear the changelog + diff for this loop without changing the design (use when you kept the changes)">
          <I.X size={12} /> Clear changelog &amp; diff
        </button>
        <span className="text-[11px] text-ink-500 ml-2">
          Accept keeps the changes. Reject restores the pre-loop state. Clear dismisses the changelog/diff but keeps the design.
        </span>
        {rejectWarning && (
          <div className="w-full mt-2 text-[11px] text-err bg-err/[0.06] border border-err/30 rounded px-2 py-1.5">
            {rejectWarning}
          </div>
        )}
      </footer>
    </section>
  );
}

function ChangeList({ sheet }:
  { sheet: { added: Record<string, unknown>; removed: Record<string, unknown>; changed: Record<string, { from_value: string; to_value: string }> } }) {
  const totalChanges =
    Object.keys(sheet.added).length +
    Object.keys(sheet.removed).length +
    Object.keys(sheet.changed).length;
  if (totalChanges === 0) {
    return (
      <div className="px-4 py-2 text-[11.5px] text-ink-500">
        No changes on this sheet.
      </div>
    );
  }
  return (
    <details className="px-4 py-2 text-[11.5px]" open>
      <summary className="cursor-pointer text-ink-700 hover:text-ink-900">
        Change list ({totalChanges})
      </summary>
      <ul className="mt-1.5 ml-3 space-y-0.5">
        {Object.entries(sheet.added).map(([rd]) => (
          <li key={"a" + rd}><span className="text-ok">+</span> {rd} added</li>
        ))}
        {Object.entries(sheet.removed).map(([rd]) => (
          <li key={"r" + rd}><span className="text-err">-</span> {rd} removed</li>
        ))}
        {Object.entries(sheet.changed).map(([rd, c]) => (
          <li key={"c" + rd}><span className="text-warn">~</span> {rd}: {c.from_value} → {c.to_value}</li>
        ))}
      </ul>
    </details>
  );
}
