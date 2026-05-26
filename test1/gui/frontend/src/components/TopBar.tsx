import { I } from "./Icon";

interface Props {
  title: string;
  /** Right-hand status chip text (e.g. "0E · 0W · 0I"). */
  health?: { text: string; tone: "ok" | "warn" | "err" | "neutral" };
  onTogglePng: () => void;
  pngOpen: boolean;
}

const TONE: Record<string, string> = {
  ok: "bg-ok/10 text-ok border-ok/20",
  warn: "bg-warn/10 text-warn border-warn/20",
  err: "bg-err/10 text-err border-err/20",
  neutral: "bg-edge text-ink-700 border-edge",
};

export function TopBar({ title, health, onTogglePng, pngOpen }: Props) {
  return (
    <div className="h-12 border-b border-edge flex items-center gap-3 px-4 bg-white">
      <h1 className="text-sm font-medium text-ink-900">{title}</h1>
      {health && (
        <span
          className={
            "text-xs font-medium px-2 py-0.5 rounded-full border " +
            TONE[health.tone]
          }
        >
          {health.text}
        </span>
      )}

      <div className="ml-auto flex items-center gap-2">
        <div className="relative">
          <span className="absolute left-2 top-1/2 -translate-y-1/2 text-ink-500">
            <I.Search size={14} />
          </span>
          <input
            placeholder="Search..."
            className="pl-7 pr-3 py-1.5 text-sm bg-rail border border-edge rounded-md w-[260px] focus:outline-none focus:border-ink-300"
          />
        </div>
        <button
          onClick={onTogglePng}
          className={
            "h-8 px-3 text-xs font-medium rounded-md border transition " +
            (pngOpen
              ? "bg-ink-900 text-white border-ink-900"
              : "bg-white text-ink-700 border-edge hover:border-ink-300")
          }
          title="Toggle schematic PNG split view"
        >
          {pngOpen ? "Hide PNG" : "Show PNG"}
        </button>
        <button className="p-1.5 rounded hover:bg-rail text-ink-500" title="History">
          <I.History />
        </button>
        <button className="p-1.5 rounded hover:bg-rail text-ink-500" title="Notifications">
          <I.Bell />
        </button>
      </div>
    </div>
  );
}
