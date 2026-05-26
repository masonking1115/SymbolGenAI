import { useEffect, useRef } from "react";

interface Props {
  lines: string[];
  status: "idle" | "running" | "ok" | "fail";
}

const STATUS_LABEL: Record<string, string> = {
  idle: "idle",
  running: "running…",
  ok: "ok",
  fail: "failed",
};

const STATUS_TONE: Record<string, string> = {
  idle: "text-ink-500",
  running: "text-warn",
  ok: "text-ok",
  fail: "text-err",
};

export function Console({ lines, status }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lines.length]);
  return (
    <div className="border border-edge rounded-md bg-[#0F1115] text-[#D6DAE0] flex flex-col overflow-hidden">
      <div className="h-7 px-3 flex items-center gap-2 text-[11px] text-ink-300 bg-[#181B22] border-b border-black/30">
        <span>console</span>
        <span className={STATUS_TONE[status] + " ml-auto"}>{STATUS_LABEL[status]}</span>
      </div>
      <div
        ref={ref}
        className="thin-scroll flex-1 overflow-auto px-3 py-2 font-mono text-[11.5px] leading-[1.55]"
      >
        {lines.length === 0 ? (
          <div className="text-ink-500 italic">No output yet.</div>
        ) : (
          lines.map((l, i) => <div key={i} className="whitespace-pre">{l}</div>)
        )}
      </div>
    </div>
  );
}
