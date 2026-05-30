import { useEffect, useState } from "react";
import { api, subscribeLoop } from "../api";
import { I } from "./Icon";
import { LiveConsole } from "./LiveConsole";
import { PipelineStrip, type Step, type StepState } from "./PipelineStrip";
import type { LoopEvent, LoopSummary, LoopRound, LoopAction } from "../types";

interface Props {
  loopId: string | null;          // null when no loop running/completed
  onLoopCompleted: (status: string) => void;
  setHealth: (h: { text: string; tone: "ok" | "warn" | "err" | "neutral" } | undefined) => void;
  // expose summary up for DiffAndAccept gating (Phase 4D)
  onSummary?: (s: LoopSummary | null) => void;
}

const MAX_ROUNDS = 10;

// ---- Pipeline-stage model ------------------------------------------------
// Mirrors the Simulation tab's WorkflowSteps. A loop round walks:
//   Plan → Apply → Sim → Build → Re-eval
// The orchestrator emits SSE events; we map them to a `phase` here. Stages
// not exercised in a round (e.g. no sim action this round) stay "skipped".

type PhaseId = "idle" | "plan" | "apply" | "sim" | "missing_part" | "lint_fix" | "build" | "re_eval" | "done";

// Compute the step row from the current phase + the last round's seen kinds
// (so a round that skipped sim shows "Sim" gray-skipped rather than pending).
// StepIcon, Step, StepState, ACTOR_TONE all moved to PipelineStrip.tsx.
function pipelineSteps(phase: PhaseId, currentRound: LoopRound | undefined, terminal: boolean): Step[] {
  const seenKinds = new Set<string>((currentRound?.actions ?? []).map(a => a.kind));
  const everSim = seenKinds.has("sim");
  const everMissing = seenKinds.has("missing_part");
  const everLintFix = seenKinds.has("lint_fix");

  const order: string[] = ["plan", "apply", "sim", "missing_part", "lint_fix", "build", "re_eval"];
  const phaseIdx = order.indexOf(phase);

  const steps: Step[] = [
    { id: "plan",         label: "Plan",     actor: "py",    state: "pending" },
    { id: "apply",        label: "Apply",    actor: "agent", state: "pending" },
    { id: "sim",          label: "Sim",      actor: "ngspice", state: everSim ? "pending" : "skipped" },
    { id: "missing_part", label: "Missing",  actor: "agent", state: everMissing ? "pending" : "skipped" },
    { id: "lint_fix",     label: "Lint fix", actor: "agent", state: everLintFix ? "pending" : "skipped" },
    { id: "build",        label: "Build",    actor: "build", state: "pending" },
    { id: "re_eval",      label: "Re-eval",  actor: "py",    state: "pending" },
  ];

  if (terminal) {
    // After loop done: everything visited in the last round is "done".
    for (const s of steps) {
      if (s.state === "skipped") continue;
      s.state = "done";
    }
    return steps;
  }

  for (let i = 0; i < steps.length; i++) {
    if (steps[i].state === "skipped") continue;
    const ordIdx = order.indexOf(steps[i].id);
    if (ordIdx < phaseIdx) steps[i].state = "done";
    else if (ordIdx === phaseIdx) steps[i].state = "active";
    else steps[i].state = "pending";
  }
  return steps;
}

function inferPhaseFromEvent(ev: LoopEvent, prev: PhaseId): PhaseId {
  switch (ev.event) {
    case "loop_start":  return "plan";
    case "round_start": return "plan";
    case "action_start":
      switch (ev.data.kind) {
        case "apply":         return "apply";
        case "sim":           return "sim";
        case "missing_part":  return "missing_part";
        case "lint_fix":      return "lint_fix";
        default:              return prev;
      }
    case "action_end":  return prev;   // build_start follows
    case "build_start": return "build";
    case "build_end":   return "re_eval";
    case "round_done":  return "plan";  // next round begins; or terminal soon
    case "done":        return "done";
    default:            return prev;
  }
}

// ---- Component ----------------------------------------------------------

