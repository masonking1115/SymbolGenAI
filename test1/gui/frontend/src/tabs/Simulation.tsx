import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { api, subscribeAgent } from "../api";
import { I } from "../components/Icon";
import type { SimBlock, SimResult, SimSeries, SimXAxis } from "../types";

type StepState = "pending" | "active" | "pass" | "fail" | "warn" | "done";

// Derive the workflow-stage states from the phase + the ngspice result + the
// agent's streamed tool calls. The flow is context-first:
//   read context → apply params → simulate → interpret vs spec
function workflowSteps(res: SimResult | undefined, it: Interp | undefined):
  { label: string; hint: string; state: StepState }[] {
  const phase = it?.phase;
  const ord = { setup: 0, sim: 1, interpret: 2, done: 3 } as const;
  const p = phase ? ord[phase] : -1;
  const verdict = it?.verdict;
  const fresh = it?.setupFresh;

  // 1 + 2: context read + param apply both happen in the setup stage.
  const setupState: StepState =
    p < 0 ? "pending" : p === 0 ? "active" : "done";
  const ctxHint = setupState === "done" ? (fresh ? "from cache" : "read")
    : setupState === "active" ? "reading…" : "";
  const parHint = setupState === "done" ? (fresh ? "from cache" : "applied")
    : setupState === "active" ? "…" : "";

  // 3: simulate.
  const sim: StepState = res
    ? (res.status !== "ran" ? "done" : res.ok ? "pass" : "fail")
    : (p >= 1 ? "active" : "pending");

  // 4: interpret.
  let interp: StepState = "pending";
  if (verdict) interp = verdict === "MEETS_SPEC" ? "pass" : verdict === "OUT_OF_SPEC" ? "fail" : "warn";
  else if (phase === "interpret") interp = "active";
  else if (phase === "done") interp = "done";

  return [
    { label: "Read context", hint: ctxHint, state: setupState },
    { label: "Apply params", hint: parHint, state: setupState },
    { label: "Simulate", hint: "ngspice", state: sim },
    { label: "Interpret vs spec", hint: verdict ? verdict.replace(/_/g, " ").toLowerCase() : "", state: interp },
  ];
}

function StepIcon({ state }: { state: StepState }) {
  const base = "w-5 h-5 rounded-full grid place-items-center shrink-0";
  if (state === "pass") return <span className={base + " bg-ok/15 text-ok"}><I.Check size={12} /></span>;
  if (state === "fail") return <span className={base + " bg-err/15 text-err"}><I.X size={12} /></span>;
  if (state === "warn") return <span className={base + " bg-warn/15 text-warn"}><I.Dot size={12} /></span>;
  if (state === "active") return (
    <span className={base + " bg-ink-100"}>
      <span className="w-3 h-3 rounded-full border-2 border-ink-300 border-t-ink-700 animate-spin" />
    </span>
  );
  if (state === "done") return <span className={base + " bg-ink-100 text-ink-500"}><I.Check size={12} /></span>;
  return <span className={base + " border border-edge text-ink-300"}><I.Dot size={10} /></span>;
}

function WorkflowSteps({ res, it }: { res?: SimResult; it?: Interp }) {
  const steps = workflowSteps(res, it);
  return (
    <div className="flex items-center gap-1.5 mb-3 pb-3 border-b border-edge/60">
      {steps.map((s, i) => (
        <Fragment key={s.label}>
          <div className="flex items-center gap-1.5">
            <StepIcon state={s.state} />
            <div className="leading-tight">
              <div className="text-[11px] text-ink-700 whitespace-nowrap">{s.label}</div>
              {s.hint && <div className="text-[10px] text-ink-500 whitespace-nowrap">{s.hint}</div>}
            </div>
          </div>
          {i < steps.length - 1 && <div className="flex-1 h-px bg-edge min-w-[10px]" />}
        </Fragment>
      ))}
    </div>
  );
}

interface Suggestion {
  text: string;
  checked: boolean;
}

interface Interp {
  running: boolean;
  lines: string[];
  phase?: "setup" | "sim" | "interpret" | "done";
  setupFresh?: boolean;   // true if the cached scenario was reused (no setup agent)
  verdict?: "MEETS_SPEC" | "OUT_OF_SPEC" | "NEEDS_CLARIFICATION";
  margin?: string;
  suggestions?: Suggestion[];
  clarify?: string;
  iterations?: string;   // "N re-sims, changed X" (bounded to 3)
}

