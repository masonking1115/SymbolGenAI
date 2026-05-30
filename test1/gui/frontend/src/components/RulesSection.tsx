import { useCallback, useEffect, useRef, useState } from "react";
import { api, subscribeRuleGen } from "../api";
import { I } from "./Icon";
import { LiveConsole } from "./LiveConsole";
import { PipelineStrip, type Step, type StepState } from "./PipelineStrip";
import type {
  Rule,
  RuleGenEvent,
  RuleGenPhase,
  RuleGenSummary,
  RulesListResponse,
} from "../types";

interface Props {
  onApproveAndRun: () => void;   // start a loop after user clicks "Approve & Run"
  loopRunning: boolean;          // disable buttons while a loop is in flight
}

const SEV_DOT: Record<string, string> = {
  ERROR: "bg-err", WARNING: "bg-warn", INFO: "bg-ink-300",
};

const FAMILY_LABEL: Record<string, string> = {
  schematic: "schematic", simulation: "simulation", design: "design",
};

// ---- Pipeline-phase model -----------------------------------------------
// Mirrors test1/review/rule_gen.py: bundle → dispatch → validate → merge →
// write. `done` and `error` are terminal markers, not displayed as steps.

const PIPELINE_PHASE_ORDER: RuleGenPhase[] = [
  "bundle", "dispatch", "validate", "merge", "write",
];

function pipelineSteps(phase: RuleGenPhase, terminal: boolean,
                       failed: boolean): Step[] {
  const steps: Step[] = [
    { id: "bundle",   label: "Bundle",   actor: "py",    state: "pending" },
    { id: "dispatch", label: "Agent",    actor: "agent", state: "pending" },
    { id: "validate", label: "Validate", actor: "py",    state: "pending" },
    { id: "merge",    label: "Merge",    actor: "py",    state: "pending" },
    { id: "write",    label: "Write",    actor: "py",    state: "pending" },
  ];

  if (terminal && !failed) {
    for (const s of steps) s.state = "done";
    return steps;
  }
  if (failed) {
    // Steps BEFORE the failed phase are done; the failed phase itself is
    // marked fail; later steps stay pending (never reached).
    const failIdx = PIPELINE_PHASE_ORDER.indexOf(phase);
    for (let i = 0; i < steps.length; i++) {
      const idx = PIPELINE_PHASE_ORDER.indexOf(steps[i].id as RuleGenPhase);
      if (idx < failIdx) steps[i].state = "done";
      else if (idx === failIdx) steps[i].state = "fail";
      else steps[i].state = "pending";
    }
    return steps;
  }
  const phaseIdx = PIPELINE_PHASE_ORDER.indexOf(phase);
  for (let i = 0; i < steps.length; i++) {
    const idx = PIPELINE_PHASE_ORDER.indexOf(steps[i].id as RuleGenPhase);
    if (idx < phaseIdx) steps[i].state = "done";
    else if (idx === phaseIdx) steps[i].state = "active";
    else steps[i].state = "pending";
  }
  return steps;
}

// Reduce SSE events into the current phase. The server emits `<phase>` to
// mark phase entry and `<phase>_done` for finish info; we drive state off
// the entry events (so the active phase lights up immediately).
function phaseFromEvent(ev: RuleGenEvent, prev: RuleGenPhase): RuleGenPhase {
  switch (ev.event) {
    case "bundle":   return "bundle";
    case "dispatch": return "dispatch";
    case "validate": return "validate";
    case "merge":    return "merge";
    case "write":    return "write";
    case "done":     return "done";
    case "error":    return "error";
    default:         return prev;
  }
}

