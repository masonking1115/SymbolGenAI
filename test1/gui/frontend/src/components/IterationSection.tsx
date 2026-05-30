import { useEffect, useRef, useState } from "react";
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

// Render a loop SSE event as a readable console line (null = don't log it).
function loopEventLine(ev: LoopEvent): string | null {
  switch (ev.event) {
    case "eval_start":
      return `▶ evaluating rules (${ev.data.phase})…`;
    case "eval_progress": {
      const d = ev.data;
      const mark = d.result === "fail" ? "✗ FAIL" : "✓ pass";
      const tag = d.evaluation === "semantic" ? " [semantic]" : "";
      return `  [${d.i}/${d.total}] ${d.id}${tag} — ${mark}`;
    }
    case "eval_done":
      return `  → ${ev.data.findings} finding(s)`;
    case "loop_start":
      return `loop start · ${ev.data.findings} finding(s) to resolve`;
    case "round_start":
      return `── round ${ev.data.round} · ${ev.data.findings} finding(s) ──`;
    case "action_start":
      return `▶ ${ev.data.kind} [${(ev.data.targets || []).join(", ")}]`;
    case "action_end":
      return `  ${ev.data.status === "ok" ? "✓" : "✗"} ${ev.data.kind} — ${ev.data.summary || ev.data.status}`;
    case "build_start":
      return `▶ rebuild…`;
    case "build_end": {
      const l = ev.data.lint;
      return `  build ${ev.data.status}${l ? ` · lint ${l.ERROR}/${l.WARNING}/${l.INFO}` : ""}`;
    }
    case "round_done":
      return `  round ${ev.data.round} done · Δ${ev.data.delta} · ${ev.data.remaining} remaining`;
    case "plateau":
      return `⚠ plateau — ${ev.data.remaining} finding(s) unresolved after no progress`;
    case "error":
      return `error: ${ev.data.message}`;
    case "done":
      return `loop done · ${ev.data.status} · ${ev.data.remaining} remaining`;
    default:
      return null;
  }
}

