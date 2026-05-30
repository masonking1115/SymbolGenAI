import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, subscribeAgent } from "../api";
import { I } from "../components/Icon";
import type { AgentModelConfig, ModelChoice, SimBlock, SimRequirements, SimResult, SimSeries, SimXAxis } from "../types";

type StepState = "pending" | "active" | "pass" | "fail" | "warn" | "done";

// Derive the workflow-stage states from the phase + the ngspice result + the
// agent's streamed tool calls. The flow is context-first:
//   read context → apply params → simulate → interpret vs spec
function workflowSteps(res: SimResult | undefined, it: Interp | undefined, isRunning: boolean):
  { label: string; hint: string; state: StepState; actor: string }[] {
  const phase = it?.phase;
  const ord = { setup: 0, sim: 1, interpret: 2, done: 3 } as const;
  const p = phase ? ord[phase] : -1;
  const verdict = it?.verdict;
  const fresh = it?.setupFresh;
  // A spinner means "happening right now" — it must require a LIVE run. On
  // reload, persisted state must never read as active (that produced phantom
  // "running" sims with no result). `active` is only ever shown when isRunning.
  const liveActive = (cond: boolean): StepState => (isRunning && cond ? "active" : "pending");
  // When the feedback loop starts a NEW pass, the run loop walks the phase back
  // to "setup". The previous pass's `res`/`verdict` still linger in state, so a
  // downstream step must NOT show last pass's outcome while this pass is re-running
  // upstream of it — each step resets to pending/active until it re-completes.
  // (`reran` = actively running and still upstream of that step's stage.)
  const rerunningBefore = (stage: number): boolean => isRunning && p >= 0 && p < stage;

  // 1 + 2: context read + param apply both happen in the setup stage.
  const setupState: StepState =
    p < 0 ? "pending" : p === 0 ? liveActive(true) : "done";
  const ctxHint = setupState === "done" ? (fresh ? "from cache" : "read")
    : setupState === "active" ? "reading…" : "";
  const parHint = setupState === "done" ? (fresh ? "from cache" : "applied")
    : setupState === "active" ? "…" : "";

  // 3: simulate. While a new pass is re-running setup, don't keep showing the
  // prior pass's pass/fail — reset to active/pending for this pass.
  const sim: StepState = rerunningBefore(ord.sim)
    ? liveActive(false) /* pending: this pass hasn't reached Simulate yet */
    : res
      ? (res.status !== "ran" ? "done" : res.ok ? "pass" : "fail")
      : liveActive(p >= 1);

  // 4: interpret. Likewise, a lingering verdict from the prior pass must not show
  // while this pass is still upstream of interpret.
  let interp: StepState = "pending";
  if (rerunningBefore(ord.interpret)) interp = liveActive(false);
  else if (verdict) interp = verdict === "MEETS_SPEC" ? "pass" : verdict === "OUT_OF_SPEC" ? "fail" : "warn";
  else if (phase === "interpret") interp = liveActive(true);
  else if (phase === "done") interp = "done";

  return [
    { label: "Read context", hint: ctxHint, state: setupState, actor: "claude -p" },
    { label: "Apply params", hint: parHint, state: setupState, actor: "claude -p" },
    { label: "Simulate", hint: "ngspice", state: sim, actor: "ngspice" },
    { label: "Interpret vs spec", hint: verdict ? verdict.replace(/_/g, " ").toLowerCase() : "", state: interp, actor: "claude -p" },
  ];
}

function StepIcon({ state }: { state: StepState }) {
  const base = "w-5 h-5 rounded-full grid place-items-center shrink-0";
  // A finished step always reads the SAME green check, whether it merely
  // completed ("done") or passed a spec gate ("pass") — uniform completion
  // color across the loop. Only failure (red) and in-progress (spinner) differ.
  if (state === "pass" || state === "done") return <span className={base + " bg-ok/15 text-ok"}><I.Check size={12} /></span>;
  if (state === "fail") return <span className={base + " bg-err/15 text-err"}><I.X size={12} /></span>;
  if (state === "warn") return <span className={base + " bg-warn/15 text-warn"}><I.Dot size={12} /></span>;
  if (state === "active") return (
    <span className={base + " bg-ink-100"}>
      <span className="w-3 h-3 rounded-full border-2 border-ink-300 border-t-ink-700 animate-spin" />
    </span>
  );
  return <span className={base + " border border-edge text-ink-300"}><I.Dot size={10} /></span>;
}

// Which pass the workflow is on. Prefer an explicit `pass` from the run loop;
// otherwise infer from the re-sim count the verdict reported (a second pass only
// exists once at least one re-sim happened). Clamped to the hard loop cap.
function currentPass(it?: Interp): number {
  if (it?.pass && it.pass > 0) return Math.min(it.pass, MAX_LOOPS);
  const m = it?.iterations?.match(/\d+/);   // "2 re-sims, changed primary_vout"
  const resims = m ? parseInt(m[0], 10) : 0;
  return Math.min(1 + (resims > 0 ? Math.min(resims, MAX_LOOPS - 1) : 0), MAX_LOOPS);
}

