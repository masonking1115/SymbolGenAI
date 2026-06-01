// Shared agent console — the ONE console used by Schematic Generation,
// Simulation, and Design Review. Standardizes the chrome across tabs (same
// view toggle + styling); the agents differ per tab, the presentation does not.
//
// Three views (identical everywhere):
//   • "Reasoning" (default) — a per-agent, structured timeline of what each
//     agent is doing AND thinking. When >1 agent runs at once, each gets its own
//     vertical pane (split screen). Each pane interleaves the agent's reasoning
//     (full thinking blocks) with the actions it takes (reading / editing /
//     running) — so you see intent next to act, not just a terminal dump.
//   • "Raw" — the unfiltered line feed (build output / loop activity / raw agent
//     stream), for when you want everything verbatim.
//   • "Agents" — (only when `rounds` is supplied, i.e. the review loop) a roll-up
//     of every agent across all rounds, click-to-expand.
//
// Structured reasoning comes from the backend's typed `ev` (agent.py
// _summarize_event) carried alongside each streamed line by subscribeAgent.

import { useEffect, useRef, useState } from "react";
import { subscribeAgent, type AgentEv } from "../api";
import { I } from "./Icon";
import { LiveConsole } from "./LiveConsole";
import type { LoopRound } from "../types";

export type ConsoleView = "reasoning" | "agents" | "raw";

export interface ActiveAgent {
  id: string;            // agent_run_id
  kind: string;          // "apply" | "sim" | "interpret" | "lint_fix" | "generate" | ...
  status: string;        // "running" | "ok" | "fail" | "cancelled"
  targets?: string[];
}

// ---- A single timeline entry in a pane ----------------------------------
// Built from the structured `ev` when present; falls back to distill() for
// pre-`ev` (buffered/legacy) lines so older runs still render.
type Entry =
  | { kind: "think"; text: string }
  | { kind: "read" | "edit" | "run" | "say" | "tool" | "status"; text: string };

const TONE: Record<Entry["kind"], string> = {
  think: "text-violet-700",
  read: "text-ink-500",
  edit: "text-blue-600",
  run: "text-amber-700",
  say: "text-ink-700",
  tool: "text-ink-500",
  status: "text-ink-600",
};
const GLYPH: Record<Entry["kind"], string> = {
  think: "💭", read: "○", edit: "✎", run: "▸", say: "·", tool: "·", status: "›",
};

// Map a structured backend event → a timeline entry.
function entryFromEv(ev: AgentEv): Entry | null {
  switch (ev.t) {
    case "think": {
      const t = (ev.text || "").trim();
      return t ? { kind: "think", text: t } : null;
    }
    case "say": {
      const t = (ev.text || "").trim();
      return t ? { kind: "say", text: t } : null;
    }
    case "tool": {
      const name = ev.name || "";
      const arg = (ev.target || "").slice(0, 100);
      if (name === "Read" || name === "Glob" || name === "Grep")
        return { kind: "read", text: `reading ${arg || "files"}` };
      if (name === "Edit" || name === "Write")
        return { kind: "edit", text: `editing ${arg || "a file"}` };
      if (name === "Bash")
        return { kind: "run", text: `running ${arg || "a command"}` };
      if (name === "WebSearch" || name === "WebFetch")
        return { kind: "run", text: `searching the web${arg ? " · " + arg : ""}` };
      return { kind: "tool", text: `${name.toLowerCase()} ${arg}`.trim() };
    }
    case "result":
      return { kind: "status", text: `result: ${ev.subtype || "done"}` };
    case "stderr":
      return { kind: "status", text: ev.text };
    case "raw":
    default:
      return null; // raw goes to the Raw view, not the reasoning timeline
  }
}