export function IterationSection({ loopId, onLoopCompleted, setHealth, onSummary }: Props) {
  const [summary, setSummary] = useState<LoopSummary | null>(null);
  const [phase, setPhase] = useState<PhaseId>("idle");
  const [activeAgentId, setActiveAgentId] = useState<string | null>(null);
  const [pinnedAgentId, setPinnedAgentId] = useState<string | null>(null);

  // Subscribe to the loop stream
  useEffect(() => {
    if (!loopId) { setPhase("idle"); return; }
    let lastFetch = 0;

    const refresh = async () => {
      try {
        const s = await api.loopGet(loopId);
        setSummary(s);
        onSummary?.(s);
        const tone: "ok" | "warn" | "err" | "neutral" =
          s.status === "all_clear" ? "ok" :
          s.status === "plateau" || s.status === "max_rounds" ? "warn" :
          s.status === "running" ? "neutral" :
          s.status === "cancelled" ? "neutral" : "err";
        setHealth({ text: `loop ${s.status}`, tone });
        if (s.status !== "running") setPhase("done");
      } catch { /* ignore */ }
    };

    void refresh();

    const unsub = subscribeLoop(loopId, async (ev: LoopEvent) => {
      setPhase((p) => inferPhaseFromEvent(ev, p));
      if (Date.now() - lastFetch > 250) {
        lastFetch = Date.now();
        await refresh();
      }
      if (ev.event === "action_start" && ev.data.kind && (ev.data as { agent_run_id?: string }).agent_run_id) {
        setActiveAgentId((ev.data as { agent_run_id?: string }).agent_run_id ?? null);
      }
      if (ev.event === "action_end") {
        setActiveAgentId(null);
      }
    }, (status) => {
      void refresh();
      setPhase("done");
      onLoopCompleted(status);
    });

    return () => { unsub(); };
  }, [loopId, onLoopCompleted, setHealth, onSummary]);

  if (!loopId) return null;

  const isRunning = summary?.status === "running";
  const terminal = !!summary && !isRunning;
  const currentRound = summary?.rounds[summary.rounds.length - 1];
  const round = summary?.round ?? 0;
  const steps = pipelineSteps(phase, currentRound, terminal);

  return (
    <section className="mt-5 rounded-md border border-edge bg-white">
      <header className="px-4 py-2.5 flex items-center gap-2 border-b border-edge">
        <I.Play size={14} />
        <span className="text-sm font-semibold text-ink-900">Iteration</span>
        <span className="text-[11px] text-ink-500">
          loop {loopId.slice(0, 8)}
          {summary && ` · ${summary.status}`}
        </span>
        {isRunning && (
          <button
            onClick={() => api.loopCancel(loopId)}
            className="ml-auto h-7 px-2.5 text-[11.5px] rounded border border-edge text-ink-700 hover:border-err hover:text-err"
          >
            ⊗ Cancel
          </button>
        )}
      </header>

      {/* Pipeline-stage strip — mirrors the Simulation tab's WorkflowSteps */}
      <div className="px-4 pt-3 pb-2">
        <PipelineStrip
          steps={steps}
          badge={round > 0 ? (
            <span
              className={
                "shrink-0 inline-flex items-center gap-1 text-[9.5px] font-mono px-1.5 py-0.5 rounded-full border " +
                (isRunning
                  ? "border-violet-300 bg-violet-100 text-violet-700"
                  : "border-edge bg-ink-100 text-ink-500")
              }
              title={`round ${round} of ${MAX_ROUNDS}`}
            >
              <I.Refresh size={9} className={isRunning ? "animate-spin" : ""} />
              round {round}/{MAX_ROUNDS}
            </span>
          ) : null}
        />
      </div>

      {summary?.status === "plateau" && (
        <div className="px-4 py-2 text-[12px] bg-warn/[0.06] text-ink-700 border-y border-edge">
          <strong>⚠ Loop halted</strong> — no progress for 2 consecutive rounds.{" "}
          {summary.findings_current} findings unresolved.
        </div>
      )}
      {summary?.status === "all_clear" && (
        <div className="px-4 py-2 text-[12px] bg-ok/[0.06] text-ok border-y border-edge">
          ✓ All findings resolved in {summary.rounds.length} rounds.
        </div>
      )}
      {summary?.error && (
        <div className="px-4 py-2 text-[12px] text-err bg-err/[0.06] border-y border-edge">
          error: {summary.error}
        </div>
      )}

      {/* Live console — always present once a loop has started. Shows the
          active or pinned sub-agent's stream via the shared LiveConsole. */}
      <LiveConsole
        agentRunId={pinnedAgentId ?? activeAgentId}
        idlePlaceholder={isRunning ? "waiting for agent action…" : "no active agent"}
        headerRight={pinnedAgentId ? (
          <button onClick={() => setPinnedAgentId(null)}
            className="ml-2 text-ink-500 hover:text-ink-900 underline">unpin</button>
        ) : undefined}
      />

      {/* Per-round history — collapsed by default once finished */}
      {summary && summary.rounds.length > 0 && (
        <details className="border-t border-edge" open={isRunning}>
          <summary className="px-4 py-2 text-[11.5px] text-ink-700 cursor-pointer hover:text-ink-900">
            Round history ({summary.rounds.length})
          </summary>
          <div className="px-4 py-3 space-y-2">
            {summary.rounds.map((r) => (
              <RoundCard key={r.n} r={r}
                activeAgentId={pinnedAgentId ?? activeAgentId}
                onPin={setPinnedAgentId} />
            ))}
          </div>
        </details>
      )}
    </section>
  );
}