function WorkflowSteps({ res, it, isRunning }: { res?: SimResult; it?: Interp; isRunning: boolean }) {
  const steps = workflowSteps(res, it, isRunning);
  const pass = currentPass(it);
  return (
    <div className="flex items-center gap-1.5 mb-3 pb-3 border-b border-edge/60">
      {/* Loop badge: only when the feedback loop has gone past the first pass.
          The reviewer's feedback re-tunes setup and the sequence re-runs, up to
          MAX_LOOPS. */}
      {pass > 1 && (
        <span
          className={
            "shrink-0 inline-flex items-center gap-1 text-[9.5px] font-mono px-1.5 py-0.5 rounded-full border " +
            (isRunning
              ? "border-violet-300 bg-violet-100 text-violet-700"
              : "border-edge bg-ink-100 text-ink-500")
          }
          title={`reviewer feedback re-tuned the setup; pass ${pass} of ${MAX_LOOPS}`}
        >
          <I.Refresh size={9} className={isRunning ? "animate-spin" : ""} />
          loop {pass}/{MAX_LOOPS}
        </span>
      )}
      {steps.map((s, i) => (
        <Fragment key={s.label}>
          <div className="flex items-center gap-1.5">
            <StepIcon state={s.state} />
            <div className="leading-tight">
              <div className="text-[11px] text-ink-700 whitespace-nowrap flex items-center gap-1">
                {s.label}
                {/* actor badge: which engine runs this stage (AI agent vs ngspice) */}
                <span className={
                  "text-[8.5px] px-1 py-px rounded font-mono " +
                  (s.state === "active"
                    ? (s.actor === "ngspice" ? "bg-amber-100 text-amber-700" : "bg-violet-100 text-violet-700")
                    : "bg-ink-100 text-ink-400")
                }>
                  {s.actor}
                </span>
              </div>
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
  interpretError?: string;  // set when the AI interpret step ended without a
  //                           verdict (stream dropped / timed out / unavailable)
  // Outer feedback loop: when a pass comes up incomplete, the reviewer's
  // feedback is handed back to the setup agent which re-tunes parameters and the
  // whole setup→sim→interpret sequence re-runs (hard-capped at MAX_LOOPS). `pass`
  // is the 1-based current pass; the workflow row shows a "loop N/MAX" badge once
  // it exceeds 1.
  pass?: number;
}

const MAX_LOOPS = 3;

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
  /** Re-fetch the block catalog after a model is generated/updated (its
   *  has_model / model_status / sim_types change). */
  onBlocksChanged?: () => void;
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

export function Simulation({ setHealth, blocks, selected, onBlocksChanged }: Props) {
  // Rehydrate results + settled interpretations from localStorage so the tab
  // survives navigation away and full page refreshes.
  const [results, setResults] = useState<Record<string, SimResult>>(
    () => loadLS<Record<string, SimResult>>(LS_RESULTS) ?? {},
  );
  const [running, setRunning] = useState<string | null>(null);
  // In-flight run control for the Cancel button: the key being run, the live
  // agent's run_id (so we can POST cancel), and a cancelled flag the sequential
  // run() loop checks between stages so it bails out promptly.
  const runCtl = useRef<{ key: string; runId: string | null; cancelled: boolean } | null>(null);
  const [logged, setLogged] = useState<Record<string, boolean>>({});
  // Mirror of `logged` for the changelog-status poller (avoids re-arming the
  // interval whenever `logged` changes).
  const loggedRef = useRef<Record<string, boolean>>({});
  useEffect(() => { loggedRef.current = logged; }, [logged]);
  // Lifecycle of sim-originated changelog items, keyed by "<block>:<sim_type>":
  //   "pending"  → added to the changelog, not yet applied (still queued)
  //   "applied"  → the apply pass implemented it (no longer queued)
  // Derived by polling the live changelog (still-queued sim items for this
  // block/sim = pending) so a Run-suggestion reflects its real state.
  const [clStatus, setClStatus] = useState<Record<string, "pending" | "applied">>({});
  const [reqOpen, setReqOpen] = useState(false);
  const [modelsOpen, setModelsOpen] = useState(false);
  // Pass criteria edited in the Requirements panel are also shown (read-only) on
  // each sim_type card; keep a per-(block,sim) override so the card reflects an
  // edit immediately without needing the parent to re-fetch the blocks catalog.
  const [passOverride, setPassOverride] = useState<Record<string, string>>({});
  const [interp, setInterp] = useState<Record<string, Interp>>(() => {
    const saved = loadLS<Record<string, Interp>>(LS_INTERP) ?? {};
    const out: Record<string, Interp> = {};
    for (const k in saved) {
      const v = saved[k];
      // Only rehydrate entries that reached a real terminal state (a verdict).
      // A half-saved in-progress entry must NOT come back as a phantom card /
      // spinner on reload.
      if (!v.verdict) continue;
      out[k] = { ...v, running: false, lines: [], phase: "done", interpretError: undefined };
    }
    return out;
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
        // Persist ONLY completed interpretations (have a verdict). Skipping
        // in-progress / aborted entries keeps stale half-states from
        // rehydrating as phantom "running" cards.
        if (!v.verdict) continue;
        strip[k] = { running: false, lines: [], verdict: v.verdict, margin: v.margin,
                     clarify: v.clarify, suggestions: v.suggestions,
                     // keep how many passes the loop took so the "loop N/MAX"
                     // badge survives a reload
                     iterations: v.iterations, pass: v.pass };
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
      runCtl.current = { key, runId: null, cancelled: false };
      const wasCancelled = () => runCtl.current?.cancelled ?? false;
      const markCancelled = (note: string) =>
        setInterp((prev) => ({
          ...prev,
          [key]: { ...(prev[key] ?? { lines: [] }), running: false, phase: "done", interpretError: note },
        }));
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
          if (runCtl.current) runCtl.current.runId = setup.run_id;   // cancel target
          await new Promise<void>((resolve) => {
            subscribeAgent(setup.run_id!, appendLine, () => resolve());
          });
        }
        if (wasCancelled()) { markCancelled("cancelled before simulating"); setHealth({ text: "sim cancelled", tone: "neutral" }); return; }

        // STAGE 2 — simulate, now using the determined operating point.
        setInterp((prev) => ({ ...prev, [key]: { ...(prev[key]!), phase: "sim" } }));
        setHealth({ text: `simulating ${simType}…`, tone: "neutral" });
        const res = await api.simRun(block.id, simType);
        setResults((prev) => ({ ...prev, [key]: res }));
        setHealth({
          text: res.ok ? `${simType}: PASS` : `${simType}: FAIL`,
          tone: res.ok ? "ok" : "err",
        });
        if (wasCancelled()) { markCancelled("cancelled — interpretation skipped (sim result above is valid)"); return; }

        // STAGE 3 — interpret vs spec (+ iterate is handled agent-side).
        // The sim RESULT already stands (chart/table above); interpret is the AI
        // judgement layer. If its live stream drops (e.g. backend restart),
        // stalls, or is CANCELLED, we MUST still reach a terminal state so the
        // step stops spinning — the result is valid regardless.
        setInterp((prev) => ({ ...prev, [key]: { ...(prev[key]!), phase: "interpret" } }));
        try {
          const { run_id } = await api.simInterpret(block.id, simType);
          if (runCtl.current) runCtl.current.runId = run_id;          // cancel target
          // If a cancel landed in the gap before the run_id came back, kill it now.
          if (wasCancelled()) api.cancelAgent(run_id).catch(() => {});
          let settled = false;
          const finishInterpret = (text: string | undefined, err?: string) => {
            if (settled) return;
            settled = true;
            clearTimeout(watchdog);
            const parsed = text ? parseVerdict(text) : {};
            const hasVerdict = !!parsed.verdict;
            setInterp((prev) => ({
              ...prev,
              [key]: {
                ...(prev[key] ?? { running: false, lines: [] }),
                running: false,
                phase: "done",
                ...parsed,
                interpretError: hasVerdict ? undefined : (err ?? "interpretation unavailable"),
              },
            }));
            if (hasVerdict) {
              // The agent may have re-simmed (bounded iterate) with a corrected
              // scenario — refresh the structured result to the final scenario.
              api.simRun(block.id, simType)
                .then((res) => setResults((prev) => ({ ...prev, [key]: res })))
                .catch(() => {});
            }
          };
          // Watchdog: if neither a verdict nor a stream-close arrives in time,
          // stop waiting. Interpret now works from the inlined cached params (it
          // shouldn't read datasheets — the slow path), so a healthy pass is well
          // under this; a longer wait means something stalled. Generous margin so
          // a legitimately-thorough verdict (or up to 3 bounded re-sims) isn't cut
          // off prematurely.
          const watchdog = setTimeout(
            () => finishInterpret(undefined, "interpretation timed out — the sim result above is valid"),
            240_000,
          );
          subscribeAgent(
            run_id,
            appendLine,
            (status) => {
              const lines = (interp[key]?.lines ?? []).join("\n");
              if (status.status === "cancelled") {
                finishInterpret(undefined, "cancelled — interpretation stopped (sim result above is valid)");
              } else if (status.status === "stream_error") {
                finishInterpret(status.text ?? lines,
                  "interpretation connection lost — the sim result above is valid");
              } else {
                finishInterpret(status.text ?? lines);
              }
            },
          );
        } catch {
          setInterp((prev) => ({
            ...prev,
            [key]: { ...(prev[key] ?? { lines: [] }), running: false, phase: "done",
                     interpretError: "interpretation unavailable — the sim result above is valid" },
          }));
        }
      } catch (e) {
        if (wasCancelled()) { markCancelled("sim cancelled"); setHealth({ text: "sim cancelled", tone: "neutral" }); }
        else {
          setHealth({ text: "sim error", tone: "err" });
          setInterp((prev) => ({ ...prev, [key]: { ...(prev[key] ?? { lines: [] }), running: false, phase: "done" } }));
        }
      } finally {
        if (runCtl.current?.key === key) runCtl.current = null;
        setRunning(null);
      }
    },
    [block, setHealth],
  );

  // Cancel the in-flight sim: terminate the live agent (setup or interpret) and
  // flag the run loop so it bails between stages. ngspice itself is a ~1s
  // synchronous call and isn't interrupted, but the long agent stages are.
  const cancel = useCallback(() => {
    const ctl = runCtl.current;
    if (!ctl) return;
    ctl.cancelled = true;
    if (ctl.runId) api.cancelAgent(ctl.runId).catch(() => {});
    setHealth({ text: "cancelling…", tone: "neutral" });
  }, [setHealth]);

  // Wipe the DISPLAYED results for a block (all its sim_type keys) so a
  // cache-clear visibly returns the tab to "not run yet" — no stale chart or
  // verdict lingering against state that's just been cleared. Drops the chart
  // (results), the interpretation/workflow (interp), and the changelog flag
  // (logged); the next Run re-derives from scratch. Keyed by "<block>:<sim>".
  const resetBlockDisplay = useCallback((blockId: string) => {
    const mine = (k: string) => k.startsWith(`${blockId}:`);
    const prune = <T,>(m: Record<string, T>) =>
      Object.fromEntries(Object.entries(m).filter(([k]) => !mine(k)));
    setResults((prev) => prune(prev));
    setInterp((prev) => prune(prev));
    setLogged((prev) => prune(prev));
    setClStatus((prev) => prune(prev));
  }, []);

  // Derive each sim's changelog lifecycle from the live changelog. A badge is
  // only meaningful for a suggestion we've actually SEEN queued this session:
  //   • currently queued            → PENDING
  //   • seen-queued, now gone       → APPLIED (it was consumed by an apply pass)
  //   • logged but never seen queued (orphaned flag from a prior session, or
  //     cleared externally) → NO badge (clear the stale logged flag).
  // This kills the stale "PENDING/APPLIED" that lingered when an item was
  // drained/cleared without this tab ever seeing it queued.
  const seenQueuedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const { items } = await api.changelog();
        if (!alive) return;
        const queued = new Set(
          items
            .filter((it) => it.source === "sim" && it.sim_block && it.sim_type)
            .map((it) => `${it.sim_block}:${it.sim_type}`),
        );
        queued.forEach((k) => seenQueuedRef.current.add(k));
        setClStatus(() => {
          const next: Record<string, "pending" | "applied"> = {};
          for (const k of Object.keys(loggedRef.current)) {
            if (!loggedRef.current[k]) continue;
            if (queued.has(k)) next[k] = "pending";
            else if (seenQueuedRef.current.has(k)) next[k] = "applied";
            // else: orphaned/stale → no badge (omit from clStatus)
          }
          return next;
        });
      } catch {
        // ignore
      }
    };
    tick();
    const id = setInterval(tick, 2500);
    return () => { alive = false; clearInterval(id); };
  }, []);

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
            // Circuit-edit suggestions are sim-originated: tag source + block so
            // the post-apply chain re-runs THIS sim (and only sim items) to
            // confirm the fix landed.
            await api.changelogAdd(`[sim ${res.block}/${res.sim_type}] ${s.text}`, {
              source: "sim",
              sim_block: res.block,
              sim_type: res.sim_type,
            });
          }
        } else {
          // A bare PASS/FAIL record is NOT a circuit change — log it as a plain
          // user note so it never triggers a (pointless, circular) re-sim.
          const verdict = res.ok ? "PASS" : "FAIL";
          await api.changelogAdd(
            `Sim ${verdict}: ${res.block} / ${res.sim_type}. Criterion: ${res.pass_criterion ?? "n/a"}.`,
            { source: "user" },
          );
        }
        setLogged((prev) => ({ ...prev, [key]: true }));
        // Sim circuit-edits enter the changelog as PENDING immediately; the
        // poller flips it to APPLIED once the apply pass drains the queue. Record
        // that we've seen it queued so the "gone => applied" transition is valid.
        if (sel.length > 0) {
          seenQueuedRef.current.add(key);
          setClStatus((prev) => ({ ...prev, [key]: "pending" }));
        }
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
              Simulation · ngspice
            </div>
            <span className={"text-[10px] px-1.5 py-0.5 rounded border " + (STATUS_BADGE[block.status] ?? STATUS_BADGE.not_simulatable)}>
              {block.status}
            </span>
            <span className="text-[10px] text-ink-500 font-mono">{block.sheet}</span>
            {/* per-block controls: edit requirements + clear cache + agent models */}
            <div className="ml-auto flex items-center gap-1.5">
              <button
                onClick={() => { setModelsOpen((v) => !v); setReqOpen(false); }}
                className={"h-7 px-2.5 inline-flex items-center gap-1.5 rounded-md border text-[11px] " +
                  (modelsOpen ? "border-ink-300 bg-rail text-ink-900" : "border-edge bg-white text-ink-600 hover:border-ink-300")}
                title="Which Claude model each sim agent runs on"
              >
                <I.Dot size={12} /> Agent models
              </button>
              <button
                onClick={() => { setReqOpen((v) => !v); setModelsOpen(false); }}
                className={"h-7 px-2.5 inline-flex items-center gap-1.5 rounded-md border text-[11px] " +
                  (reqOpen ? "border-ink-300 bg-rail text-ink-900" : "border-edge bg-white text-ink-600 hover:border-ink-300")}
              >
                <I.Wrench size={12} /> Requirements
              </button>
              <ClearCacheMenu
                block={block}
                onCleared={(msg) => setHealth({ text: msg, tone: "ok" })}
                onReset={() => resetBlockDisplay(block.id)}
              />
            </div>
          </div>
          <h2 className="text-[18px] font-semibold text-ink-900 mt-0.5">{block.title}</h2>
          <p className="text-sm text-ink-700 mt-1.5 leading-relaxed">{block.description}</p>

          {/* SPICE-model lifecycle: generate (no model) / update (stale) — agentic */}
          <ModelLifecycle
            block={block}
            setHealth={setHealth}
            onChanged={onBlocksChanged}
          />

          {modelsOpen && <AgentModelPicker />}

          {reqOpen && (
            <RequirementsEditor
              block={block}
              onPassEdited={(simType, value) =>
                setPassOverride((p) => ({ ...p, [resultKey(block.id, simType)]: value }))}
            />
          )}

            {block.models_needed.length > 0 && (
              <div className="mt-2 text-[11px] text-ink-500">
                models: {block.models_needed.map((m) => (
                  <span key={m} className="font-mono text-ink-700 mr-1.5">{m}</span>
                ))}
              </div>
            )}

            <div className="mt-2 text-[11px] text-ink-500">
              Deck values are read from the as-built design
              {block.sheet ? <> (<span className="font-mono text-ink-700">netlist/{block.sheet}</span>)</> : null};
              device params come from the datasheets below.
            </div>

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
                      <I.Datasheet size={14} />
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
                            <span className="uppercase tracking-wide">pass</span> · {passOverride[key] ?? st.pass}
                          </div>
                          {planned && st.defer_reason && (
                            <div className="text-[11px] text-warn/90 mt-1.5 italic">deferred: {st.defer_reason}</div>
                          )}
                        </div>
                        {!planned && (isRunning ? (
                          <button
                            onClick={cancel}
                            className="h-8 px-3 inline-flex items-center gap-1.5 rounded-md border border-err/40 bg-err/10 text-err text-xs font-medium hover:bg-err/20 shrink-0"
                          >
                            <I.X size={13} /> Cancel
                          </button>
                        ) : (
                          <button
                            onClick={() => run(st.type)}
                            disabled={running !== null || block.status !== "implemented"}
                            className="h-8 px-3 inline-flex items-center gap-1.5 rounded-md bg-ink-900 text-white text-xs font-medium hover:bg-black disabled:opacity-40 shrink-0"
                          >
                            <I.Play size={13} /> Run
                          </button>
                        ))}
                      </div>

                      {(res || interp[key]) && (
                        <div className="border-t border-edge px-4 py-3">
                          <WorkflowSteps res={res} it={interp[key]} isRunning={isRunning} />
                          {/* Behind-the-scenes: which agents are spawning + what
                              they're doing. Only while live, or when there are
                              real streamed events to inspect — never an empty
                              "no activity" box on a restored, idle entry. */}
                          {(isRunning || (interp[key]?.lines?.length ?? 0) > 0) && (
                            <AgentActivityLog it={interp[key]} isRunning={isRunning} />
                          )}
                          {res && res.status !== "ran" ? (
                            <div className="text-xs text-ink-500">{res.message}</div>
                          ) : res ? (
                            <SimReport res={res} />
                          ) : null}

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
                                  {logged[key] && (
                                    <span
                                      className={
                                        "px-1.5 py-[1px] rounded text-[10px] font-semibold " +
                                        (clStatus[key] === "applied"
                                          ? "bg-ok/15 text-ok"
                                          : "bg-warn/15 text-warn")
                                      }
                                      title={
                                        clStatus[key] === "applied"
                                          ? "The apply pass implemented this change."
                                          : "Queued in the changelog — runs when you Generate."
                                      }
                                    >
                                      {clStatus[key] === "applied" ? "APPLIED" : "PENDING"}
                                    </span>
                                  )}
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

// ---------------------------------------------------------------------------
// SPICE-model lifecycle: when a block has NO model, offer "Generate SPICE
// model"; when its model is STALE (the schematic changed under it), offer
// "Update to match schematic". Both spawn a guarded agent (claude -p) that
// writes/edits the deck builder; we stream its activity inline and re-fetch the
// catalog when it finishes (the block's has_model / model_status / sim_types
// change).
function ModelLifecycle({ block, setHealth, onChanged }: {
  block: SimBlock;
  setHealth: (h: { text: string; tone: "ok" | "warn" | "err" | "neutral" } | undefined) => void;
  onChanged?: () => void;
}) {
  const [running, setRunning] = useState<null | "generate" | "update">(null);
  const [lines, setLines] = useState<string[]>([]);
  const [done, setDone] = useState<string | null>(null);

  const run = async (kind: "generate" | "update") => {
    setRunning(kind); setLines([]); setDone(null);
    setHealth({ text: kind === "generate" ? "generating SPICE model…" : "updating model to match schematic…", tone: "neutral" });
    try {
      const { run_id } = kind === "generate"
        ? await api.simGenerateModel(block.id)
        : await api.simUpdateModel(block.id);
      await new Promise<void>((resolve) => {
        subscribeAgent(run_id,
          (l) => setLines((p) => [...p, l]),
          (status) => {
            setDone(status.text ?? "");
            resolve();
          });
      });
      setHealth({ text: kind === "generate" ? "model generated" : "model updated", tone: "ok" });
      onChanged?.();          // re-fetch the catalog: status/sim_types changed
    } catch (e) {
      setHealth({ text: "model agent error", tone: "err" });
      setDone(`error: ${String(e)}`);
    } finally {
      setRunning(null);
    }
  };

  // Decide what (if anything) to surface for this block.
  const ms = block.model_status;
  const needGenerate = !block.has_model;
  const stale = block.has_model && ms === "stale";
  // No banner when the model exists and is fresh/unknown and nothing is running.
  if (!needGenerate && !stale && !running && !done) return null;

  const tone = needGenerate
    ? "border-warn/40 bg-warn/[0.06]"
    : stale ? "border-amber-400/50 bg-amber-50" : "border-edge bg-rail/40";

  return (
    <div className={"mt-3 rounded-md border p-3 " + tone}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[12px] font-medium text-ink-900">
            {needGenerate ? "No SPICE model for this block"
              : stale ? "SPICE model may be out of date"
              : "SPICE model"}
          </div>
          <div className="text-[11px] text-ink-600 mt-0.5 leading-snug">
            {needGenerate
              ? "There's no deck builder yet. Generate one agentically from the netlist + datasheets — it authors the SPICE model, wires it in, and verifies it runs."
              : stale
                ? "The schematic changed since this model was last synced. Update it agentically to match the current netlist."
                : "Re-sync this model with the schematic at any time."}
          </div>
        </div>
        {running ? (
          <span className="h-8 px-3 inline-flex items-center gap-1.5 rounded-md border border-edge bg-white text-ink-600 text-xs shrink-0">
            <span className="w-3 h-3 rounded-full border-2 border-ink-300 border-t-ink-700 animate-spin" />
            {running === "generate" ? "generating…" : "updating…"}
          </span>
        ) : needGenerate ? (
          <button onClick={() => run("generate")}
            className="h-8 px-3 inline-flex items-center gap-1.5 rounded-md bg-ink-900 text-white text-xs font-medium hover:bg-black shrink-0">
            <I.Play size={13} /> Generate SPICE model
          </button>
        ) : (
          <button onClick={() => run("update")}
            className="h-8 px-3 inline-flex items-center gap-1.5 rounded-md border border-amber-400 bg-white text-amber-700 text-xs font-medium hover:bg-amber-50 shrink-0">
            <I.Refresh size={13} /> Update to match schematic
          </button>
        )}
      </div>
      {(running || lines.length > 0) && (
        <ModelAgentLog lines={lines} running={!!running} />
      )}
      {done && !running && (
        <div className="mt-2 text-[11px] text-ink-700 font-mono whitespace-pre-wrap border-t border-edge/60 pt-2">
          {done.split("\n").slice(-4).join("\n")}
        </div>
      )}
    </div>
  );
}

// Compact live log of the lifecycle agent's streamed tool calls (reuses the same
// classify logic as the behind-the-scenes panel).
function ModelAgentLog({ lines, running }: { lines: string[]; running: boolean }) {
  const endRef = useRef<HTMLDivElement>(null);
  const entries = lines.map(classifyLine).filter((e) => e.text);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "nearest" }); }, [entries.length]);
  return (
    <div className="mt-2 rounded border border-edge bg-white/70">
      <div className="px-2 py-1 text-[10px] uppercase tracking-wide text-ink-500 flex items-center gap-1.5">
        {running && <span className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse" />}
        model agent {running ? "working" : "log"}
        <span className="ml-auto text-ink-400">{entries.length}</span>
      </div>
      {entries.length > 0 && (
        <div className="max-h-40 overflow-auto px-2 pb-1.5 font-mono text-[10px] leading-relaxed thin-scroll">
          {entries.map((e, i) => (
            <div key={i} className="flex items-start gap-1.5 py-0.5">
              <span className={"mt-0.5 shrink-0 " + LOG_TONE[e.kind]}>{LOG_ICON[e.kind]}</span>
              <span className={"break-all " + (e.kind === "think" ? "text-ink-600 italic" : LOG_TONE[e.kind])}>{e.text}</span>
            </div>
          ))}
          <div ref={endRef} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Per-agent model picker: choose which Claude model each sim agent runs on
// (extraction/verdict vs. the heavier model-generator). Backed by
// /api/sim/agent-models; persisted server-side.
function AgentModelPicker() {
  const [cfg, setCfg] = useState<AgentModelConfig | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api.simAgentModels().then((c) => { if (alive) setCfg(c); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  if (!cfg) return <div className="mt-3 text-[11px] text-ink-400">loading agent models…</div>;
  const setModel = async (kind: string, model: string) => {
    setSaving(kind);
    try { setCfg(await api.simSetAgentModel(kind, model)); } catch { /* ignore */ } finally { setSaving(null); }
  };
  // Exact model ids grouped by family (latest first within each), for <optgroup>.
  const families: Array<ModelChoice["family"]> = ["opus", "sonnet", "haiku"];
  const byFamily = families
    .map((fam) => ({ fam, models: cfg.models.filter((m) => m.family === fam) }))
    .filter((g) => g.models.length > 0);
  const idLabel = (id: string) => cfg.models.find((m) => m.id === id)?.label ?? id;
  // Section the agents by their group (Simulation / Schematic), preserving the
  // backend's order within each.
  const groupsOrder: string[] = [];
  for (const a of cfg.agents) if (!groupsOrder.includes(a.group)) groupsOrder.push(a.group);
  const agentRow = (a: typeof cfg.agents[number]) => (
    <div key={a.kind} className="flex items-center gap-2 text-[12px]">
      <span className="text-ink-800 flex-1 truncate" title={a.kind}>{a.label}</span>
      {a.overridden && (
        <button onClick={() => setModel(a.kind, a.default)}
          className="text-[10px] text-ink-400 hover:text-ink-700" title={`reset to default (${idLabel(a.default)})`}>
          reset
        </button>
      )}
      <select
        value={a.model}
        disabled={saving === a.kind}
        onChange={(e) => setModel(a.kind, e.target.value)}
        title={a.model}
        className="h-7 w-56 rounded border border-edge bg-white text-[11px] font-mono px-1.5 outline-none focus:border-ink-400 disabled:opacity-50"
      >
        {byFamily.map((g) => (
          <optgroup key={g.fam} label={g.fam.toUpperCase()}>
            {g.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.id}{m.id === a.default ? " · default" : ""}{m.latest ? " · latest" : ""}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
  return (
    <div className="mt-3 rounded-md border border-edge bg-rail/40 p-3">
      <div className="text-[11px] uppercase tracking-wide text-ink-500 mb-2">
        Agent models · exact Anthropic model per agent (simulation + schematic)
      </div>
      <div className="space-y-3">
        {groupsOrder.map((grp) => (
          <div key={grp}>
            <div className="text-[10px] uppercase tracking-wide text-ink-400 mb-1">{grp}</div>
            <div className="space-y-1.5">
              {cfg.agents.filter((a) => a.group === grp).map(agentRow)}
            </div>
          </div>
        ))}
      </div>
      <div className="text-[10px] text-ink-400 mt-2">
        Exact pinned model ids passed to <span className="font-mono">claude --model</span>. Applies to the next run of each agent;
        authoring/repair agents default to Opus, extraction/verdict/chat to Sonnet.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Clear-cache menu: drop a block's cached sim state so the next Run re-derives
// it. Scope chosen at click time (scenario / datasheet params / all).
function ClearCacheMenu({ block, onCleared, onReset }: {
  block: SimBlock; onCleared: (msg: string) => void; onReset: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const clear = async (scope: "scenario" | "params" | "all") => {
    setOpen(false); setBusy(true);
    try {
      const r = await api.simClearCache(block.id, scope);
      const bits: string[] = [];
      if (r.scenario_cleared) bits.push("scenario");
      if (r.counters_cleared) bits.push(`${r.counters_cleared} counters`);
      if (r.params_cleared?.length) bits.push(`${r.params_cleared.length} part params`);
      // The displayed chart/verdict reflects the now-cleared cache — wipe it so
      // the tab visibly returns to "not run yet" rather than showing a stale graph.
      onReset();
      onCleared(`cleared ${block.id}: ${bits.join(", ") || "nothing cached"} — next Run re-derives`);
    } catch {
      onCleared(`clear failed for ${block.id}`);
    } finally { setBusy(false); }
  };
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={busy}
        className="h-7 px-2.5 inline-flex items-center gap-1.5 rounded-md border border-edge bg-white text-ink-600 hover:border-ink-300 text-[11px] disabled:opacity-50"
      >
        <I.Trash size={12} /> Clear cache {open ? "▾" : "▸"}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 mt-1 z-20 w-56 rounded-md border border-edge bg-white shadow-lg py-1 text-xs">
            <MenuItem label="Clear scenario" hint="operating point + re-sim counters" onClick={() => clear("scenario")} />
            <MenuItem label="Clear datasheet params" hint="re-extract device params from PDFs" onClick={() => clear("params")} />
            <div className="border-t border-edge/60 my-1" />
            <MenuItem label="Clear all" hint="scenario + params + counters" danger onClick={() => clear("all")} />
          </div>
        </>
      )}
    </div>
  );
}

function MenuItem({ label, hint, onClick, danger }: { label: string; hint: string; onClick: () => void; danger?: boolean }) {
  return (
    <button onClick={onClick}
      className={"w-full text-left px-3 py-1.5 hover:bg-rail " + (danger ? "text-err" : "text-ink-800")}>
      <div className="font-medium">{label}</div>
      <div className="text-[10px] text-ink-500">{hint}</div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Requirements editor: edit each sim_type's pass criterion + the block's
// boundary params (operating point / load / limits). Writes blocks.yaml via
// surgical, comment-preserving backend edits.
function RequirementsEditor({ block, onPassEdited }: {
  block: SimBlock; onPassEdited: (simType: string, value: string) => void;
}) {
  const [req, setReq] = useState<SimRequirements | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api.simRequirements(block.id).then((r) => { if (!cancelled) setReq(r); }).catch(() => {});
    return () => { cancelled = true; };
  }, [block.id]);

  if (!req) return <div className="mt-3 text-[11px] text-ink-400">loading requirements…</div>;

  const savePass = async (simType: string, value: string) => {
    setSaving(simType); setErr(null);
    try {
      const r = await api.simEditField(block.id, simType, "pass", value);
      setReq(r.requirements); onPassEdited(simType, value);
    } catch (e) { setErr(String(e)); } finally { setSaving(null); }
  };
  const saveBoundary = async (net: string, key: string, value: string) => {
    const tag = `${net}.${key}`; setSaving(tag); setErr(null);
    try {
      const r = await api.simEditBoundary(block.id, net, key, value);
      setReq(r.requirements);
    } catch (e) { setErr(String(e)); } finally { setSaving(null); }
  };

  return (
    <div className="mt-3 rounded-md border border-edge bg-rail/40 p-3 space-y-3">
      <div className="text-[11px] uppercase tracking-wide text-ink-500">
        Edit requirements · writes the curated catalog (blocks.yaml)
      </div>
      {err && <div className="text-[11px] text-err">{err}</div>}

      {/* per-sim pass criteria */}
      <div className="space-y-2">
        {req.sim_types.map((s) => (
          <PassRow key={s.type} type={s.type} status={s.status} value={s.pass ?? ""}
                   saving={saving === s.type} onSave={(v) => savePass(s.type, v)} />
        ))}
      </div>

      {/* block boundary params */}
      {Object.keys(req.boundaries).length > 0 && (
        <div>
          <div className="text-[11px] uppercase tracking-wide text-ink-500 mb-1">
            Boundary params · off-sheet operating point / load
          </div>
          <div className="space-y-1.5">
            {Object.entries(req.boundaries).map(([net, b]) => (
              <BoundaryRow key={net} net={net} stub={b.stub} params={b.params}
                           savingKey={saving} onSave={(k, v) => saveBoundary(net, k, v)} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PassRow({ type, status, value, saving, onSave }: {
  type: string; status: string; value: string; saving: boolean; onSave: (v: string) => void;
}) {
  const [text, setText] = useState(value);
  useEffect(() => { setText(value); }, [value]);
  const dirty = text !== value;
  return (
    <div className="flex items-start gap-2">
      <span className="font-mono text-[11px] text-ink-700 w-36 shrink-0 pt-1.5 truncate" title={type}>
        {type}{status === "planned" ? " ·planned" : ""}
      </span>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={2}
        className="flex-1 text-[11px] rounded border border-edge px-2 py-1 font-mono resize-y focus:border-ink-400 outline-none"
      />
      <button
        onClick={() => onSave(text)}
        disabled={!dirty || saving}
        className="h-7 px-2 mt-0.5 rounded border border-edge text-[11px] text-ink-700 hover:border-ink-300 disabled:opacity-40 shrink-0"
      >
        {saving ? "…" : "Save"}
      </button>
    </div>
  );
}

function BoundaryRow({ net, stub, params, savingKey, onSave }: {
  net: string; stub: string | null; params: Record<string, string | number>;
  savingKey: string | null; onSave: (key: string, value: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [newKey, setNewKey] = useState("");
  return (
    <div className="rounded border border-edge/70 bg-white px-2 py-1.5">
      <div className="flex items-center gap-2 text-[11px]">
        <span className="font-mono text-ink-800">{net}</span>
        {stub && <span className="text-[10px] text-ink-400">{stub}</span>}
        <button onClick={() => setAdding((v) => !v)}
                className="ml-auto text-[10px] text-ink-500 hover:text-ink-800 inline-flex items-center gap-0.5">
          <I.Plus size={10} /> param
        </button>
      </div>
      <div className="flex flex-wrap gap-1.5 mt-1">
        {Object.entries(params).map(([k, v]) => (
          <ParamField key={k} pkey={k} value={String(v)} saving={savingKey === `${net}.${k}`}
                      onSave={(val) => onSave(k, val)} />
        ))}
      </div>
      {adding && (
        <div className="flex items-center gap-1.5 mt-1.5">
          <input value={newKey} onChange={(e) => setNewKey(e.target.value)} placeholder="key"
                 className="w-24 text-[11px] rounded border border-edge px-1.5 py-0.5 font-mono outline-none" />
          <ParamField pkey="" value="" saving={false} placeholder="value"
                      onSave={(val) => { if (newKey.trim()) { onSave(newKey.trim(), val); setNewKey(""); setAdding(false); } }} />
        </div>
      )}
    </div>
  );
}

function ParamField({ pkey, value, saving, onSave, placeholder }: {
  pkey: string; value: string; saving: boolean; onSave: (v: string) => void; placeholder?: string;
}) {
  const [text, setText] = useState(value);
  useEffect(() => { setText(value); }, [value]);
  const dirty = text !== value;
  return (
    <span className="inline-flex items-center gap-1 rounded border border-edge bg-rail/50 pl-1.5 pr-0.5 py-0.5">
      {pkey && <span className="font-mono text-[10px] text-ink-500">{pkey}</span>}
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && (dirty || placeholder)) onSave(text); }}
        placeholder={placeholder}
        className="w-16 text-[10.5px] font-mono bg-transparent outline-none"
      />
      {(dirty || (placeholder && text)) && (
        <button onClick={() => onSave(text)} disabled={saving}
                className="text-[10px] text-blue-600 px-1 hover:text-blue-800 disabled:opacity-40">
          {saving ? "…" : "✓"}
        </button>
      )}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Behind-the-scenes activity log: parse the agent's streamed stream-json lines
// (already classified backend-side into "tool: Read <path>", "tool: Bash <cmd>",
// "assistant: …", "result: …") into typed, readable entries — so you can see
// which agent spawned and exactly what it did (read which datasheet, ran which
// re-sim, wrote which cache file).

type LogKind = "agent" | "read" | "write" | "bash" | "think" | "result" | "raw";
interface LogEntry { kind: LogKind; text: string }

function classifyLine(l: string): LogEntry {
  const base = (p: string) => p.split(/[\\/]/).pop() || p;
  let m;
  if ((m = l.match(/^tool:\s*Read\s+(.+)$/i))) return { kind: "read", text: base(m[1].trim()) };
  if ((m = l.match(/^tool:\s*(Edit|Write)\s+(.+)$/i))) return { kind: "write", text: base(m[2].trim()) };
  if ((m = l.match(/^tool:\s*Bash\s+(.+)$/i))) return { kind: "bash", text: m[1].trim() };
  if ((m = l.match(/^tool:\s*(\w+)(.*)$/i))) return { kind: "bash", text: (m[1] + (m[2] || "")).trim() };
  if ((m = l.match(/^assistant:\s*(.+)$/i))) return { kind: "think", text: m[1].trim() };
  if ((m = l.match(/^result:\s*(.+)$/i))) return { kind: "result", text: m[1].trim() };
  return { kind: "raw", text: l };
}

const LOG_ICON: Record<LogKind, React.ReactNode> = {
  agent: <I.Play size={11} />, read: <I.Datasheet size={11} />, write: <I.Plus size={11} />,
  bash: <I.Refresh size={11} />, think: <I.Dot size={11} />, result: <I.Check size={11} />,
  raw: <I.Dot size={11} />,
};
const LOG_TONE: Record<LogKind, string> = {
  agent: "text-ink-900 font-medium", read: "text-blue-600", write: "text-emerald-600",
  bash: "text-violet-600", think: "text-ink-600", result: "text-ink-500", raw: "text-ink-400",
};
const LOG_VERB: Record<LogKind, string> = {
  agent: "", read: "read", write: "wrote", bash: "ran", think: "", result: "", raw: "",
};

function AgentActivityLog({ it, isRunning }: { it?: Interp; isRunning: boolean }) {
  const [open, setOpen] = useState(true);
  const endRef = useRef<HTMLDivElement>(null);
  // Classified events from the agent's streamed stream-json output.
  const lines = it?.lines ?? [];
  const entries: LogEntry[] = lines.map(classifyLine).filter((e) => e.text);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "nearest" }); }, [entries.length]);

  if (!it) return null;
  const phase = it.phase;
  // The live-agent header pulses ONLY while actually running — never from a
  // restored phase on reload.
  const agentLabel = !isRunning ? null
    : phase === "setup" ? "Datasheet & scenario agent — extracting device params + operating point"
    : phase === "interpret" ? "Verdict agent — checking the result against datasheets + spec"
    : null;

  return (
    <div className="mt-3 rounded-md border border-edge bg-ink-900/[0.02]">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[11px] text-ink-600 hover:text-ink-900"
      >
        <I.Wrench size={12} />
        <span className="uppercase tracking-wide">behind the scenes</span>
        {agentLabel && (
          <span className="inline-flex items-center gap-1 text-[10px] text-ink-500">
            <span className="w-1.5 h-1.5 rounded-full bg-violet-500 animate-pulse" />
            {agentLabel}
          </span>
        )}
        <span className="ml-auto text-ink-400">{open ? "▾" : "▸"} {entries.length}</span>
      </button>
      {open && entries.length > 0 && (
        <div className="max-h-44 overflow-auto px-2.5 pb-2 font-mono text-[10.5px] leading-relaxed thin-scroll">
          {entries.map((e, i) => (
            <div key={i} className="flex items-start gap-1.5 py-0.5">
              <span className={"mt-0.5 shrink-0 " + LOG_TONE[e.kind]}>{LOG_ICON[e.kind]}</span>
              <span className="text-ink-400 shrink-0 w-8">{LOG_VERB[e.kind]}</span>
              <span className={"break-all " + (e.kind === "think" ? "text-ink-600 italic" : LOG_TONE[e.kind])}>
                {e.text}
              </span>
            </div>
          ))}
          <div ref={endRef} />
        </div>
      )}
      {open && entries.length === 0 && (
        <div className="px-2.5 pb-2 text-[10.5px] text-ink-400 font-mono">
          {agentLabel ? "waiting for agent output…" : "no agent activity (params were cached; ngspice ran directly)"}
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
      {/* While running: concise checklist of what it's reading. Only while the
          agent is actually live — otherwise a dropped/timed-out interpret would
          keep showing the checklist as if still working. */}
      {!it.verdict && it.running && <ThinkingChecklist block={block} it={it} />}
      {it.verdict && (
        <div className={"mt-2 inline-flex items-center gap-2 rounded border px-2 py-1 text-xs font-medium " + tone}>
          {it.verdict.replace(/_/g, " ")}
        </div>
      )}
      {/* Interpret ended without a verdict (stream dropped / timed out / agent
          unavailable). The sim result itself is unaffected. */}
      {!it.verdict && !it.running && it.interpretError && (
        <div className="mt-2 flex items-start gap-1.5 text-[11px] text-ink-500">
          <I.Dot size={12} className="mt-0.5 shrink-0 text-warn" />
          <span>{it.interpretError}. You can re-run to retry the interpretation.</span>
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
