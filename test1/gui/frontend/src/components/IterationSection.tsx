import { useEffect, useRef, useState } from "react";
import { api, subscribeAgent, subscribeLoop } from "../api";
import { I } from "./Icon";
import type { LoopEvent, LoopSummary, LoopRound, LoopAction } from "../types";

interface Props {
  loopId: string | null;          // null when no loop running/completed
  onLoopCompleted: (status: string) => void;
  setHealth: (h: { text: string; tone: "ok" | "warn" | "err" | "neutral" } | undefined) => void;
  // expose summary up for DiffAndAccept gating (Phase 4D)
  onSummary?: (s: LoopSummary | null) => void;
}

export function IterationSection({ loopId, onLoopCompleted, setHealth, onSummary }: Props) {
  const [summary, setSummary] = useState<LoopSummary | null>(null);
  const [liveConsole, setLiveConsole] = useState<string[]>([]);
  const [activeAgentId, setActiveAgentId] = useState<string | null>(null);
  const [pinnedAgentId, setPinnedAgentId] = useState<string | null>(null);
  const consoleEndRef = useRef<HTMLDivElement | null>(null);

  // Subscribe to the loop stream
  useEffect(() => {
    if (!loopId) return;
    let lastFetch = 0;

    const unsubscribeAgent = { current: null as null | (() => void) };

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
      } catch { /* ignore */ }
    };

    void refresh();

    const unsub = subscribeLoop(loopId, async (ev: LoopEvent) => {
      // Lightweight refresh throttle — most events trigger a summary fetch
      if (Date.now() - lastFetch > 250) {
        lastFetch = Date.now();
        await refresh();
      }
      if (ev.event === "action_start" && ev.data.kind && (ev.data as { agent_run_id?: string }).agent_run_id) {
        setActiveAgentId((ev.data as { agent_run_id?: string }).agent_run_id ?? null);
        setLiveConsole([]);
      }
      if (ev.event === "action_end") {
        setActiveAgentId(null);
      }
    }, (status) => {
      void refresh();
      onLoopCompleted(status);
    });

    return () => { unsub(); unsubscribeAgent.current?.(); };
  }, [loopId, onLoopCompleted, setHealth, onSummary]);

  // Subscribe to the active sub-agent's stream
  useEffect(() => {
    const id = pinnedAgentId ?? activeAgentId;
    if (!id) return;
    const unsub = subscribeAgent(id,
      (line) => setLiveConsole((prev) => [...prev.slice(-200), line]),
      () => {});
    return () => { unsub(); };
  }, [activeAgentId, pinnedAgentId]);

  // Auto-scroll console
  useEffect(() => {
    consoleEndRef.current?.scrollIntoView({ behavior: "auto" });
  }, [liveConsole]);

  if (!loopId) return null;

  return (
    <section className="mt-5 rounded-md border border-edge bg-white">
      <header className="px-4 py-2.5 flex items-center gap-2 border-b border-edge">
        <I.Play size={14} />
        <span className="text-sm font-semibold text-ink-900">Iteration</span>
        <span className="text-[11px] text-ink-500">
          loop {loopId.slice(0, 8)}
          {summary && ` · ${summary.status}${summary.status === "running" ?
            ` · round ${summary.round} of 10` : ""}`}
        </span>
        {summary?.status === "running" && (
          <button
            onClick={() => api.loopCancel(loopId)}
            className="ml-auto h-7 px-2.5 text-[11.5px] rounded border border-edge text-ink-700 hover:border-err hover:text-err"
          >
            ⊗ Cancel
          </button>
        )}
      </header>

      {summary?.status === "plateau" && (
        <div className="px-4 py-2 text-[12px] bg-warn/[0.06] text-ink-700 border-b border-edge">
          <strong>⚠ Loop halted</strong> — no progress for 2 consecutive rounds.{" "}
          {summary.findings_current} findings unresolved.
        </div>
      )}
      {summary?.status === "all_clear" && (
        <div className="px-4 py-2 text-[12px] bg-ok/[0.06] text-ok border-b border-edge">
          ✓ All findings resolved in {summary.rounds.length} rounds.
        </div>
      )}
      {summary?.error && (
        <div className="px-4 py-2 text-[12px] text-err bg-err/[0.06] border-b border-edge">
          error: {summary.error}
        </div>
      )}

      <div className="px-4 py-3 space-y-2">
        {summary?.rounds.map((r) => (
          <RoundCard key={r.n} r={r}
            activeAgentId={pinnedAgentId ?? activeAgentId}
            onPin={setPinnedAgentId} />
        ))}
      </div>

      {(activeAgentId || pinnedAgentId) && (
        <div className="border-t border-edge px-4 py-2.5">
          <div className="text-[11px] text-ink-500 mb-1.5 flex items-center gap-2">
            Live console — agent {(pinnedAgentId ?? activeAgentId)?.slice(0, 8)}
            {pinnedAgentId && (
              <button onClick={() => setPinnedAgentId(null)}
                className="ml-auto text-ink-500 hover:text-ink-900">unpin</button>
            )}
          </div>
          <pre className="text-[11px] font-mono bg-rail/40 p-2 rounded max-h-[200px] overflow-auto">
{liveConsole.join("\n")}
            <div ref={consoleEndRef} />
          </pre>
        </div>
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
