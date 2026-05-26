import { I } from "./Icon";
import type { TabKey } from "../types";

interface Props {
  active: TabKey;
  onChange: (k: TabKey) => void;
  projectLabel: string;
}

const ITEMS: { key: TabKey; label: string; icon: (p?: { size?: number }) => JSX.Element }[] = [
  { key: "library", label: "Library", icon: I.Library },
  { key: "generator", label: "Schematic Generator", icon: I.Schematic },
  { key: "review", label: "Design Review", icon: I.Review },
];

export function Sidebar({ active, onChange, projectLabel }: Props) {
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

      <nav className="px-2 py-2 space-y-1 flex-1">
        {ITEMS.map((it) => {
          const isActive = it.key === active;
          const Icon = it.icon;
          return (
            <button
              key={it.key}
              onClick={() => onChange(it.key)}
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
            </button>
          );
        })}
      </nav>

      <div className="border-t border-edge px-3 py-2 text-[11px] text-ink-500">
        test1 · Bobcat carrier
      </div>
    </aside>
  );
}
