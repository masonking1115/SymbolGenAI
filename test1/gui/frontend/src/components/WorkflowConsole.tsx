// Workflow console with two views:
//   • "Steps"  (default) — a human-readable, step-by-step narrative of what the
//     tool is doing. When multiple agents run at once, each gets its own panel
//     side-by-side (split screen). Each panel distills the agent's raw stream
//     into clean bullet steps (tool calls → "reading X / editing Y", thinking
//     → condensed) instead of the raw terminal dump.
//   • "Raw"    — the original discrete event/log console (loop activity feed or
//     the raw agent stream), for when you want the unfiltered detail.
//
// Both views read the same streams; the toggle just changes presentation.

import { useEffect, useRef, useState } from "react";
import { subscribeAgent } from "../api";
import { I } from "./Icon";
import { LiveConsole } from "./LiveConsole";
import type { LoopRound } from "../types";

export type ConsoleView = "steps" | "agents" | "raw";

export interface ActiveAgent {
  id: string;            // agent_run_id
  kind: string;          // "apply" | "sim" | "missing_part" | "lint_fix"
  status: string;        // "running" | "ok" | "fail" | ...
  targets?: string[];
}

// ---- Raw-stream → readable step distillation ----------------------------
// claude -p agents emit raw lines (tool calls, assistant prose, "thinking:"
// lines). We turn the noisy ones into short, skimmable steps. This is
// best-effort string heuristics — unknown lines pass through trimmed.

interface Step { text: string; kind: "read" | "edit" | "run" | "think" | "say" | "tool" }

function distill(line: string): Step | null {
  const l = line.trim();
  if (!l) return null;
  // Tool calls the agent makes (the harness prints these). Map common ones to
  // plain verbs.
  const tool = l.match(/^\s*[●•*-]?\s*(Read|Edit|Write|Glob|Grep|Bash|Task|WebSearch|WebFetch)\b[:(]?\s*(.*)$/);
  if (tool) {
    const [, t, rest] = tool;
    const arg = rest.replace(/[)"'`]+$/g, "").slice(0, 80);
    if (t === "Read" || t === "Glob" || t === "Grep") return { kind: "read", text: `reading ${arg || "files"}` };
    if (t === "Edit" || t === "Write") return { kind: "edit", text: `editing ${arg || "a file"}` };
    if (t === "Bash") return { kind: "run", text: `running ${arg || "a command"}` };
    if (t === "WebSearch" || t === "WebFetch") return { kind: "run", text: `searching the web ${arg ? "· " + arg : ""}` };
    return { kind: "tool", text: `${t.toLowerCase()} ${arg}`.trim() };
  }
  // Thinking lines (the agent's reasoning, when surfaced).
  const think = l.match(/^\s*(?:thinking|reasoning)\s*[:>-]\s*(.*)$/i);
  if (think) return { kind: "think", text: think[1].slice(0, 160) };
  // Obvious status/verdict markers.
  if (/^\s*(✓|✗|PASS|FAIL|done|wrote|error)\b/i.test(l)) return { kind: "say", text: l.slice(0, 160) };
  // Otherwise: an assistant prose line — keep short ones as narration.
  if (l.length <= 200 && !l.startsWith("{") && !l.startsWith("[")) return { kind: "say", text: l };
  return null;
}

const STEP_TONE: Record<Step["kind"], string> = {
  read: "text-ink-500", edit: "text-blue-600", run: "text-amber-700",
  think: "text-violet-600 italic", say: "text-ink-700", tool: "text-ink-500",
};
const STEP_GLYPH: Record<Step["kind"], string> = {
  read: "○", edit: "✎", run: "▸", think: "…", say: "·", tool: "·",
};

// One agent's distilled step list. Subscribes to the agent stream itself so
// each panel is independent (true split-screen, concurrent).
function StructuredAgentPanel({ agent }: { agent: ActiveAgent }) {
  const [steps, setSteps] = useState<Step[]>([]);
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setSteps([]);
    const unsub = subscribeAgent(agent.id, (line) => {
      const s = distill(line);
      if (s) setSteps((prev) => {
        // de-dupe consecutive identical steps (agents repeat lines)
        if (prev.length && prev[prev.length - 1].text === s.text) return prev;
        return [...prev.slice(-120), s];
      });
    });
    return () => { unsub(); };
  }, [agent.id]);

  useEffect(() => {
    const el = boxRef.current;
    if (el) {
      const near = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
      if (near) el.scrollTop = el.scrollHeight;
    }
  }, [steps]);

  const running = agent.status === "running";
  const tone = agent.status === "ok" ? "text-ok" : agent.status === "fail" ? "text-err" : "text-ink-700";

  return (
    <div className="flex-1 min-w-[200px] rounded border border-edge bg-white overflow-hidden">
      <div className="px-2.5 py-1.5 border-b border-edge flex items-center gap-1.5 text-[11px]">
        {running
          ? <span className="w-2.5 h-2.5 rounded-full border-2 border-ink-300 border-t-violet-500 animate-spin" />
          : <span className={tone}>{agent.status === "ok" ? "✓" : agent.status === "fail" ? "✗" : "●"}</span>}
        <span className="font-medium text-ink-800">{agent.kind}</span>
        {agent.targets && agent.targets.length > 0 && (
          <span className="font-mono text-[10px] text-ink-400 truncate">
            {agent.targets.slice(0, 2).join(", ")}{agent.targets.length > 2 ? "…" : ""}
          </span>
        )}
        <span className="ml-auto font-mono text-[9.5px] text-ink-300">{agent.id.slice(0, 6)}</span>
      </div>
      <div ref={boxRef} className="px-2.5 py-2 overflow-auto text-[11px] leading-snug space-y-0.5"
           style={{ minHeight: 120, maxHeight: 240 }}>
        {steps.length === 0
          ? <span className="text-ink-400 italic">{running ? "starting…" : "(no steps captured)"}</span>
          : steps.map((s, i) => (
            <div key={i} className={"flex gap-1.5 " + STEP_TONE[s.kind]}>
              <span className="select-none opacity-60">{STEP_GLYPH[s.kind]}</span>
              <span className="whitespace-pre-wrap break-words">{s.text}</span>
            </div>
          ))}
      </div>
    </div>
  );
}

