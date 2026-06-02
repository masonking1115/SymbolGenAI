// Shared status-card group used by BOTH the Schematic Generator (Phase 2) and the
// Design Review (Phase 3). The two tabs show identical-looking ERRORS/WARNINGS/
// INFOS cards but measure DIFFERENT things — geometry of the drawn schematic
// (layout lint) vs correctness of the design (review findings). Users mistook one
// for the other when the counts differed, so every group now carries a TITLE +
// a one-line caption of exactly what it measures. Same chrome, clearly labeled.
import React from "react";
import { I } from "./Icon";

export type StatTone = "ok" | "warn" | "err" | "neutral";

/** A titled wrapper around a row of StatCards. The header (title + caption) is the
 *  differentiator: it tells the user WHAT this group measures so a count here is
 *  never confused with the other tab's count. */
export function StatusGroup({
  title,
  caption,
  children,
}: {
  title: string;
  caption: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className="rounded-lg border border-edge bg-white/40 p-3"
      aria-label={title}
    >
      <div className="mb-2">
        <div className="text-[12px] font-semibold text-ink-800 uppercase tracking-wide">
          {title}
        </div>
        <div className="text-[11px] text-ink-500 leading-snug">{caption}</div>
      </div>
      {children}
    </section>
  );
}

/** Clickable count card (ERRORs/WARNINGs/INFOs). `onClick`/`active` make it an
 *  expander toggle; omit `onClick` for a static card. Shared so the Generator and
 *  Review render the SAME card, and the caret affordance is consistent. */
export function StatCard({
  label,
  value,
  tone,
  onClick,
  active,
}: {
  label: string;
  value: number;
  tone: StatTone;
  onClick?: () => void;
  active?: boolean;
}) {
  const ring =
    tone === "ok"
      ? "border-ok/30 bg-ok/[0.05]"
      : tone === "warn"
      ? "border-warn/30 bg-warn/[0.05]"
      : tone === "err"
      ? "border-err/30 bg-err/[0.05]"
      : "border-edge bg-rail";
  const num =
    tone === "ok"
      ? "text-ok"
      : tone === "warn"
      ? "text-warn"
      : tone === "err"
      ? "text-err"
      : "text-ink-900";
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      disabled={!onClick}
      className={
        "text-left rounded-md border px-3 py-2 transition-shadow w-full " +
        ring +
        (onClick ? " cursor-pointer hover:shadow-sm" : " cursor-default") +
        (active ? " ring-2 ring-ink-300" : "")
      }
    >
      <div className="text-[11px] uppercase tracking-wide text-ink-500 flex items-center justify-between">
        <span>{label}</span>
        {onClick && (
          <I.Caret
            size={12}
            className={"transition-transform " + (active ? "rotate-180" : "opacity-40")}
          />
        )}
      </div>
      <div className={"text-2xl font-semibold mt-0.5 " + num}>{value}</div>
    </button>
  );
}