function RoundCard({ r, activeAgentId, onPin }:
  { r: LoopRound; activeAgentId: string | null; onPin: (id: string) => void }) {
  const delta = r.findings_before - r.findings_after;
  const deltaTxt = delta > 0 ? `-${delta} net` : delta < 0 ? `+${-delta} net` : "0 net";
  return (
    <div className="rounded border border-edge px-3 py-2">
      <div className="flex items-baseline gap-2 text-[12px]">
        <strong className="text-ink-900">Round {r.n}</strong>
        <span className="text-ink-500">
          {deltaTxt} · {r.findings_before}→{r.findings_after}
        </span>
        {!r.finished_at && <span className="text-ink-500 italic">(running)</span>}
      </div>
      <div className="mt-1.5 ml-2 space-y-1">
        {r.actions.map((a, i) => (
          <ActionRow key={i} a={a} onPin={onPin} active={a.agent_run_id === activeAgentId} />
        ))}
        {r.build_status && (
          <div className="text-[11.5px] text-ink-700">
            ▾ build · {r.build_status}
            {r.lint_summary && ` · lint ${r.lint_summary.ERROR}/${r.lint_summary.WARNING}/${r.lint_summary.INFO}`}
          </div>
        )}
        {r.sim_results.length > 0 && (
          <div className="text-[11.5px] text-ink-700">
            ▾ sim · {r.sim_results.filter(s => s.ok).length}/{r.sim_results.length} ok
          </div>
        )}
      </div>
    </div>
  );
}

function ActionRow({ a, onPin, active }:
  { a: LoopAction; onPin: (id: string) => void; active: boolean }) {
  const dot = a.status === "ok" ? "●" : a.status === "fail" ? "✗" :
              a.status === "cancelled" ? "⊗" : "◐";
  const tone = a.status === "ok" ? "text-ok" : a.status === "fail" ? "text-err" :
               a.status === "cancelled" ? "text-ink-500" : "text-ink-700";
  return (
    <div className={"text-[11.5px] flex items-center gap-1.5 " + (active ? "bg-rail/30 rounded px-1" : "")}>
      <span className={tone}>{dot}</span>
      <span className="font-mono text-ink-500">{a.kind}</span>
      <span className="text-ink-700">· {a.summary}</span>
      {a.agent_run_id && (
        <button onClick={() => onPin(a.agent_run_id!)}
          className="ml-auto text-[10px] text-ink-500 hover:text-ink-900">
          pin
        </button>
      )}
    </div>
  );
}