// ---- "All agents" roll-up ------------------------------------------------
// Every agent spawned across the WHOLE loop (all rounds), newest first — one
// scannable list with a round tag + status badge, each click-to-expand to its
// live (and post-hoc) reasoning stream. Complements the per-round Steps view.
interface FlatAgent {
  id: string; kind: string; status: string; targets: string[];
  round: number; started_at: number;
}

function flattenAgents(rounds: LoopRound[]): FlatAgent[] {
  const out: FlatAgent[] = [];
  for (const r of rounds) {
    for (const a of r.actions ?? []) {
      if (!a.agent_run_id) continue;       // only real sub-agents (eval spawns none)
      out.push({
        id: a.agent_run_id, kind: a.kind, status: a.status,
        targets: a.targets ?? [], round: r.n, started_at: a.started_at,
      });
    }
  }
  // Newest first; de-dupe by run id (an action can appear across summary refreshes).
  const seen = new Set<string>();
  return out
    .sort((x, y) => (y.started_at || 0) - (x.started_at || 0))
    .filter((a) => (seen.has(a.id) ? false : (seen.add(a.id), true)));
}

function AllAgentsRow({ a }: { a: FlatAgent }) {
  const running = a.status === "running";
  const [open, setOpen] = useState(running);
  useEffect(() => { if (running) setOpen(true); }, [running]);
  const dot = a.status === "ok" ? "●" : a.status === "fail" ? "✗"
    : a.status === "cancelled" ? "⊗" : "◐";
  const tone = a.status === "ok" ? "text-ok" : a.status === "fail" ? "text-err"
    : a.status === "cancelled" ? "text-ink-500" : "text-violet-600";
  return (
    <div className="rounded border border-edge bg-white">
      <button onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-1.5 px-2 py-1.5 text-[11.5px] text-left hover:bg-rail/30">
        <span className={"transition-transform text-ink-400 " + (open ? "rotate-180" : "")}>
          <I.Caret size={10} />
        </span>
        {running
          ? <span className="w-2.5 h-2.5 rounded-full border-2 border-ink-300 border-t-violet-500 animate-spin" />
          : <span className={tone}>{dot}</span>}
        <span className="font-medium text-ink-800">{a.kind}</span>
        <span className="text-[9.5px] px-1 rounded-full bg-ink-100 text-ink-500">round {a.round}</span>
        {a.targets.length > 0 && (
          <span className="font-mono text-[10px] text-ink-400 truncate">
            {a.targets.slice(0, 3).join(", ")}{a.targets.length > 3 ? "…" : ""}
          </span>
        )}
        <span className={"ml-auto font-mono text-[9.5px] " + tone}>{a.status}</span>
        <span className="font-mono text-[9.5px] text-ink-300">{a.id.slice(0, 6)}</span>
      </button>
      {open && (
        <div className="px-2 pb-2">
          <LiveConsole
            agentRunId={a.id}
            label={`${a.kind} · round ${a.round} · ${a.status}`}
            idlePlaceholder={running ? "waiting for agent output…" : "(agent finished — reasoning below)"}
            minHeightPx={72}
            maxHeightPx={220}
          />
        </div>
      )}
    </div>
  );
}

