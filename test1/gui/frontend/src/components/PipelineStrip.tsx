// Shared horizontal pipeline-stage strip used by the closed-loop Iteration
// section, the rule-generation pipeline (Review tab), and the Simulation tab's
// per-block workflow strip.
//
// Each step is one circle + label + actor badge; steps are connected by a
// thin horizontal rule. State is one of: pending | active | done | skipped |
// fail (renders accordingly).

import { Fragment } from "react";
import { I } from "./Icon";

export type StepState = "pending" | "active" | "done" | "skipped" | "fail";

export interface Step {
  id: string;
  label: string;
  actor: string;        // "py" | "agent" | "ngspice" | "build" | ...
  state: StepState;
  hint?: string;
}

export function StepIcon({ state }: { state: StepState }) {
  const base = "w-5 h-5 rounded-full grid place-items-center shrink-0";
  if (state === "done")
    return <span className={base + " bg-ok/15 text-ok"}><I.Check size={12} /></span>;
  if (state === "fail")
    return <span className={base + " bg-err/15 text-err"}><I.X size={12} /></span>;
  if (state === "skipped")
    return <span className={base + " border border-edge text-ink-300"}>·</span>;
  if (state === "active")
    return (
      <span className={base + " bg-ink-100"}>
        <span className="w-3 h-3 rounded-full border-2 border-ink-300 border-t-ink-700 animate-spin" />
      </span>
    );
  return <span className={base + " border border-edge text-ink-300"}><I.Dot size={10} /></span>;
}

// Tint the actor badge when its step is the active one (matches IterationSection).
const ACTOR_TONE: Record<string, string> = {
  py:      "bg-ink-100 text-ink-500",
  agent:   "bg-violet-100 text-violet-700",
  ngspice: "bg-amber-100 text-amber-700",
  build:   "bg-blue-100 text-blue-700",
};

interface Props {
  steps: Step[];
  // Optional left-side badge (e.g. "round 3/10"). Rendered before the first
  // step. Pass null for none.
  badge?: React.ReactNode;
}

export function PipelineStrip({ steps, badge = null }: Props) {
  return (
    <div className="flex items-center gap-1.5">
      {badge}
      {steps.map((s, i) => (
        <Fragment key={s.id}>
          <div className="flex items-center gap-1.5">
            <StepIcon state={s.state} />
            <div className="leading-tight">
              <div className="text-[11px] text-ink-700 whitespace-nowrap flex items-center gap-1">
                {s.label}
                <span className={
                  "text-[8.5px] px-1 py-px rounded font-mono " +
                  (s.state === "active"
                    ? ACTOR_TONE[s.actor] ?? ACTOR_TONE.py
                    : "bg-ink-100 text-ink-400")
                }>
                  {s.actor}
                </span>
              </div>
              {s.hint && (
                <div className="text-[10px] text-ink-500 whitespace-nowrap">{s.hint}</div>
              )}
            </div>
          </div>
          {i < steps.length - 1 && <div className="flex-1 h-px bg-edge min-w-[10px]" />}
        </Fragment>
      ))}
    </div>
  );
}
