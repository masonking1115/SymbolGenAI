import { useEffect, useState } from "react";
import { api, subscribeLoop } from "../api";
import { I } from "./Icon";
import { LiveConsole } from "./LiveConsole";
import { PipelineStrip, type Step, type StepState } from "./PipelineStrip";
import { WorkflowConsole } from "./WorkflowConsole";
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

// Plain-English meaning of each pipeline stage. One source of truth, shared by
// the per-step hover tooltips (PipelineStrip) and the always-visible legend
// below the strip — "Missing" especially isn't self-explanatory.
const STEP_DOCS: { id: string; label: string; desc: string }[] = [
  { id: "plan",         label: "Plan",
    desc: "Decide which of the open findings to act on this round, and pick the action for each (edit / simulate / source a part / lint-fix)." },
  { id: "apply",        label: "Apply",
    desc: "An agent edits the Altium builders (altium/build_*.py) + netlist to implement the chosen fixes." },
  { id: "sim",          label: "Sim",
    desc: "Run ngspice on the affected block(s) to check the change holds up physically (e.g. bias current, rail droop). Skipped when no finding needs simulation." },
  { id: "missing_part", label: "Missing",
    desc: "“Missing part”: the design references a component it doesn't yet have a symbol/footprint for — an agent sources or authors it and places it. Skipped when nothing is missing." },
  { id: "lint_fix",     label: "Lint fix",
    desc: "Auto-correct cosmetic layout-linter nits (label/symbol overlaps, power-stub side, decap grouping). Skipped when the build is already lint-clean." },
  { id: "build",        label: "Build",
    desc: "Regenerate the Altium schematic (SchDoc + SVG renders + lint report) from the edited builders." },
  { id: "re_eval",      label: "Re-eval",
    desc: "Re-run every review rule against the rebuilt design to see which findings cleared and what remains for the next round." },
];
const STEP_DESC: Record<string, string> = Object.fromEntries(STEP_DOCS.map(s => [s.id, s.desc]));

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
    { id: "plan",         label: "Plan",     actor: "py",      state: "pending",                          desc: STEP_DESC.plan },
    { id: "apply",        label: "Apply",    actor: "agent",   state: "pending",                          desc: STEP_DESC.apply },
    { id: "sim",          label: "Sim",      actor: "ngspice", state: everSim ? "pending" : "skipped",    desc: STEP_DESC.sim },
    { id: "missing_part", label: "Missing",  actor: "agent",   state: everMissing ? "pending" : "skipped", desc: STEP_DESC.missing_part },
    { id: "lint_fix",     label: "Lint fix", actor: "agent",   state: everLintFix ? "pending" : "skipped", desc: STEP_DESC.lint_fix },
    { id: "build",        label: "Build",    actor: "build",   state: "pending",                          desc: STEP_DESC.build },
    { id: "re_eval",      label: "Re-eval",  actor: "py",      state: "pending",                          desc: STEP_DESC.re_eval },
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

export function WorkflowSection({ loopId, onLoopCompleted, setHealth, onSummary }: Props) {
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

  // Agents active (or completed) THIS round → one structured panel each in the
  // Steps view (split screen). Sourced from the round's actions, which carry
  // agent_run_id/kind/status/targets.
  const activeAgents = (currentRound?.actions ?? [])
    .filter(a => a.agent_run_id)
    .map(a => ({ id: a.agent_run_id as string, kind: a.kind, status: a.status, targets: a.targets }));
  // One-line "what is the tool doing now" narration from the live phase.
  const phaseNarration = isRunning ? (STEP_DESC[phase] ?? undefined) : undefined;

  return (
    <section className="mt-5 rounded-md border border-edge bg-white">
      <header className="px-4 py-2.5 flex items-center gap-2 border-b border-edge">
        <I.Play size={14} />
        <span className="text-sm font-semibold text-ink-900">Workflow</span>
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
        <StepLegend />
      </div>

      {summary?.status === "plateau" && (
        <div className="px-4 py-2 text-[12px] bg-warn/[0.06] text-ink-700 border-y border-edge">
          <strong>⚠ Loop halted</strong> — no progress for 2 consecutive rounds.{" "}
          {summary.findings_current} findings unresolved.
        </div>
      )}
      {/* Flapping warning — rules whose verdict flipped across rounds without a
          fix that explains it (semantic/sim nondeterminism). The loop's
          "resolution" of these can't be trusted; surface them explicitly. */}
      {summary?.flapping && Object.keys(summary.flapping).length > 0 && (
        <div className="px-4 py-2 text-[12px] bg-warn/[0.08] text-ink-700 border-y border-edge">
          <strong className="text-warn">⚠ Unstable verdicts (flapping)</strong> —
          these rules changed pass/fail across rounds with no fix that explains it
          (LLM/sim nondeterminism). Don't trust their final state without a manual look:
          <ul className="mt-1 list-disc pl-5">
            {Object.entries(summary.flapping).slice(0, 6).map(([rid, n]) => (
              <li key={rid} className="font-mono text-[11px]">
                {rid} <span className="text-ink-500">({n} flip{n === 1 ? "" : "s"})</span>
              </li>
            ))}
          </ul>
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

      {/* Console — always present once a loop has started. A PINNED agent (from
          the round history) gets the full raw LiveConsole for deep inspection.
          Otherwise the WorkflowConsole shows the default Steps view (split per
          agent) with a Raw toggle back to the discrete loop-activity feed. */}
      {pinnedAgentId ? (
        <LiveConsole
          agentRunId={pinnedAgentId}
          headerRight={
            <button onClick={() => setPinnedAgentId(null)}
              className="ml-2 text-ink-500 hover:text-ink-900 underline">unpin</button>
          }
        />
      ) : (
        <WorkflowConsole
          agents={activeAgents}
          rawLines={loopLog}
          running={isRunning}
          phaseNarration={phaseNarration}
        />
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

// Always-available legend explaining what each pipeline stage means. Collapsed
// by default (the strip + per-step tooltips carry the day-to-day signal); expand
// for the plain-English description of every stage, esp. the non-obvious ones
// ("Missing", "Lint fix"). Reads the same STEP_DOCS as the tooltips.
function StepLegend() {
  return (
    <details className="mt-1.5 group">
      <summary className="text-[10.5px] text-ink-500 hover:text-ink-700 cursor-pointer inline-flex items-center gap-1 select-none">
        <I.Caret size={9} className="transition-transform group-open:rotate-180" />
        What do these steps mean?
      </summary>
      <dl className="mt-1.5 pl-3 border-l border-edge space-y-1">
        {STEP_DOCS.map((s) => (
          <div key={s.id} className="text-[11px] leading-snug">
            <dt className="inline font-medium text-ink-800">{s.label}</dt>
            <dd className="inline text-ink-600"> — {s.desc}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
