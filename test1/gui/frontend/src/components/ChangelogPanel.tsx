import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { I } from "./Icon";
import type { ChangelogItem } from "../types";

// Above this many queued items, the list collapses behind a dropdown toggle
// (like the linter checklist) so it doesn't dominate the panel.
const COLLAPSE_THRESHOLD = 3;

interface Props {
  /** "rail" = compact, bordered-bottom (Agent rail). "tab" = standalone card
   *  for the Generator tab. Behavior is identical; only chrome differs. */
  variant?: "rail" | "tab";
  /** Bumped by the parent to force a refresh (e.g. right after a generate run
   *  consumes the queue, so the list updates immediately). */
  refreshKey?: number;
  /** Notified whenever the queued-item count changes (lets the Generator tab
   *  keep its own counter in sync without a second poll). */
  onCountChange?: (n: number) => void;
}

/** Add / view / delete / clear the changelog. Single source of truth shared by
 *  the Agent rail and the Schematic Generator tab so the two never drift. */
export function ChangelogPanel({ variant = "rail", refreshKey, onCountChange }: Props) {
  const [items, setItems] = useState<ChangelogItem[]>([]);
  const [adding, setAdding] = useState("");
  const [expanded, setExpanded] = useState(false);
  // In the Generator tab the whole section is collapsible like the linter
  // checklist (default open); the rail keeps the inline ">3 → show all" behavior.
  const [sectionOpen, setSectionOpen] = useState(true);
  const isTab = variant === "tab";

  const collapsible = items.length > COLLAPSE_THRESHOLD;
  const showList = !collapsible || expanded;

  const refresh = useCallback(async () => {
    try {
      const r = await api.changelog();
      setItems(r.items);
      onCountChange?.(r.items.length);
    } catch {
      // ignore
    }
  }, [onCountChange]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 2500);
    return () => clearInterval(id);
  }, [refresh, refreshKey]);

  const add = async () => {
    const s = adding.trim();
    if (!s) return;
    await api.changelogAdd(s);
    setAdding("");
    refresh();
  };

  // Shared list body + add-row (identical in both variants).
  const sourceTone = (src: string) =>
    src === "sim"
      ? "bg-ok/10 text-ok"
      : src === "agent"
      ? "bg-ink-900/[0.06] text-ink-600"
      : "bg-warn/10 text-warn"; // user
  const body = (
    <>
      {!showList ? (
        <div className="px-3 pb-2 text-xs text-ink-500 italic">
          {items.length} queued change{items.length === 1 ? "" : "s"} — “show all” to view.
        </div>
      ) : (
        <div className="px-3 pb-2 max-h-[200px] overflow-auto thin-scroll">
          {items.length === 0 ? (
            <div className="text-xs text-ink-500 italic">
              No queued changes. Ask the agent for edits or add a bullet below.
            </div>
          ) : (
            <ul className="space-y-1">
              {items.map((it) => (
                <li
                  key={it.id}
                  className="flex items-start gap-2 text-[12.5px] group rounded px-1.5 py-1 hover:bg-rail"
                >
                  <span
                    className={
                      "shrink-0 mt-[1px] px-1.5 py-[1px] rounded text-[9.5px] font-semibold uppercase tracking-wide " +
                      sourceTone(it.source)
                    }
                  >
                    {it.source}
                  </span>
                  <span className="flex-1 text-ink-800 leading-snug">{it.summary}</span>
                  <button
                    onClick={async () => {
                      await api.changelogDelete(it.id);
                      refresh();
                    }}
                    className="opacity-0 group-hover:opacity-100 text-ink-500 hover:text-err shrink-0 mt-0.5"
                    title="Remove"
                  >
                    <I.X size={12} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="px-2 pb-2 flex gap-1">
        <input
          value={adding}
          onChange={(e) => setAdding(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") add();
          }}
          placeholder="Add a manual bullet…"
          className="flex-1 text-[12px] border border-edge rounded-md px-2 py-1 focus:outline-none focus:border-ink-300"
        />
        <button
          onClick={add}
          disabled={!adding.trim()}
          className="h-7 px-2 text-[11px] rounded-md border border-edge text-ink-700 hover:border-ink-300 disabled:opacity-50"
        >
          add
        </button>
      </div>
    </>
  );

  // --- Generator tab: render as a SubSection-style block matching the linter
  //     checklist (caret toggle + semibold title + hint), borderless section.
  if (isTab) {
    return (
      <section className="mt-6">
        <div className="flex items-baseline gap-3 mb-2">
          <button
            type="button"
            onClick={() => setSectionOpen((o) => !o)}
            className="flex items-baseline gap-3 hover:opacity-80 transition-opacity"
          >
            <I.Caret
              size={14}
              className={"transition-transform text-ink-500 " + (sectionOpen ? "rotate-180" : "")}
            />
            <h3 className="text-sm font-semibold text-ink-900">Changelog</h3>
            <span className="text-[11px] text-ink-500">
              {items.length} queued — applied on Generate
            </span>
          </button>
          {sectionOpen && items.length > 0 && (
            <button
              onClick={async () => {
                await api.changelogClear();
                refresh();
              }}
              className="ml-auto text-[11px] text-ink-500 hover:text-ink-900"
            >
              clear
            </button>
          )}
        </div>
        {sectionOpen && (
          <div className="border border-edge rounded-md bg-white">{body}</div>
        )}
      </section>
    );
  }

  // --- Agent rail: compact bordered-bottom block (unchanged idiom).
  return (
    <div className="border-b border-edge">
      <div className="px-3 py-2 text-[11px] uppercase tracking-wide text-ink-500 flex items-center">
        Changelog
        <span className="ml-1.5 text-[11px] text-ink-500 normal-case tracking-normal">
          ({items.length} queued)
        </span>
        {collapsible && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="ml-2 text-[11px] text-ink-500 hover:text-ink-900 inline-flex items-center gap-1 normal-case tracking-normal"
          >
            {expanded ? "hide" : "show all"}
            <span className={"transition-transform inline-block " + (expanded ? "rotate-180" : "rotate-0")}>
              <I.Caret size={11} />
            </span>
          </button>
        )}
        {items.length > 0 && (
          <button
            onClick={async () => {
              await api.changelogClear();
              refresh();
            }}
            className="ml-auto text-[11px] text-ink-500 hover:text-ink-900"
          >
            clear
          </button>
        )}
      </div>
      {body}
    </div>
  );
}
