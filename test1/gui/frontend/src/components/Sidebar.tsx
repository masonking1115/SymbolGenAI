import { useEffect, useMemo, useState } from "react";
import { I } from "./Icon";
import type { SimBlock, SimGroup, TabKey } from "../types";

interface Props {
  active: TabKey;
  onChange: (k: TabKey) => void;
  projectLabel: string;
  /** Test-block catalog for the Simulation dropdown. */
  simBlocks: SimBlock[];
  /** Functional groups (ordered labels) the blocks are organized under. */
  simGroups: SimGroup[];
  selectedSimBlock: string;
  onSelectSimBlock: (id: string) => void;
}

const ITEMS: { key: TabKey; label: string; icon: (p?: { size?: number }) => JSX.Element }[] = [
  { key: "resources", label: "Design Resources", icon: I.Resources },
  { key: "library", label: "Library", icon: I.Library },
  { key: "generator", label: "Schematic Generator", icon: I.Schematic },
  { key: "simulation", label: "Simulation", icon: I.Wave },
  { key: "review", label: "Design Review", icon: I.Review },
];

const STATUS_DOT: Record<string, string> = {
  implemented: "bg-ok",
  planned: "bg-warn",
  not_simulatable: "bg-ink-300",
};

export function Sidebar({
  active,
  onChange,
  projectLabel,
  simBlocks,
  simGroups,
  selectedSimBlock,
  onSelectSimBlock,
}: Props) {
  // Auto-expand the Simulation test-block list when the tab is active.
  const [simOpen, setSimOpen] = useState(active === "simulation");
  useEffect(() => {
    if (active === "simulation") setSimOpen(true);
  }, [active]);

  // Bucket the blocks into their functional groups, in the backend's group
  // order. A block whose group isn't in the list (or when no groups loaded yet)
  // falls into a trailing "other" bucket so nothing is ever hidden.
  const grouped = useMemo(() => {
    const order = simGroups.length ? simGroups : [{ id: "other", label: "Other", blurb: "" }];
    const byId = new Map(order.map((g) => [g.id, g]));
    const buckets = new Map<string, SimBlock[]>();
    for (const b of simBlocks) {
      const gid = byId.has(b.group) ? b.group : "other";
      (buckets.get(gid) ?? buckets.set(gid, []).get(gid)!).push(b);
    }
    // emit in group order; include a synthetic "other" at the end if it has blocks
    const out = order
      .filter((g) => buckets.has(g.id))
      .map((g) => ({ group: g, blocks: buckets.get(g.id)! }));
    if (buckets.has("other") && !byId.has("other"))
      out.push({ group: { id: "other", label: "Other", blurb: "" }, blocks: buckets.get("other")! });
    return out;
  }, [simBlocks, simGroups]);

  return (
    <aside className="h-full w-full bg-rail border-r border-edge flex flex-col">
      <div className="h-12 px-3 flex items-center gap-2 border-b border-edge">
        <button className="flex items-center gap-2 hover:bg-white/60 rounded px-2 py-1 -ml-1 text-ink-900">
          <img src="/logo.png" alt="logo" className="w-5 h-5 object-contain shrink-0" />
          <span className="text-sm font-medium truncate max-w-[140px]">
            {projectLabel}
          </span>
          <I.Caret size={14} />
        </button>
        <div className="ml-auto flex items-center text-ink-500">
          <button className="p-1 hover:text-ink-900">
            <I.Sidebar />
          </button>
        </div>
      </div>

      <nav className="px-2 py-2 space-y-1 flex-1 overflow-auto thin-scroll">
        {ITEMS.map((it) => {
          const isActive = it.key === active;
          const Icon = it.icon;
          const isSim = it.key === "simulation";
          return (
            <div key={it.key}>
              <button
                onClick={() => {
                  onChange(it.key);
                  if (isSim) setSimOpen(true);
                }}
                className={
                  "w-full flex items-center gap-2 px-2 py-2 rounded-md text-sm transition " +
                  (isActive
                    ? "bg-white text-ink-900 shadow-[0_0_0_1px_rgb(230,232,236)]"
                    : "text-ink-700 hover:bg-white/70")
                }
              >
                <span className={isActive ? "text-ink-900" : "text-ink-500"}>
                  <Icon />
                </span>
                <span>{it.label}</span>
                {isSim && simBlocks.length > 0 && (
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={(e) => {
                      e.stopPropagation();
                      setSimOpen((v) => !v);
                    }}
                    className="ml-auto text-ink-500 hover:text-ink-900 p-0.5 -mr-0.5"
                  >
                    <I.Caret size={13} className={simOpen ? "" : "-rotate-90 transition-transform"} />
                  </span>
                )}
              </button>

              {isSim && simOpen && simBlocks.length > 0 && (
                <div className="mt-0.5 ml-3 pl-2 border-l border-edge space-y-1.5">
                  {grouped.map(({ group, blocks }) => (
                    <SimGroupSection
                      key={group.id}
                      group={group}
                      blocks={blocks}
                      active={active === "simulation"}
                      selectedSimBlock={selectedSimBlock}
                      onSelectSimBlock={onSelectSimBlock}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      <div className="border-t border-edge px-3 py-2 text-[11px] text-ink-500">
        test1 · Bobcat carrier
      </div>
    </aside>
  );
}

// One functional group in the Simulation sidebar: a small header (label + block
// count) over its blocks. Collapsible; auto-opens when it holds the selected
// block, and the "not_simulatable" group starts collapsed (least-actionable).
function SimGroupSection({
  group,
  blocks,
  active,
  selectedSimBlock,
  onSelectSimBlock,
}: {
  group: SimGroup;
  blocks: SimBlock[];
  active: boolean;
  selectedSimBlock: string;
  onSelectSimBlock: (id: string) => void;
}) {
  const hasSelected = blocks.some((b) => b.id === selectedSimBlock);
  const [open, setOpen] = useState(group.id !== "not_simulatable");
  // If the selection moves into this (collapsed) group, reveal it.
  useEffect(() => {
    if (active && hasSelected) setOpen(true);
  }, [active, hasSelected]);

  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        title={group.blurb}
        className="w-full flex items-center gap-1 px-1 py-0.5 text-[10px] uppercase tracking-wide text-ink-400 hover:text-ink-700"
      >
        <I.Caret size={10} className={open ? "" : "-rotate-90 transition-transform"} />
        <span className="truncate">{group.label}</span>
        <span className="ml-auto text-ink-300 normal-case">{blocks.length}</span>
      </button>
      {open && (
        <div className="space-y-0.5 mt-0.5">
          {blocks.map((b) => {
            const sel = active && b.id === selectedSimBlock;
            return (
              <button
                key={b.id}
                onClick={() => onSelectSimBlock(b.id)}
                title={b.title}
                className={
                  "w-full flex items-center gap-2 pl-3 pr-2 py-1.5 rounded-md text-[13px] transition " +
                  (sel
                    ? "bg-white text-ink-900 shadow-[0_0_0_1px_rgb(230,232,236)]"
                    : "text-ink-700 hover:bg-white/70")
                }
              >
                <span
                  className={
                    "w-1.5 h-1.5 rounded-full shrink-0 " +
                    (STATUS_DOT[b.status] ?? STATUS_DOT.not_simulatable)
                  }
                  title={b.status}
                />
                <span className="truncate">{b.title}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