export function RulesSection({ onApproveAndRun, loopRunning }: Props) {
  const [data, setData] = useState<RulesListResponse | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});  // by family
  const [error, setError] = useState<string>("");

  // Pipeline-job state. `job` is the latest in-flight or recently-finished
  // job; once it's been done for >5s and `keepVisible` flips false, we hide
  // the pipeline strip + console so the rules list is the focus again.
  const [job, setJob] = useState<RuleGenSummary | null>(null);
  const [phase, setPhase] = useState<RuleGenPhase>("bundle");
  const [keepVisible, setKeepVisible] = useState(false);
  const hideTimerRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    try { setData(await api.rules()); setError(""); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  // On mount: if a recent job is still in memory on the backend, re-attach
  // to it so a tab-switch or page-reload mid-pipeline doesn't lose the view.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const latest = await api.ruleGenLatest();
        if (cancelled) return;
        if ("job_id" in latest && latest.job_id) {
          setJob(latest as RuleGenSummary);
          setPhase((latest as RuleGenSummary).phase);
          if ((latest as RuleGenSummary).status === "running") {
            setKeepVisible(true);
          }
        }
      } catch { /* ignore */ }
    })();
    return () => { cancelled = true; };
  }, []);

  // Subscribe to the active job's SSE stream. Re-runs whenever the job_id
  // changes; cleanup tears down the EventSource.
  useEffect(() => {
    if (!job?.job_id || job.status !== "running") return;
    const unsub = subscribeRuleGen(job.job_id, (ev) => {
      setPhase((p) => phaseFromEvent(ev, p));
      if (ev.event === "dispatch") {
        const aid = (ev.data as { agent_run_id?: string }).agent_run_id;
        if (aid) setJob((prev) => prev ? { ...prev, agent_run_id: aid } : prev);
      }
      if (ev.event === "done") {
        setJob((prev) => prev ? { ...prev, phase: "done", status: "ok",
          result: (ev.data as RuleGenSummary["result"]) ?? prev.result,
          finished_at: Date.now() / 1000 } : prev);
      }
      if (ev.event === "error") {
        setJob((prev) => prev ? { ...prev, phase: "error", status: "fail",
          error: (ev.data as { message?: string }).message ?? "",
          finished_at: Date.now() / 1000 } : prev);
      }
    }, (terminalStatus) => {
      // Reload rules list when the job completes (regardless of ok/fail —
      // failure may have written nothing, but refresh is cheap).
      void refresh();
      // Start the 5-second hide-timer.
      if (hideTimerRef.current) window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = window.setTimeout(() => setKeepVisible(false), 5000);
      // The stream may close before our `done`/`error` event handler fires
      // (race on transport close). Lock the phase to a terminal one so the
      // strip doesn't get stuck on the last "active" phase.
      if (terminalStatus === "fail" || terminalStatus === "stream_error") {
        setPhase((p) => p === "done" ? p : "error");
      } else {
        setPhase((p) => p === "error" ? p : "done");
      }
    });
    return () => { unsub(); };
  }, [job?.job_id, job?.status, refresh]);

  const generate = async () => {
    setError("");
    // Cancel any pending hide-timer from a previous run.
    if (hideTimerRef.current) {
      window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
    try {
      const { job_id } = await api.generateRules();
      setJob({
        job_id,
        phase: "bundle",
        status: "running",
        agent_run_id: null,
        result: null,
        error: "",
        started_at: Date.now() / 1000,
        finished_at: null,
      });
      setPhase("bundle");
      setKeepVisible(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const toggleRule = async (rule_id: string, enabled: boolean) => {
    await api.editRule(rule_id, { enabled });
    await refresh();
  };

  if (!data) return (
    <section className="mt-5">
      <div className="text-sm text-ink-500">Loading rules…{error && ` (${error})`}</div>
    </section>
  );

  const stale = data.stale_sources.length > 0;
  const empty = data.rules.length === 0;

  const generating = job?.status === "running";
  // Show the pipeline pane while a job is active, or for ~5s after it
  // finishes so the user can see the green checkmarks. The hide-timer above
  // flips `keepVisible` false to retract the pane.
  const showPipeline = !!job && (generating || keepVisible);
  const failed = job?.status === "fail";

  return (
    <section className="mt-5 rounded-md border border-edge bg-white">
      <header className="px-4 py-2.5 flex items-center gap-2 border-b border-edge">
        <I.Schematic size={14} />
        <span className="text-sm font-semibold text-ink-900">Rules</span>
        <span className="text-[11px] text-ink-500">
          {data.rules.length} active · {data.by_origin.user} user · {data.rules.filter(r=>!r.enabled).length} disabled
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          <button
            onClick={generate}
            disabled={generating || loopRunning}
            className="h-7 px-2.5 text-[11.5px] rounded border border-edge text-ink-700 hover:border-ink-300 disabled:opacity-50"
          >
            {generating ? "Generating…" : empty ? "Generate rules" : "Regenerate"}
          </button>
          {!empty && (
            <button
              onClick={onApproveAndRun}
              disabled={loopRunning}
              className="h-7 px-2.5 text-[11.5px] rounded bg-ink-900 text-white font-medium hover:bg-black disabled:opacity-50"
            >
              ✓ Approve &amp; Run loop
            </button>
          )}
        </div>
      </header>

      {error && (
        <div className="px-4 py-2 text-[12px] text-err bg-err/[0.04] border-b border-edge">
          {error}
        </div>
      )}

      {/* ---- Rule-gen pipeline viewer (only while generating or just done) ---- */}
      {showPipeline && job && (
        <>
          <div className="px-4 pt-3 pb-2 border-b border-edge bg-rail/10">
            <PipelineStrip
              steps={pipelineSteps(phase, job.status !== "running", failed)}
              badge={
                <span
                  className={
                    "shrink-0 inline-flex items-center gap-1 text-[9.5px] font-mono px-1.5 py-0.5 rounded-full border " +
                    (generating
                      ? "border-violet-300 bg-violet-100 text-violet-700"
                      : failed
                        ? "border-err/40 bg-err/[0.06] text-err"
                        : "border-edge bg-ink-100 text-ink-500")
                  }
                  title={`rule-gen job ${job.job_id}`}
                >
                  <I.Refresh size={9} className={generating ? "animate-spin" : ""} />
                  rule_gen {job.job_id.slice(0, 6)}
                </span>
              }
            />
            {job.status === "ok" && job.result && (
              <div className="mt-2 text-[11.5px] text-ok">
                ✓ Wrote {job.result.count_total} rules
                {" · "}schematic {job.result.count_by_family.schematic}
                {" · "}sim {job.result.count_by_family.simulation}
                {" · "}design {job.result.count_by_family.design}
                {job.result.rejected_unverifiable.length > 0 &&
                  ` · rejected ${job.result.rejected_unverifiable.length} (unverifiable)`}
                {job.result.conflicts.length > 0 &&
                  ` · ${job.result.conflicts.length} user-rule conflicts skipped`}
              </div>
            )}
            {job.status === "fail" && job.error && (
              <div className="mt-2 text-[11.5px] text-err">
                ✗ {job.error}
              </div>
            )}
          </div>
          <LiveConsole
            agentRunId={job.agent_run_id}
            idlePlaceholder={
              generating
                ? phase === "bundle"
                  ? "bundling docs…"
                  : "waiting for rule_gen agent…"
                : "no active agent"
            }
          />
        </>
      )}

      {empty && (
        <div className="px-4 py-6 text-center text-sm text-ink-500">
          No rules yet. Click <em>Generate rules</em> to build them from the
          project docs.
        </div>
      )}

      {stale && (
        <div className="px-4 py-2 text-[12px] bg-warn/[0.06] text-ink-700 border-b border-edge">
          <strong>⚠ Sources changed</strong> since rules were generated —
          {data.stale_sources.length} files newer:
          <ul className="mt-1 list-disc pl-5">
            {data.stale_sources.slice(0, 5).map(s => (
              <li key={s.path} className="font-mono text-[11px]">{s.path}</li>
            ))}
          </ul>
        </div>
      )}

      {!empty && (
        <div className="px-4 py-3 space-y-2">
          {(["schematic", "simulation", "design"] as const).map(fam => {
            const rules = data.rules.filter(r => r.family === fam);
            if (rules.length === 0) return null;
            const open = !!expanded[fam];
            return (
              <div key={fam}>
                <button
                  onClick={() => setExpanded(e => ({ ...e, [fam]: !open }))}
                  className="text-[11.5px] text-ink-700 hover:text-ink-900 flex items-center gap-1.5"
                >
                  {open ? "▾" : "▸"} {FAMILY_LABEL[fam]} ({rules.length})
                </button>
                {open && (
                  <div className="mt-1.5 ml-3 space-y-1">
                    {rules.map(r => (
                      <RuleRow key={r.id} r={r} onToggle={toggleRule} />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function RuleRow({ r, onToggle }: { r: Rule; onToggle: (id: string, en: boolean) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={"rounded border px-2 py-1.5 text-[11.5px] " + (r.enabled ? "border-edge bg-white" : "border-edge/50 bg-ink-100/50")}>
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={r.enabled}
          onChange={(e) => onToggle(r.id, e.target.checked)}
          className="mt-0.5"
        />
        <span className={"mt-1 inline-block w-2 h-2 rounded-full " + SEV_DOT[r.severity]} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="font-mono text-[10px] text-ink-500">{r.id}</span>
            <span className="text-ink-500">·</span>
            <span className="text-ink-500">{r.evaluation}</span>
            {r.origin === "user" && <span className="text-[10px] px-1 rounded bg-warn/15 text-warn">user</span>}
          </div>
          <div className="text-ink-900">{r.title}</div>
          {open && (
            <div className="mt-1.5 pl-2 border-l border-edge text-[11px] text-ink-700">
              {r.source.map((s, i) => (
                <div key={i} className="mb-1">
                  <span className="font-mono text-ink-500">{s.doc}:{s.loc}</span>
                  {s.quote && <div className="italic text-ink-500">"{s.quote}"</div>}
                </div>
              ))}
              {r.fix_hint && <div className="mt-1"><strong>fix:</strong> {r.fix_hint}</div>}
              {r.predicate && (
                <pre className="mt-1 text-[10.5px] bg-rail/40 px-1.5 py-1 rounded overflow-auto">
{JSON.stringify(r.predicate, null, 2)}
                </pre>
              )}
              {r.prompt && (
                <div className="mt-1">
                  <strong>prompt:</strong>
                  <div className="text-[11px] text-ink-700 whitespace-pre-wrap">{r.prompt}</div>
                </div>
              )}
            </div>
          )}
          <button
            onClick={() => setOpen(o => !o)}
            className="mt-1 text-[10px] text-ink-500 hover:text-ink-900"
          >
            {open ? "hide details" : "details"}
          </button>
        </div>
      </div>
    </div>
  );
}
