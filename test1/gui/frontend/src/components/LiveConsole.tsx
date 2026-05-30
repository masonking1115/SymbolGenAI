// Shared dark terminal-style console used by IterationSection (closed-loop
// active sub-agent) and RulesSection (rule_gen agent). Pass the
// agent_run_id; the component owns the subscribeAgent lifecycle, auto-scrolls,
// and shows a placeholder when nothing is streaming yet.

import { useEffect, useRef, useState } from "react";
import { subscribeAgent } from "../api";
import { I } from "./Icon";

interface Props {
  agentRunId: string | null;
  // Optional header label override (default: "Live console — agent {id}").
  label?: string;
  // Optional right-side header content (e.g. an Unpin button).
  headerRight?: React.ReactNode;
  // Placeholder text when no agent is streaming yet.
  idlePlaceholder?: string;
  // Min/max height for the pre block. Defaults match IterationSection.
  minHeightPx?: number;
  maxHeightPx?: number;
}

export function LiveConsole({
  agentRunId,
  label,
  headerRight,
  idlePlaceholder = "(streaming output will appear here)",
  minHeightPx = 160,
  maxHeightPx = 280,
}: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const preRef = useRef<HTMLPreElement | null>(null);

  // Subscribe to the agent's stream. Reset on agent_run_id change so a new
  // agent doesn't inherit the previous one's trailing output.
  useEffect(() => {
    setLines([]);
    if (!agentRunId) return;
    const unsub = subscribeAgent(
      agentRunId,
      (line) => setLines((prev) => [...prev.slice(-400), line]),
      () => { /* keep last lines visible after agent completes */ },
    );
    return () => { unsub(); };
  }, [agentRunId]);

  // Auto-scroll the <pre> itself (NOT the page). scrollIntoView on a child
  // would walk up to the document scroller and jump the entire viewport when
  // the console isn't already on-screen. Only autoscroll when the user is
  // already near the bottom — if they've scrolled up to read older output,
  // don't yank them back.
  useEffect(() => {
    const el = preRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [lines]);

  const headerLabel = label ?? (
    agentRunId
      ? `Live console — agent ${agentRunId.slice(0, 8)}`
      : null
  );

  return (
    <div className="border-t border-edge px-4 py-2.5 bg-rail/20">
      <div className="text-[11px] text-ink-500 mb-1.5 flex items-center gap-2">
        <I.Terminal size={11} />
        {headerLabel ? <span>{headerLabel}</span> : (
          <span className="italic">{idlePlaceholder}</span>
        )}
        {headerRight}
        <span className="ml-auto text-[10px] text-ink-400">{lines.length} lines</span>
      </div>
      <pre
        ref={preRef}
        className="text-[11px] font-mono bg-white text-ink-900 border border-edge p-2.5 rounded overflow-auto whitespace-pre-wrap"
        style={{ minHeight: `${minHeightPx}px`, maxHeight: `${maxHeightPx}px` }}
      >
{lines.length === 0
  ? <span className="text-ink-400 italic">{agentRunId ? "(waiting for first line…)" : "(no active agent)"}</span>
  : lines.join("\n")}
      </pre>
    </div>
  );
}