interface Props {
  // The agents that are (or were) active this round — each gets a panel.
  agents: ActiveAgent[];
  // Every round's actions (all rounds), for the "All agents" roll-up view.
  rounds?: LoopRound[];
  // Raw loop-activity lines (the discrete event feed) for the Raw view.
  rawLines: string[];
  running: boolean;
  // Plain-English description of the current phase (the "what is it doing now").
  phaseNarration?: string;
}

export function WorkflowConsole({ agents, rounds, rawLines, running, phaseNarration }: Props) {
  const [view, setView] = useState<ConsoleView>("steps");
  const rawRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    const el = rawRef.current;
    if (el) {
      const near = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
      if (near) el.scrollTop = el.scrollHeight;
    }
  }, [rawLines]);

  const liveAgents = agents.filter(a => a.id);
  const allAgents = flattenAgents(rounds ?? []);

  const VIEW_LABEL: Record<ConsoleView, string> = { steps: "Steps", agents: "Agents", raw: "Raw" };
  return (
    <div className="border-t border-edge px-4 py-2.5 bg-rail/20">
      <div className="text-[11px] text-ink-500 mb-1.5 flex items-center gap-2">
        <I.Terminal size={11} />
        <span>console</span>
        {/* Steps | Agents | Raw toggle */}
        <span className="inline-flex rounded border border-edge overflow-hidden ml-1">
          {(["steps", "agents", "raw"] as const).map(v => (
            <button key={v} onClick={() => setView(v)}
              className={"px-2 py-0.5 text-[10px] " +
                (view === v ? "bg-ink-900 text-white" : "bg-white text-ink-600 hover:bg-ink-50")}>
              {VIEW_LABEL[v]}
            </button>
          ))}
        </span>
        {phaseNarration && <span className="text-ink-600 truncate">· {phaseNarration}</span>}
        <span className="ml-auto text-[10px] text-ink-400">
          {view === "steps" ? `${liveAgents.length} this round`
            : view === "agents" ? `${allAgents.length} total`
            : `${rawLines.length} lines`}
        </span>
      </div>

      {view === "agents" ? (
        allAgents.length === 0 ? (
          <div className="rounded border border-edge bg-white px-3 py-4 text-[11.5px] text-ink-500"
               style={{ minHeight: 120 }}>
            No agents have run in this loop yet. Each spawned sub-agent (apply,
            symbol-gen, lint-fix, sim, missing-part, topology) appears here — click
            one to see what it did + its reasoning.
          </div>
        ) : (
          // Flat list of EVERY agent across ALL rounds, newest first.
          <div className="space-y-1 overflow-auto" style={{ maxHeight: 360 }}>
            {allAgents.map(a => <AllAgentsRow key={a.id} a={a} />)}
          </div>
        )
      ) : view === "steps" ? (
        liveAgents.length === 0 ? (
          <div className="rounded border border-edge bg-white px-3 py-4 text-[11.5px] text-ink-500"
               style={{ minHeight: 120 }}>
            {running
              ? (phaseNarration || "evaluating rules — no sub-agent running yet (the eval phase spawns none).")
              : "No agents ran this round. Switch to Raw for the full event log."}
          </div>
        ) : (
          // Split screen: one panel per agent, side-by-side (wraps on narrow).
          <div className="flex flex-wrap gap-2">
            {liveAgents.map(a => <StructuredAgentPanel key={a.id} agent={a} />)}
          </div>
        )
      ) : (
        <pre ref={rawRef}
          className="text-[11px] font-mono bg-white text-ink-900 border border-edge p-2.5 rounded overflow-auto whitespace-pre-wrap"
          style={{ minHeight: 120, maxHeight: 240 }}>
{rawLines.length === 0
  ? <span className="text-ink-400 italic">{running ? "starting — evaluating rules…" : "(idle)"}</span>
  : rawLines.join("\n")}
        </pre>
      )}
    </div>
  );
}
