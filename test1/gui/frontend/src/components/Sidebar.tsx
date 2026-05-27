import { useEffect, useState } from "react";
import { I } from "./Icon";
import type { SimBlock, TabKey } from "../types";

interface Props {
  active: TabKey;
  onChange: (k: TabKey) => void;
  projectLabel: string;
  /** Test-block catalog for the Simulation dropdown. */
  simBlocks: SimBlock[];
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
  selectedSimBlock,
  onSelectSimBlock,
}: Props) {
  // Auto-expand the Simulation test-block list when the tab is active.
  const [simOpen, setSimOpen] = useState(active === "simulation");
  useEffect(() => {
    if (active === "simulation") setSimOpen(true);
  }, [active]);

  return (
    <aside className="h-full w-full bg-rail border-r border-edge flex flex-col">
      <div className="h-12 px-3 flex items-center gap-2 border-b border-edge">
        <button className="flex items-center gap-2 hover:bg-white/60 rounded px-2 py-1 -ml-1 text-ink-900">
          <I.Folder />
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
                <div className="mt-0.5 ml-3 pl-2 border-l border-edge space-y-0.5">
                  {simBlocks.map((b) => {
                    const sel = active === "simulation" && b.id === selectedSimBlock;
                    return (
                      <button
                        key={b.id}
                        onClick={() => onSelectSimBlock(b.id)}
                        title={b.title}
                        className={
                          "w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-[13px] transition " +
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
        })}
      </nav>

      <div className="border-t border-edge px-3 py-2 text-[11px] text-ink-500">
        test1 · Bobcat carrier
      </div>
    </aside>
  );
}