function inferPhaseFromEvent(ev: LoopEvent, prev: PhaseId): PhaseId {
  switch (ev.event) {
    case "eval_start":  return "plan";
    case "eval_progress": return "plan";
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
  // Loop-level activity feed — readable lines from the SSE events (esp. the
  // rule-evaluation phase, which spawns no tracked agent). This is what makes
  // the review console show activity from the first second, like the sim tab.
  const [loopLog, setLoopLog] = useState<string[]>([]);

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
    setLoopLog([]);

    const unsub = subscribeLoop(loopId, async (ev: LoopEvent) => {
      setPhase((p) => inferPhaseFromEvent(ev, p));
      const line = loopEventLine(ev);
      if (line) setLoopLog((prev) => [...prev.slice(-300), line]);
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
          {summary.rounds.length === 0 ? (
            <>
              ✓ Already clean — the design passes every review rule, so the loop
              had nothing to fix. (No findings to begin with.)
            </>
          ) : (
            <>✓ All findings resolved in {summary.rounds.length} round
              {summary.rounds.length === 1 ? "" : "s"}.</>
          )}
        </div>
      )}
      {summary?.error && (
        <div className="px-4 py-2 text-[12px] text-err bg-err/[0.06] border-y border-edge">
          error: {summary.error}
        </div>
      )}

      {/* Console — always present once a loop has started. When a sub-agent is
          active/pinned, show its live stream; otherwise show the loop ACTIVITY
          FEED (rule evaluation, rounds, builds) so the console is never empty —
          this is what fills it during the eval phase, like the sim tab. */}
      {(pinnedAgentId ?? activeAgentId) ? (
        <LiveConsole
          agentRunId={pinnedAgentId ?? activeAgentId}
          idlePlaceholder={isRunning ? "waiting for agent action…" : "no active agent"}
          headerRight={pinnedAgentId ? (
            <button onClick={() => setPinnedAgentId(null)}
              className="ml-2 text-ink-500 hover:text-ink-900 underline">unpin</button>
          ) : undefined}
        />
      ) : (
        <LoopActivityConsole lines={loopLog} running={isRunning} />
      )}

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
  // Each spawned agent gets its OWN dropdown: the row is a toggle, and expanding
  // it reveals that agent's live "doing + thinking" stream inline (its tool calls,
  // assistant lines, and thinking: lines via the shared LiveConsole). Auto-opens
  // while the action is running so you watch it work without clicking.
  const [open, setOpen] = useState(false);
  const running = a.status === "running";
  useEffect(() => { if (running) setOpen(true); }, [running]);

  const dot = a.status === "ok" ? "●" : a.status === "fail" ? "✗" :
              a.status === "cancelled" ? "⊗" : "◐";
  const tone = a.status === "ok" ? "text-ok" : a.status === "fail" ? "text-err" :
               a.status === "cancelled" ? "text-ink-500" : "text-ink-700";
  const hasAgent = !!a.agent_run_id;

  return (
    <div className={"rounded " + (active ? "bg-rail/30" : "")}>
      <div className="text-[11.5px] flex items-center gap-1.5 px-1">
        {hasAgent ? (
          <button
            onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-1.5 flex-1 text-left hover:opacity-80"
            title={open ? "hide agent activity" : "show what this agent is doing + thinking"}
          >
            <span className={"transition-transform text-ink-500 " + (open ? "rotate-180" : "")}>
              <I.Caret size={10} />
            </span>
            <span className={tone}>{dot}</span>
            <span className="font-mono text-ink-500">{a.kind}</span>
            {a.targets.length > 0 && (
              <span className="font-mono text-[10px] text-ink-400">
                {a.targets.slice(0, 3).join(", ")}{a.targets.length > 3 ? "…" : ""}
              </span>
            )}
            <span className="text-ink-700 truncate">· {a.summary || (running ? "working…" : "")}</span>
          </button>
        ) : (
          <div className="flex items-center gap-1.5 flex-1">
            <span className={tone}>{dot}</span>
            <span className="font-mono text-ink-500">{a.kind}</span>
            <span className="text-ink-700">· {a.summary}</span>
          </div>
        )}
        {hasAgent && (
          <button onClick={() => onPin(a.agent_run_id!)}
            className="text-[10px] text-ink-500 hover:text-ink-900 shrink-0"
            title="pin this agent to the main console below">
            pin
          </button>
        )}
      </div>
      {hasAgent && open && (
        <div className="mt-1 mb-1.5 ml-3">
          <LiveConsole
            agentRunId={a.agent_run_id!}
            label={`${a.kind} agent · ${a.status}`}
            idlePlaceholder={running ? "waiting for agent output…" : "(agent finished — reasoning below)"}
            minHeightPx={72}
            maxHeightPx={220}
          />
        </div>
      )}
    </div>
  );
}

// Loop-level activity console. Shows the readable event feed (rule evaluation,
// rounds, builds) so the review console streams from the first second — the
// fix for the previously-empty console during the eval phase. Styling matches
// the shared LiveConsole (white pre, auto-scroll when near the bottom).
function LoopActivityConsole({ lines, running }: { lines: string[]; running: boolean }) {
  const preRef = useRef<HTMLPreElement | null>(null);
  useEffect(() => {
    const el = preRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [lines]);
  return (
    <div className="border-t border-edge px-4 py-2.5 bg-rail/20">
      <div className="text-[11px] text-ink-500 mb-1.5 flex items-center gap-2">
        <I.Terminal size={11} />
        <span>loop activity</span>
        <span className="ml-auto text-[10px] text-ink-400">{lines.length} lines</span>
      </div>
      <pre
        ref={preRef}
        className="text-[11px] font-mono bg-white text-ink-900 border border-edge p-2.5 rounded overflow-auto whitespace-pre-wrap"
        style={{ minHeight: "120px", maxHeight: "240px" }}
      >
{lines.length === 0
  ? <span className="text-ink-400 italic">{running ? "starting — evaluating rules…" : "(idle)"}</span>
  : lines.join("\n")}
      </pre>
    </div>
  );
}