function parseVerdict(text: string): Partial<Interp> {
  const grab = (k: string) => {
    const m = text.match(new RegExp(`^\\s*${k}:\\s*(.+)$`, "mi"));
    return m ? m[1].trim() : undefined;
  };
  const out: Partial<Interp> = {};
  const v = grab("VERDICT");
  if (v && /MEETS_SPEC|OUT_OF_SPEC|NEEDS_CLARIFICATION/i.test(v)) {
    out.verdict = v.toUpperCase().match(/MEETS_SPEC|OUT_OF_SPEC|NEEDS_CLARIFICATION/)![0] as Interp["verdict"];
  }
  const margin = grab("MARGIN");
  if (margin) out.margin = margin;
  const clarify = grab("CLARIFY");
  if (clarify && !/^none$/i.test(clarify)) out.clarify = clarify;
  const iters = grab("ITERATIONS");
  if (iters && !/^(0|none)\b/i.test(iters)) out.iterations = iters;

  // SUGGESTIONS: collect bullets until the next field / end. Bullets can wrap
  // across lines, so fold continuation lines into the current bullet.
  const lines = text.split("\n");
  const si = lines.findIndex((l) => /^\s*SUGGESTIONS:/i.test(l));
  if (si >= 0) {
    const sugg: Suggestion[] = [];
    let cur: string | null = null;
    const flush = () => {
      if (cur !== null) {
        const t = cur.trim();
        if (t && !/^none$/i.test(t)) sugg.push({ text: t, checked: true });
      }
      cur = null;
    };
    for (let i = si + 1; i < lines.length; i++) {
      if (/^\s*(CLARIFY|VERDICT|MARGIN):/i.test(lines[i])) break;
      const m = lines[i].match(/^\s*[-*]\s+(.+)/);
      if (m) {
        flush();
        cur = m[1];
      } else if (cur !== null && lines[i].trim() && !/^\s*```/.test(lines[i])) {
        cur += " " + lines[i].trim();
      }
    }
    flush();
    if (sugg.length) out.suggestions = sugg;
  }
  return out;
}

interface Props {
  setHealth: (h: { text: string; tone: "ok" | "warn" | "err" | "neutral" } | undefined) => void;
  /** Test-block catalog + selection are owned by App so the sidebar dropdown
   *  and this detail pane stay in sync. */
  blocks: SimBlock[];
  selected: string;
}

const STATUS_BADGE: Record<string, string> = {
  implemented: "bg-ok/10 text-ok border-ok/30",
  planned: "bg-warn/10 text-warn border-warn/30",
  not_simulatable: "bg-ink-100 text-ink-500 border-edge",
};

const resultKey = (block: string, simType: string) => `${block}:${simType}`;

const LS_RESULTS = "test1.sim.results";
const LS_INTERP = "test1.sim.interp";

function loadLS<T>(key: string): T | null {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : null;
  } catch {
    return null;
  }
}

export function Simulation({ setHealth, blocks, selected }: Props) {
  // Rehydrate results + settled interpretations from localStorage so the tab
  // survives navigation away and full page refreshes.
  const [results, setResults] = useState<Record<string, SimResult>>(
    () => loadLS<Record<string, SimResult>>(LS_RESULTS) ?? {},
  );
  const [running, setRunning] = useState<string | null>(null);
  const [logged, setLogged] = useState<Record<string, boolean>>({});
  const [interp, setInterp] = useState<Record<string, Interp>>(() => {
    const saved = loadLS<Record<string, Interp>>(LS_INTERP) ?? {};
    for (const k in saved) { saved[k].running = false; saved[k].lines = []; saved[k].phase = "done"; }
    return saved;
  });

  // Persist results + interpretations (without the transient stream lines).
  useEffect(() => {
    try { localStorage.setItem(LS_RESULTS, JSON.stringify(results)); } catch { /* quota */ }
  }, [results]);
  useEffect(() => {
    try {
      const strip: Record<string, Partial<Interp>> = {};
      for (const k in interp) {
        const v = interp[k];
        strip[k] = { running: false, lines: [], verdict: v.verdict, margin: v.margin,
                     clarify: v.clarify, suggestions: v.suggestions };
      }
      localStorage.setItem(LS_INTERP, JSON.stringify(strip));
    } catch { /* quota */ }
  }, [interp]);

  const block = blocks.find((b) => b.id === selected);

  const run = useCallback(
    async (simType: string) => {
      if (!block) return;
      const key = resultKey(block.id, simType);
      setRunning(key);
      setHealth({ text: `simulating ${simType}…`, tone: "neutral" });
      const appendLine = (line: string) =>
        setInterp((prev) => ({
          ...prev,
          [key]: { ...(prev[key] ?? { running: true, lines: [] }), lines: [...(prev[key]?.lines ?? []), line] },
        }));

      try {
        // STAGE 1 — context + params (cache-gated). The agent reads datasheets
        // + requirements + the current design and determines the operating
        // point BEFORE the sim runs. Skipped when the cached scenario is fresh.
        setInterp((prev) => ({ ...prev, [key]: { running: true, lines: [], phase: "setup" } }));
        setHealth({ text: `${simType}: reading datasheets…`, tone: "neutral" });
        const setup = await api.simSetup(block.id, simType);
        setInterp((prev) => ({ ...prev, [key]: { ...(prev[key]!), setupFresh: !!setup.fresh } }));
        if (!setup.fresh && setup.run_id) {
          await new Promise<void>((resolve) => {
            subscribeAgent(setup.run_id!, appendLine, () => resolve());
          });
        }

        // STAGE 2 — simulate, now using the determined operating point.
        setInterp((prev) => ({ ...prev, [key]: { ...(prev[key]!), phase: "sim" } }));
        setHealth({ text: `simulating ${simType}…`, tone: "neutral" });
        const res = await api.simRun(block.id, simType);
        setResults((prev) => ({ ...prev, [key]: res }));
        setHealth({
          text: res.ok ? `${simType}: PASS` : `${simType}: FAIL`,
          tone: res.ok ? "ok" : "err",
        });

        // STAGE 3 — interpret vs spec (+ iterate is handled agent-side).
        setInterp((prev) => ({ ...prev, [key]: { ...(prev[key]!), phase: "interpret" } }));
        try {
          const { run_id } = await api.simInterpret(block.id, simType);
          subscribeAgent(
            run_id,
            appendLine,
            (status) => {
              setInterp((prev) => ({
                ...prev,
                [key]: {
                  ...(prev[key] ?? { running: false, lines: [] }),
                  running: false,
                  phase: "done",
                  ...parseVerdict(status.text ?? (prev[key]?.lines ?? []).join("\n")),
                },
              }));
              // The agent may have re-simmed (bounded iterate) with a corrected
              // scenario — refresh the structured result to the final scenario.
              api.simRun(block.id, simType)
                .then((res) => setResults((prev) => ({ ...prev, [key]: res })))
                .catch(() => {});
            },
          );
        } catch {
          setInterp((prev) => ({
            ...prev,
            [key]: { ...(prev[key] ?? { lines: [] }), running: false, phase: "done", lines: [...(prev[key]?.lines ?? []), "interpreter unavailable"] },
          }));
        }
      } catch (e) {
        setHealth({ text: "sim error", tone: "err" });
        setInterp((prev) => ({ ...prev, [key]: { ...(prev[key] ?? { lines: [] }), running: false, phase: "done" } }));
      } finally {
        setRunning(null);
      }
    },
    [block, setHealth],
  );

  const toggleSuggestion = useCallback((key: string, idx: number) => {
    setInterp((prev) => {
      const it = prev[key];
      if (!it?.suggestions) return prev;
      const suggestions = it.suggestions.map((s, i) =>
        i === idx ? { ...s, checked: !s.checked } : s);
      return { ...prev, [key]: { ...it, suggestions } };
    });
  }, []);

  // The changelog button: push the SELECTED suggested changes. If a result has
  // no suggestions, fall back to logging the result summary so the button is
  // still useful for clean (MEETS_SPEC) results.
  const pushToChangelog = useCallback(
    async (res: SimResult) => {
      const key = resultKey(res.block, res.sim_type);
      const sel = (interp[key]?.suggestions ?? []).filter((s) => s.checked);
      try {
        if (sel.length > 0) {
          for (const s of sel) {
            await api.changelogAdd(`[sim ${res.block}/${res.sim_type}] ${s.text}`);
          }
        } else {
          const verdict = res.ok ? "PASS" : "FAIL";
          await api.changelogAdd(
            `Sim ${verdict}: ${res.block} / ${res.sim_type}. Criterion: ${res.pass_criterion ?? "n/a"}.`,
          );
        }
        setLogged((prev) => ({ ...prev, [key]: true }));
      } catch {
        // ignore
      }
    },
    [interp],
  );

  return (
    <div className="h-full overflow-auto thin-scroll min-h-0">
      {!block ? (
        <div className="px-6 py-5 text-sm text-ink-500">
          {blocks.length ? "Select a test block from the sidebar." : "Loading blocks…"}
        </div>
      ) : (
        <div className="px-6 py-5 max-w-[1100px]">
          <div className="flex items-center gap-2">
            <div className="text-[11px] tracking-wide uppercase text-ink-500">
              Phase 4 · Simulation
            </div>
            <span className={"text-[10px] px-1.5 py-0.5 rounded border " + (STATUS_BADGE[block.status] ?? STATUS_BADGE.not_simulatable)}>
              {block.status}
            </span>
            <span className="text-[10px] text-ink-500 font-mono">{block.sheet}</span>
          </div>
          <h2 className="text-[18px] font-semibold text-ink-900 mt-0.5">{block.title}</h2>
          <p className="text-sm text-ink-700 mt-1.5 leading-relaxed">{block.description}</p>

            {block.models_needed.length > 0 && (
              <div className="mt-2 text-[11px] text-ink-500">
                models: {block.models_needed.map((m) => (
                  <span key={m} className="font-mono text-ink-700 mr-1.5">{m}</span>
                ))}
              </div>
            )}

            {block.datasheets.length > 0 && (
              <div className="mt-3">
                <div className="text-[11px] uppercase tracking-wide text-ink-500 mb-1.5">
                  Datasheets · read by the interpreter on Run
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {block.datasheets.map((d) => (
                    <a
                      key={d.mpn}
                      href={api.datasheetUrl(d.mpn)}
                      target="_blank"
                      rel="noreferrer"
                      title={`${d.file} — open PDF`}
                      className="h-7 px-2.5 inline-flex items-center gap-1.5 rounded-md border border-edge bg-white text-ink-700 hover:border-ink-300 hover:text-ink-900 text-xs"
                    >
                      <I.Folder size={13} />
                      <span className="font-mono">{d.mpn}</span>
                    </a>
                  ))}
                </div>
              </div>
            )}

            {block.status === "not_simulatable" ? (
              <div className="mt-5 rounded-md border border-edge bg-rail px-4 py-6 text-sm text-ink-500">
                This block isn't simulatable — {block.description}
              </div>
            ) : (
              <div className="mt-5 space-y-3">
                {block.sim_types.map((st) => {
                  const key = resultKey(block.id, st.type);
                  const res = results[key];
                  const isRunning = running === key;
                  const planned = st.status === "planned";
                  return (
                    <div key={st.type} className={"rounded-md border bg-white " + (planned ? "border-edge/70 border-dashed" : "border-edge")}>
                      <div className="px-4 py-3 flex items-start gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-ink-900 font-mono">{st.type}</span>
                            {planned && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded border border-warn/30 bg-warn/10 text-warn">planned</span>
                            )}
                            {res && !planned && <Verdict ok={res.ok} status={res.status} />}
                          </div>
                          <div className="text-xs text-ink-700 mt-1">{st.rationale}</div>
                          <div className="text-[11px] text-ink-500 mt-1">
                            <span className="uppercase tracking-wide">pass</span> · {st.pass}
                          </div>
                          {planned && st.defer_reason && (
                            <div className="text-[11px] text-warn/90 mt-1.5 italic">deferred: {st.defer_reason}</div>
                          )}
                        </div>
                        {!planned && (
                          <button
                            onClick={() => run(st.type)}
                            disabled={isRunning || block.status !== "implemented"}
                            className="h-8 px-3 inline-flex items-center gap-1.5 rounded-md bg-ink-900 text-white text-xs font-medium hover:bg-black disabled:opacity-40 shrink-0"
                          >
                            <I.Play size={13} /> {isRunning ? "running…" : "Run"}
                          </button>
                        )}
                      </div>

                      {res && (
                        <div className="border-t border-edge px-4 py-3">
                          <WorkflowSteps res={res} it={interp[key]} />
                          {res.status !== "ran" ? (
                            <div className="text-xs text-ink-500">{res.message}</div>
                          ) : (
                            <SimReport res={res} />
                          )}

                          {interp[key] && <InterpPanel block={block} it={interp[key]} />}

                          {(() => {
                            const sugg = interp[key]?.suggestions ?? [];
                            const nSel = sugg.filter((s) => s.checked).length;
                            return (
                              <>
                                {sugg.length > 0 && (
                                  <div className="mt-3">
                                    <div className="text-[11px] uppercase tracking-wide text-ink-500 mb-1.5">
                                      Suggested changes — check the ones to send
                                    </div>
                                    <div className="space-y-1">
                                      {sugg.map((s, i) => (
                                        <label key={i} className="flex items-start gap-2 text-xs text-ink-700 cursor-pointer">
                                          <input
                                            type="checkbox"
                                            checked={s.checked}
                                            onChange={() => toggleSuggestion(key, i)}
                                            className="mt-0.5 accent-ink-900"
                                          />
                                          <span>{s.text}</span>
                                        </label>
                                      ))}
                                    </div>
                                  </div>
                                )}
                                <div className="mt-3 flex items-center gap-2">
                                  <button
                                    onClick={() => pushToChangelog(res)}
                                    disabled={logged[key] || (sugg.length > 0 && nSel === 0)}
                                    className="h-7 px-2.5 inline-flex items-center gap-1.5 rounded-md border border-edge text-ink-700 text-[11px] hover:border-ink-300 disabled:opacity-50"
                                  >
                                    <I.Plus size={12} />
                                    {logged[key]
                                      ? "added to changelog"
                                      : sugg.length > 0
                                        ? `Add ${nSel} selected to changelog`
                                        : "Add result to changelog"}
                                  </button>
                                </div>
                              </>
                            );
                          })()}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
  );
}

function ThinkingChecklist({ block, it }: { block: SimBlock; it: Interp }) {
  // What the agent is looking at, derived from its streamed Read/Write calls.
  const items = [
    { label: "Design requirements", hit: (l: string) => /design_requirements/i.test(l) },
    { label: "Current design", hit: (l: string) => !!block.sheet && l.toLowerCase().includes(block.sheet.toLowerCase()) },
    { label: "Parameter cache", hit: (l: string) => /datasheet_params/i.test(l) },
    ...block.datasheets.map((d) => ({
      label: `${d.mpn} datasheet`,
      hit: (l: string) =>
        l.toLowerCase().includes(d.file.toLowerCase()) ||
        l.toLowerCase().includes(`/${d.mpn.toLowerCase()}/`),
    })),
  ];
  return (
    <ul className="mt-2 space-y-0.5">
      {items.map((item) => {
        const read = it.lines.some((l) => item.hit(l));
        const cached = !read && !it.running;
        return (
          <li key={item.label} className="flex items-center gap-1.5 text-[11px]">
            {read ? (
              <I.Check size={11} className="text-ok" />
            ) : cached ? (
              <I.Check size={11} className="text-ink-300" />
            ) : (
              <span className="w-[11px] h-[11px] rounded-full border border-edge inline-block" />
            )}
            <span className={read ? "text-ink-700" : "text-ink-400"}>
              {item.label}{cached ? " · cached" : ""}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function InterpPanel({ block, it }: { block: SimBlock; it: Interp }) {
  const tone =
    it.verdict === "MEETS_SPEC" ? "border-ok/30 bg-ok/[0.05] text-ok" :
    it.verdict === "OUT_OF_SPEC" ? "border-err/30 bg-err/[0.05] text-err" :
    it.verdict === "NEEDS_CLARIFICATION" ? "border-warn/30 bg-warn/[0.05] text-warn" :
    "border-edge bg-rail text-ink-700";
  return (
    <div className="mt-3 rounded-md border border-edge bg-rail/40 p-2.5">
      <div className="flex items-center gap-2">
        <span className="text-[11px] uppercase tracking-wide text-ink-500">
          AI interpretation · vs datasheets + requirements
        </span>
        {it.running && (
          <span className="w-3 h-3 rounded-full border-2 border-ink-300 border-t-ink-700 animate-spin" />
        )}
      </div>
      {/* While running: concise checklist of what it's reading. */}
      {!it.verdict && <ThinkingChecklist block={block} it={it} />}
      {it.verdict && (
        <div className={"mt-2 inline-flex items-center gap-2 rounded border px-2 py-1 text-xs font-medium " + tone}>
          {it.verdict.replace(/_/g, " ")}
        </div>
      )}
      {it.margin && <div className="text-xs text-ink-700 mt-1.5">{it.margin}</div>}
      {it.iterations && (
        <div className="text-[11px] text-ink-500 mt-1.5 inline-flex items-center gap-1">
          <I.Refresh size={11} /> re-simmed: {it.iterations}
        </div>
      )}
      {it.clarify && <div className="text-xs text-warn mt-1.5">clarify: {it.clarify}</div>}
    </div>
  );
}

function Verdict({ ok, status }: { ok: boolean; status: string }) {
  if (status !== "ran") {
    return <span className="text-[10px] px-1.5 py-0.5 rounded border border-warn/30 bg-warn/10 text-warn">{status}</span>;
  }
  return ok ? (
    <span className="text-[10px] px-1.5 py-0.5 rounded border border-ok/30 bg-ok/10 text-ok inline-flex items-center gap-1">
      <I.Check size={11} /> PASS
    </span>
  ) : (
    <span className="text-[10px] px-1.5 py-0.5 rounded border border-err/30 bg-err/10 text-err inline-flex items-center gap-1">
      <I.X size={11} /> FAIL
    </span>
  );
}

function SimReport({ res }: { res: SimResult }) {
  const a = (res.analysis ?? {}) as Record<string, unknown>;
  const rails = a.rails as Array<Record<string, unknown>> | undefined;
  const setpoints = a.setpoints as Array<Record<string, unknown>> | undefined;
  // Scalar metrics: everything except structural keys.
  const metrics = Object.entries(a).filter(
    ([k]) => !["check", "overall", "rails", "setpoints"].includes(k),
  );

  return (
    <div className="space-y-3">
      {res.plot.length > 0 && (
        <WaveChart series={res.plot} xAxis={res.x_axis} yLabel={res.y_label} />
      )}

      {rails && (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-ink-500 text-left">
              <th className="font-medium py-1">rail</th>
              <th className="font-medium py-1">expected</th>
              <th className="font-medium py-1">measured</th>
              <th className="font-medium py-1">status</th>
            </tr>
          </thead>
          <tbody className="font-mono text-ink-700">
            {rails.map((r, i) => (
              <tr key={i} className="border-t border-edge/60">
                <td className="py-1">{String(r.rail)}</td>
                <td className="py-1">{fmt(r.expected_V)} V</td>
                <td className="py-1">{fmt(r.measured_V)} V</td>
                <td className={"py-1 " + (r.status === "OK" ? "text-ok" : "text-err")}>{String(r.status)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {setpoints && (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-ink-500 text-left">
              <th className="font-medium py-1">setpoint</th>
              <th className="font-medium py-1">measured</th>
              <th className="font-medium py-1">headroom</th>
              <th className="font-medium py-1">status</th>
            </tr>
          </thead>
          <tbody className="font-mono text-ink-700">
            {setpoints.map((r, i) => (
              <tr key={i} className="border-t border-edge/60">
                <td className="py-1">{fmt(r.setpoint_V)} V</td>
                <td className="py-1">{fmt(r.measured_V)} V</td>
                <td className="py-1">{fmt(r.headroom_V)} V</td>
                <td className={"py-1 " + (r.status === "OK" ? "text-ok" : "text-err")}>{String(r.status)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {metrics.length > 0 && (
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs font-mono">
          {metrics.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-2 border-b border-edge/40 py-0.5">
              <span className="text-ink-500">{k}</span>
              <span className={metricTone(k, v)}>{fmtVal(v)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function metricTone(k: string, v: unknown): string {
  if (k.endsWith("_status") || k === "sequence_ok") {
    if (v === "OK" || v === true) return "text-ok";
    if (v === "FAIL" || v === false) return "text-err";
  }
  return "text-ink-900";
}

function fmt(v: unknown): string {
  return typeof v === "number" ? v.toFixed(4) : String(v);
}

function fmtVal(v: unknown): string {
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") {
    if (v !== 0 && (Math.abs(v) < 1e-3 || Math.abs(v) >= 1e5)) return v.toExponential(3);
    return v.toFixed(4);
  }
  return String(v);
}

// ---------------------------------------------------------------------------
// Lightweight SVG waveform chart — no chart library. All signals are voltages
// (or volt-scaled controls), so they share one y-axis.

const PALETTE = ["#2563eb", "#16a34a", "#db2777", "#d97706", "#7c3aed", "#0891b2"];

function WaveChart({ series, xAxis, yLabel }: {
  series: SimSeries[];
  xAxis?: SimXAxis | null;
  yLabel?: string;
}) {
  const W = 820, H = 300, padL = 56, padR = 12, padT = 12, padB = 36;
  const ax = xAxis ?? { label: "time", unit: "ms", scale: 1e3, log: false };
  const log = ax.log;
  // For a log axis we plot in log10 of the raw x (which is already scaled to
  // the axis unit by `scale`). Guard against non-positive values.
  const fx = (t: number) => (log ? Math.log10(Math.max(t, 1e-12)) : t);

  const { tMin, tMax, vMin, vMax } = useMemo(() => {
    let tMin = Infinity, tMax = -Infinity, vMin = Infinity, vMax = -Infinity;
    for (const s of series) {
      for (const t of s.t) { const x = fx(t); if (x < tMin) tMin = x; if (x > tMax) tMax = x; }
      for (const v of s.v) { if (v < vMin) vMin = v; if (v > vMax) vMax = v; }
    }
    if (!isFinite(tMin)) { tMin = 0; tMax = 1; }
    if (!isFinite(vMin)) { vMin = 0; vMax = 1; }
    const pad = (vMax - vMin) * 0.08 || 0.1;
    return { tMin, tMax, vMin: vMin - pad, vMax: vMax + pad };
  }, [series, log]);

  const sx = (t: number) => padL + ((fx(t) - tMin) / (tMax - tMin || 1)) * (W - padL - padR);
  const sy = (v: number) => padT + (1 - (v - vMin) / (vMax - vMin || 1)) * (H - padT - padB);
  // Format an x tick: invert log, apply unit scale.
  const xtick = (frac: number) => {
    const raw = tMin + frac * (tMax - tMin);
    const val = (log ? Math.pow(10, raw) : raw) * ax.scale;
    if (log) return val >= 1e6 ? `${(val / 1e6).toFixed(0)}M` : val >= 1e3 ? `${(val / 1e3).toFixed(0)}k` : val.toFixed(0);
    return val.toFixed(2);
  };

  const yTicks = 4, xTicks = 5;

  return (
    <div className="rounded-md border border-edge bg-white p-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
        {/* y gridlines + labels */}
        {Array.from({ length: yTicks + 1 }, (_, i) => {
          const v = vMin + (i / yTicks) * (vMax - vMin);
          const y = sy(v);
          return (
            <g key={"y" + i}>
              <line x1={padL} y1={y} x2={W - padR} y2={y} stroke="#eef0f3" strokeWidth={1} />
              <text x={padL - 6} y={y + 3} textAnchor="end" fontSize={10} fill="#8b929e">
                {v.toFixed(2)}
              </text>
            </g>
          );
        })}
        {/* x gridlines + labels */}
        {Array.from({ length: xTicks + 1 }, (_, i) => {
          const x = padL + (i / xTicks) * (W - padL - padR);
          return (
            <g key={"x" + i}>
              <line x1={x} y1={padT} x2={x} y2={H - padB} stroke="#f4f5f7" strokeWidth={1} />
              <text x={x} y={H - padB + 14} textAnchor="middle" fontSize={10} fill="#8b929e">
                {xtick(i / xTicks)}
              </text>
            </g>
          );
        })}
        <text x={W / 2} y={H - 4} textAnchor="middle" fontSize={10} fill="#8b929e">
          {ax.label} ({ax.unit}){log ? ", log" : ""}
        </text>
        <text x={12} y={padT + 4} fontSize={10} fill="#8b929e">{yLabel ?? "volts"}</text>

        {/* polylines */}
        {series.map((s, i) => {
          const pts = s.t.map((t, j) => `${sx(t).toFixed(1)},${sy(s.v[j]).toFixed(1)}`).join(" ");
          return <polyline key={s.signal} points={pts} fill="none" stroke={PALETTE[i % PALETTE.length]} strokeWidth={1.5} />;
        })}
      </svg>
      {/* legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 px-2 pb-1">
        {series.map((s, i) => (
          <div key={s.signal} className="flex items-center gap-1.5 text-[11px] text-ink-700 font-mono">
            <span className="inline-block w-3 h-[2px]" style={{ background: PALETTE[i % PALETTE.length] }} />
            {s.signal}
          </div>
        ))}
      </div>
    </div>
  );
}