// Fallback: distill a plain string (no `ev`) into an entry. Mirrors the legacy
// WorkflowConsole heuristics; only used for buffered/older lines.
export function distill(line: string): Entry | null {
  const l = line.trim();
  if (!l) return null;
  const tool = l.match(/^\s*[●•*-]?\s*(Read|Edit|Write|Glob|Grep|Bash|Task|WebSearch|WebFetch)\b[:(]?\s*(.*)$/);
  if (tool) {
    const [, t, rest] = tool;
    const arg = rest.replace(/[)"'`]+$/g, "").slice(0, 90);
    if (t === "Read" || t === "Glob" || t === "Grep") return { kind: "read", text: `reading ${arg || "files"}` };
    if (t === "Edit" || t === "Write") return { kind: "edit", text: `editing ${arg || "a file"}` };
    if (t === "Bash") return { kind: "run", text: `running ${arg || "a command"}` };
    if (t === "WebSearch" || t === "WebFetch") return { kind: "run", text: `searching the web ${arg ? "· " + arg : ""}` };
    return { kind: "tool", text: `${t.toLowerCase()} ${arg}`.trim() };
  }
  const think = l.match(/^\s*(?:thinking|reasoning)\s*[:>-]\s*(.*)$/i);
  if (think) return { kind: "think", text: think[1] };
  if (/^\s*(✓|✗|PASS|FAIL|done|wrote|error|result:)\b/i.test(l)) return { kind: "status", text: l };
  if (l.length <= 240 && !l.startsWith("{") && !l.startsWith("[")) return { kind: "say", text: l };
  return null;
}

// ---- One agent's pane (independent live subscription = true split-screen) --
function AgentPane({ agent }: { agent: ActiveAgent }) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [raw, setRaw] = useState<string[]>([]);
  const [mode, setMode] = useState<"reasoning" | "raw">("reasoning");
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setEntries([]); setRaw([]);
    const unsub = subscribeAgent(agent.id, (line, ev) => {
      setRaw((prev) => [...prev.slice(-400), line]);
      const e = ev ? entryFromEv(ev) : distill(line);
      if (!e) return;
      setEntries((prev) => {
        // Merge consecutive thinking into one block (the agent emits reasoning in
        // chunks); de-dupe identical consecutive non-think lines.
        const last = prev[prev.length - 1];
        if (e.kind === "think" && last && last.kind === "think") {
          const merged = { kind: "think" as const, text: last.text + " " + e.text };
          return [...prev.slice(0, -1), merged];
        }
        if (last && last.kind === e.kind && last.text === e.text) return prev;
        return [...prev.slice(-200), e];
      });
    });
    return () => { unsub(); };
  }, [agent.id]);

  useEffect(() => {
    const el = boxRef.current;
    if (el) {
      const near = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
      if (near) el.scrollTop = el.scrollHeight;
    }
  }, [entries, raw, mode]);

  const running = agent.status === "running";
  const tone = agent.status === "ok" ? "text-ok" : agent.status === "fail" ? "text-err" : "text-ink-700";

  return (
    <div className="flex-1 min-w-[240px] rounded border border-edge bg-white overflow-hidden flex flex-col">
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
        {/* per-pane reasoning|raw toggle */}
        <span className="ml-auto inline-flex rounded border border-edge overflow-hidden">
          {(["reasoning", "raw"] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)}
              className={"px-1.5 py-0.5 text-[9px] " +
                (mode === m ? "bg-ink-800 text-white" : "bg-white text-ink-500 hover:bg-ink-50")}>
              {m}
            </button>
          ))}
        </span>
        <span className="font-mono text-[9.5px] text-ink-300">{agent.id.slice(0, 6)}</span>
      </div>
      <div ref={boxRef} className="px-2.5 py-2 overflow-auto text-[11px] leading-snug flex-1"
           style={{ minHeight: 140, maxHeight: 300 }}>
        {mode === "raw" ? (
          <pre className="whitespace-pre-wrap break-words font-mono text-[10.5px] text-ink-800">
            {raw.length === 0 ? (running ? "(waiting for output…)" : "(no output)") : raw.join("\n")}
          </pre>
        ) : entries.length === 0 ? (
          <span className="text-ink-400 italic">{running ? "starting…" : "(no activity captured)"}</span>
        ) : (
          <div className="space-y-1">
            {entries.map((e, i) =>
              e.kind === "think" ? (
                // Reasoning callout — the "why", shown in full (not truncated).
                <div key={i} className="rounded bg-violet-50 border-l-2 border-violet-300 px-2 py-1 text-violet-800">
                  <span className="select-none mr-1">{GLYPH.think}</span>
                  <span className="whitespace-pre-wrap break-words italic">{e.text}</span>
                </div>
              ) : (
                <div key={i} className={"flex gap-1.5 " + TONE[e.kind]}>
                  <span className="select-none opacity-60">{GLYPH[e.kind]}</span>
                  <span className="whitespace-pre-wrap break-words">{e.text}</span>
                </div>
              ),
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---- "All agents" roll-up (review loop only) -----------------------------
interface FlatAgent { id: string; kind: string; status: string; targets: string[]; round: number; started_at: number }

function flattenAgents(rounds: LoopRound[]): FlatAgent[] {
  const out: FlatAgent[] = [];
  for (const r of rounds) {
    for (const a of r.actions ?? []) {
      if (!a.agent_run_id) continue;
      out.push({ id: a.agent_run_id, kind: a.kind, status: a.status, targets: a.targets ?? [], round: r.n, started_at: a.started_at });
    }
  }
  const seen = new Set<string>();
  return out
    .sort((x, y) => (y.started_at || 0) - (x.started_at || 0))
    .filter((a) => (seen.has(a.id) ? false : (seen.add(a.id), true)));
}

function AllAgentsRow({ a }: { a: FlatAgent }) {
  const running = a.status === "running";
  const [open, setOpen] = useState(running);
  useEffect(() => { if (running) setOpen(true); }, [running]);
  const dot = a.status === "ok" ? "●" : a.status === "fail" ? "✗" : a.status === "cancelled" ? "⊗" : "◐";
  const tone = a.status === "ok" ? "text-ok" : a.status === "fail" ? "text-err" : a.status === "cancelled" ? "text-ink-500" : "text-violet-600";
  return (
    <div className="rounded border border-edge bg-white">
      <button onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-1.5 px-2 py-1.5 text-[11.5px] text-left hover:bg-rail/30">
        <span className={"transition-transform text-ink-400 " + (open ? "rotate-180" : "")}><I.Caret size={10} /></span>
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
          <LiveConsole agentRunId={a.id} label={`${a.kind} · round ${a.round} · ${a.status}`}
            idlePlaceholder={running ? "waiting for agent output…" : "(agent finished — reasoning below)"}
            minHeightPx={72} maxHeightPx={220} />
        </div>
      )}
    </div>
  );
}

export interface AgentConsoleProps {
  agents: ActiveAgent[];          // agents to partition into panes (current activity)
  rawLines?: string[];            // tab-level flat feed (build output / loop events)
  running: boolean;
  status?: "idle" | "running" | "ok" | "fail";
  phaseNarration?: string;        // one-liner "what is it doing now"
  rounds?: LoopRound[];           // review loop only → enables the Agents roll-up
  /** Compact header label (defaults to "console"). */
  title?: string;
}

export function AgentConsole({ agents, rawLines = [], running, phaseNarration, rounds, title = "console" }: AgentConsoleProps) {
  const hasRollup = Array.isArray(rounds);
  const [view, setView] = useState<ConsoleView>("reasoning");
  const rawRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    const el = rawRef.current;
    if (el) {
      const near = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
      if (near) el.scrollTop = el.scrollHeight;
    }
  }, [rawLines]);

  const liveAgents = agents.filter((a) => a.id);
  const allAgents = flattenAgents(rounds ?? []);
  const views: ConsoleView[] = hasRollup ? ["reasoning", "agents", "raw"] : ["reasoning", "raw"];
  const VIEW_LABEL: Record<ConsoleView, string> = { reasoning: "Reasoning", agents: "Agents", raw: "Raw" };

  // N-pane vertical split: 1 agent → one full-width pane; 2–3 → side-by-side
  // columns; more → wrap (each keeps a 240px min). Auto-collapses to 1.
  return (
    <div className="border-t border-edge px-4 py-2.5 bg-rail/20">
      <div className="text-[11px] text-ink-500 mb-1.5 flex items-center gap-2">
        <I.Terminal size={11} />
        <span>{title}</span>
        <span className="inline-flex rounded border border-edge overflow-hidden ml-1">
          {views.map((v) => (
            <button key={v} onClick={() => setView(v)}
              className={"px-2 py-0.5 text-[10px] " + (view === v ? "bg-ink-900 text-white" : "bg-white text-ink-600 hover:bg-ink-50")}>
              {VIEW_LABEL[v]}
            </button>
          ))}
        </span>
        {phaseNarration && <span className="text-ink-600 truncate">· {phaseNarration}</span>}
        <span className="ml-auto text-[10px] text-ink-400">
          {view === "reasoning" ? `${liveAgents.length} agent${liveAgents.length === 1 ? "" : "s"}`
            : view === "agents" ? `${allAgents.length} total`
            : `${rawLines.length} lines`}
        </span>
      </div>

      {view === "agents" ? (
        allAgents.length === 0 ? (
          <div className="rounded border border-edge bg-white px-3 py-4 text-[11.5px] text-ink-500" style={{ minHeight: 120 }}>
            No agents have run yet. Each spawned sub-agent appears here — click one to see what it did + its reasoning.
          </div>
        ) : (
          <div className="space-y-1 overflow-auto" style={{ maxHeight: 360 }}>
            {allAgents.map((a) => <AllAgentsRow key={a.id} a={a} />)}
          </div>
        )
      ) : view === "reasoning" ? (
        liveAgents.length === 0 ? (
          <div className="rounded border border-edge bg-white px-3 py-4 text-[11.5px] text-ink-500" style={{ minHeight: 120 }}>
            {running ? (phaseNarration || "working — no sub-agent running yet.") : "No agent activity. Switch to Raw for the full log."}
          </div>
        ) : (
          // Split screen: one pane per agent, side-by-side (wraps on narrow widths).
          <div className="flex flex-wrap gap-2 items-stretch">
            {liveAgents.map((a) => <AgentPane key={a.id} agent={a} />)}
          </div>
        )
      ) : (
        <pre ref={rawRef}
          className="text-[11px] font-mono bg-white text-ink-900 border border-edge p-2.5 rounded overflow-auto whitespace-pre-wrap"
          style={{ minHeight: 120, maxHeight: 280 }}>
{rawLines.length === 0
  ? <span className="text-ink-400 italic">{running ? "starting…" : "(idle)"}</span>
  : rawLines.join("\n")}
        </pre>
      )}
    </div>
  );
}
