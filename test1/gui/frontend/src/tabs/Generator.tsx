import { useCallback, useEffect, useMemo, useState } from "react";
import { api, subscribeAgent, subscribeRun } from "../api";
import { ChangelogPanel } from "../components/ChangelogPanel";
import { Console } from "../components/Console";
import { I } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import type {
  AgentDecision,
  Freshness,
  LintReport,
  PhaseEvent,
  Severity,
  StagePhase,
} from "../types";

interface Props {
  onArtifactsChanged: () => void;
  setHealth: (h: { text: string; tone: "ok" | "warn" | "err" | "neutral" } | undefined) => void;
  /** Called whenever the pipeline stage changes (used by AgentRail). */
  setStage: (s: StagePhase) => void;
  /** Called whenever a new activity line should be appended to the rail's
   *  status log. */
  pushActivity: (line: string) => void;
  /** Called to clear the rail's activity log before a new pipeline run. */
  clearActivity: () => void;
  /** Called to update the structured phases dropdown in the rail. */
  setPhases: (p: PhaseEvent[]) => void;
  /** Called to update the live "sub-phase" hint next to the stepper. */
  setSubPhase: (s: string | undefined) => void;
  /** Incremented when the user clicks the Refresh button; triggers lint/freshness update. */
  refreshTrigger?: number;
}

type RunState = "idle" | "running" | "ok" | "fail";

const SEV_DOT: Record<Severity, string> = {
  ERROR: "bg-err",
  WARNING: "bg-warn",
  INFO: "bg-ink-300",
};

export function Generator({
  onArtifactsChanged,
  setHealth,
  setStage,
  pushActivity,
  clearActivity,
  setPhases,
  setSubPhase,
  refreshTrigger,
}: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [runState, setRunState] = useState<RunState>("idle");
  const [lint, setLint] = useState<LintReport | null>(null);
  const [netlistFiles, setNetlistFiles] = useState<string[]>([]);
  const [fresh, setFresh] = useState<Freshness | null>(null);
  const [queuedCount, setQueuedCount] = useState(0);
  // Bumped to force the embedded ChangelogPanel to re-fetch immediately (e.g.
  // right after an apply pass drains the queue), instead of waiting for its poll.
  const [changelogTick, setChangelogTick] = useState(0);
  // Per-item agent outcomes from the last apply/fix pass (APPLIED/STOPPED/CLARIFY)
  // + an optional expanded reasoning log, so a run's "why" is auditable in-GUI.
  const [decisions, setDecisions] = useState<AgentDecision[]>([]);
  const [reasoningOpen, setReasoningOpen] = useState(false);
  const [reasoningLog, setReasoningLog] = useState<string>("");
  // Closed-loop review scope. After apply+build the backend reads the gates
  // (validator + lint) and, if not clean, spawns a bounded fix pass and rebuilds
  // (up to 3 rounds) so Generate lands a gate-clean change. Two opt-in modes,
  // mutually exclusive:
  //   "off"             — plain one-shot generate (no fix loop).
  //   "errors"          — loop until lint ERRORs = 0 (warnings advisory).
  //   "errors_warnings" — loop until ERRORs = 0 AND WARNINGs = 0.
  const [loopMode, setLoopMode] = useState<"off" | "errors" | "errors_warnings">("off");
  const loopReview = loopMode !== "off";
  const fixWarnings = loopMode === "errors_warnings";
  // Which severity's detail list is expanded under the count cards (click to open).
  const [openSev, setOpenSev] = useState<Severity | null>(null);
  // Whether the linter checklist section is expanded.
  const [linterOpen, setLinterOpen] = useState(false);
  // Filter rules by severity ("all" | "ERROR" | "WARNING" | "INFO") or by rule ID
  const [ruleFilter, setRuleFilter] = useState<string>("all");
  // Track which lint issues are selected for adding to changelog
  // Format: "rule_id:issue_index" (e.g., "offpage_text:0", "label_overlap:2")
  const [selectedIssues, setSelectedIssues] = useState<Set<string>>(new Set());

  // Refresh lint report whenever artifacts change.
  const refreshLint = useCallback(async () => {
    try {
      const r = await api.lint(runId ?? undefined);
      setLint(r);
      const c = r.counts;
      const tone = c.ERROR > 0 ? "err" : c.WARNING > 0 ? "warn" : "ok";
      setHealth({ text: `${c.ERROR}E · ${c.WARNING}W · ${c.INFO}I`, tone });
    } catch {
      // ignore
    }
  }, [runId, setHealth]);

  const refreshFresh = useCallback(async () => {
    try {
      setFresh(await api.freshness());
    } catch {
      setFresh(null);
    }
  }, []);

  const refreshChangelogCount = useCallback(async () => {
    try {
      const r = await api.changelog();
      setQueuedCount(r.items.length);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    refreshLint();
    refreshFresh();
    refreshChangelogCount();
    api.netlistList().then((r) => setNetlistFiles(r.files)).catch(() => {});
    const t = setInterval(refreshChangelogCount, 2500);
    return () => clearInterval(t);
  }, [refreshLint, refreshFresh, refreshChangelogCount, refreshTrigger]);

  // When a run finishes, pull the apply/fix pass's per-item decisions so the
  // user sees each changelog item's outcome (APPLIED/STOPPED/CLARIFY) and why.
  useEffect(() => {
    if (runState !== "ok" && runState !== "fail") return;
    api.agentDecisions()
      .then((d) => setDecisions(d.decisions ?? []))
      .catch(() => setDecisions([]));
  }, [runState]);

  const openReasoning = useCallback(async () => {
    setReasoningOpen((v) => !v);
    if (reasoningLog) return;
    try {
      const runs = await api.agentRuns();
      const latest = runs.runs.find((r) => /kind=apply|kind=lint_fix/.test(r.header)) ?? runs.runs[0];
      if (latest) setReasoningLog((await api.agentRunLog(latest.run_id)).body);
    } catch {
      setReasoningLog("(could not load reasoning log)");
    }
  }, [reasoningLog]);

  const startGenerate = async (opts: { force?: boolean } = {}) => {
    // If outputs are fresh AND nothing is queued, ask before regenerating.
    // (When the changelog has items, the click is unambiguous: apply them.)
    if (fresh?.status === "fresh" && queuedCount === 0 && !opts.force) {
      const ok = window.confirm(
        "Schematic is already up to date and no changelog items are queued. " +
        "Regenerate anyway?",
      );
      if (!ok) return;
    }
    setLines([]);
    setRunState("running");
    setHealth({ text: "running…", tone: "neutral" });
    clearActivity();
    setStage("connecting");

    try {
      // Stage 1+2: apply changelog (if any), then generate. Single backend
      // call orchestrates both runs.
      setLines((prev) => [...prev, "Contacting backend for build orchestration..."]);
      const { apply_run_id, generate_run_id, loop_review, fix_warnings, max_rounds } =
        await api.applyAndGenerate(loopReview, fixWarnings);
      setLines((prev) => [...prev, `Backend connected: apply_run_id=${apply_run_id || "none"} generate_run_id=${generate_run_id ?? "pending"}`]);
      if (loop_review) {
        const scope = fix_warnings ? "errors + warnings" : "errors";
        setLines((prev) => [...prev, `[LOOP] Closed-loop review on (${scope}) — apply → build → read gates → fix (up to ${max_rounds} rounds) until clean.`]);
        pushActivity(`▶ closed-loop review · ${scope} (≤${max_rounds} fix rounds)`);
      }

      if (apply_run_id) {
        setStage("applying-changelog");
        setSubPhase(`apply ${queuedCount} bullet${queuedCount === 1 ? "" : "s"}`);
        setLines((prev) => [...prev, `[APPLY] Starting changelog apply pass for ${queuedCount} item(s)`]);
        pushActivity(`▶ apply pass (${queuedCount} item${queuedCount === 1 ? "" : "s"})`);
        // Stream the agent's tool calls into the rail.
        await new Promise<void>((resolve) => {
          subscribeAgent(
            apply_run_id,
            (line) => {
              setLines((prev) => [...prev, `[APPLY] ${line}`]);
              pushActivity(line);
              // Pull the trailing detail out of "tool: Edit file_path=…"
              // so the topbar hint shows the file being touched.
              const m = /^tool: (\w+)\s+(.*)$/.exec(line);
              if (m) setSubPhase(`${m[1]} ${m[2]}`.slice(0, 80));
            },
            ({ status }) => {
              setLines((prev) => [...prev, `[APPLY] Finished with status: ${status}`]);
              pushActivity(`✓ apply ${status}`);
              resolve();
            },
          );
        });
      }

      // CLOSED-LOOP REVIEW: the backend runs apply -> build -> fix -> build … in
      // the background, so there isn't a single generate run — there's a sequence
      // of "generate" and "lint-fix" runs. Stream each as it appears, in order,
      // until the loop settles (no new run shows up within the grace window).
      if (loop_review) {
        // The backend runs apply -> build -> fix -> build … strictly SEQUENTIALLY
        // in the background, so at any moment at most ONE generate/lint-fix run is
        // `running`. Stream whichever is running; when none is, wait briefly; stop
        // once the chain has gone quiet (idle grace). No ordering math needed.
        const streamed = new Set<string>();
        const streamOne = (id: string, kind: string) =>
          new Promise<string>((resolve) => {
            setRunId(kind === "generate" ? id : null);
            setStage(kind === "lint-fix" ? "applying-changelog" : "generating");
            setSubPhase(kind === "lint-fix" ? "fixing lint/validator failures" : "building + gating");
            pushActivity(`▶ ${kind}`);
            const tag = kind === "lint-fix" ? "[FIX]" : "[GEN]";
            const onLine = (line: string) => { setLines((prev) => [...prev, `${tag} ${line}`]); pushActivity(line); };
            const onDone = ({ status }: { status: string }) => { pushActivity(`✓ ${kind} ${status}`); resolve(status); };
            if (kind === "generate") subscribeRun(id, onLine, onDone);
            else subscribeAgent(id, onLine, onDone);
          });
        let lastBuildStatus = "fail";
        let idle = 0;
        // Cap generously: apply + up to 3×(fix+build) phases, with a polling grace.
        for (let guard = 0; guard < 60 && idle < 20; guard++) {
          let running: { id: string; kind: string } | null = null;
          try {
            const state = await api.state();
            const r = (state.runs as any[]).find(
              (x: any) => (x.kind === "generate" || x.kind === "lint-fix")
                && x.status === "running" && !streamed.has(x.run_id),
            );
            if (r) running = { id: r.run_id, kind: r.kind };
          } catch { /* keep polling */ }
          if (running) {
            streamed.add(running.id);
            idle = 0;
            const st = await streamOne(running.id, running.kind);
            if (running.kind === "generate") lastBuildStatus = st;
          } else {
            idle++;
            await new Promise((r) => setTimeout(r, 500));
          }
        }
        setRunState(lastBuildStatus === "ok" ? "ok" : "fail");
        onArtifactsChanged();
        setStage(lastBuildStatus === "ok" ? "done" : "error");
        setSubPhase(undefined);
        setLines((prev) => [...prev,
          lastBuildStatus === "ok"
            ? `[LOOP] Closed-loop review complete — build passes the gates (lint ERRORs = 0${fixWarnings ? " and WARNINGs = 0" : ""}).`
            : `[LOOP] Closed-loop review ended — gates still not clean after the fix rounds; see the linter.`]);
        setTimeout(() => { refreshLint(); refreshFresh(); refreshChangelogCount(); setChangelogTick((t) => t + 1); }, 250);
        return;
      }

      // If there's no generate_run_id yet (still waiting for apply to complete),
      // poll for it to appear before subscribing.
      let genRunId = generate_run_id;
      if (!genRunId) {
        setLines((prev) => [...prev, `[GEN] Waiting for apply pass to complete before starting build...`]);
        // Poll for the generate run to appear in the registry
        let pollCount = 0;
        while (!genRunId && pollCount < 120) {
          // Max 60 seconds polling (500ms * 120)
          await new Promise((resolve) => setTimeout(resolve, 500));
          pollCount++;
          try {
            const state = await api.state();
            const genRun = (state.runs as any[]).find(
              (r: any) => r.kind === "generate" && r.status === "running",
            );
            if (genRun) genRunId = genRun.id;
          } catch {
            // If the API call fails, keep polling
          }
        }
        if (!genRunId) {
          throw new Error("Generate run failed to start after apply pass");
        }
      }

      setStage("generating");
      setSubPhase("starting build");
      setLines((prev) => [...prev, `[GEN] Starting build process (run_id=${genRunId})...`]);
      pushActivity("▶ build");
      setRunId(genRunId);
      subscribeRun(
        genRunId,
        (line) => {
          setLines((prev) => [...prev, line]);
          pushActivity(line);
          // Surface "wrote <sheet>.kicad_sch" / "Phase N …" lines as the
          // sub-phase hint so the user can see progress in real time.
          const sheetM = /wrote\s+(\S+\.kicad_sch|.*\.SchDoc)/.exec(line);
          if (sheetM) {
            setSubPhase(`wrote ${sheetM[1]}`);
          } else if (line.startsWith("Phase ")) {
            setSubPhase(line.trim());
          } else if (/kicad-cli|export svg|render/.test(line.toLowerCase())) {
            setSubPhase("rendering");
          }
        },
        ({ status }) => {
          setRunState(status === "ok" ? "ok" : "fail");
          setLines((prev) => [...prev, `[GEN] Build completed with status: ${status}`]);
          onArtifactsChanged();
          setStage("linting");
          setSubPhase("parsing lint report");
          pushActivity(`✓ generate ${status}`);
          // Slight delay so the file system catches up before re-fetching.
          setTimeout(() => {
            refreshLint();
            refreshFresh();
            refreshChangelogCount();
            setChangelogTick((t) => t + 1);
            // Pull the structured phases so the dropdown updates.
            api.runPhases(genRunId)
              .then((r) => setPhases(r.phases ?? []))
              .catch(() => {});
            setStage(status === "ok" ? "done" : "error");
            setSubPhase(undefined);
          }, 250);
        },
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setLines((prev) => [...prev, `ERROR: ${msg}`]);
      setRunState("fail");
      setStage("error");
      setHealth({ text: `error: ${msg}`, tone: "err" });
      pushActivity(`✗ Failed: ${msg}`);
    }
  };

  const byRule = useMemo(() => {
    const m: Record<string, { issues: typeof lint extends null ? never : NonNullable<LintReport>["issues"] }> = {};
    if (lint) {
      for (const r of lint.rules) m[r.id] = { issues: [] as any };
      for (const i of lint.issues) {
        if (!m[i.rule]) m[i.rule] = { issues: [] as any };
        (m[i.rule].issues as any).push(i);
      }
    }
    return m;
  }, [lint]);

  const counts = lint?.counts ?? { ERROR: 0, WARNING: 0, INFO: 0 };

  return (
    <div className="h-full overflow-auto thin-scroll">
      <div className="px-6 py-5 max-w-[1100px]">
        <PageHeader
          eyebrow="Phase 2 · Schematic Generator"
          title="Build, render, and lint the schematic from the YAML netlists"
        />

        <div className="mt-4 grid grid-cols-3 gap-3">
          <StatCard
            label="ERRORs"
            value={counts.ERROR}
            tone={counts.ERROR ? "err" : "ok"}
            active={openSev === "ERROR"}
            onClick={() => setOpenSev((s) => (s === "ERROR" ? null : "ERROR"))}
          />
          <StatCard
            label="WARNINGs"
            value={counts.WARNING}
            tone={counts.WARNING ? "warn" : "ok"}
            active={openSev === "WARNING"}
            onClick={() => setOpenSev((s) => (s === "WARNING" ? null : "WARNING"))}
          />
          <StatCard
            label="INFOs"
            value={counts.INFO}
            tone="neutral"
            active={openSev === "INFO"}
            onClick={() => setOpenSev((s) => (s === "INFO" ? null : "INFO"))}
          />
        </div>

        {openSev && (
          <SeverityDetail
            severity={openSev}
            issues={(lint?.issues ?? []).filter((i) => i.severity === openSev)}
            onClose={() => setOpenSev(null)}
            onChangelogAdded={refreshChangelogCount}
          />
        )}

        <div className="mt-4">
          <FreshnessBar fresh={fresh} />
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            onClick={() => startGenerate()}
            disabled={runState === "running"}
            className={
              "h-9 px-3 inline-flex items-center gap-2 rounded-md text-sm font-medium disabled:opacity-50 " +
              (fresh?.status === "fresh" && queuedCount === 0
                ? "border border-edge text-ink-700 bg-white hover:border-ink-300"
                : "bg-ink-900 text-white hover:bg-black")
            }
          >
            <I.Play size={14} />
            {runState === "running"
              ? "Generating…"
              : queuedCount > 0
              ? `Apply ${queuedCount} change${queuedCount === 1 ? "" : "s"} + Generate`
              : fresh?.status === "fresh"
              ? "Regenerate anyway"
              : fresh?.status === "stale"
              ? "Generate (sources changed)"
              : "Generate schematic"}
          </button>
          {/* Closed-loop review scope — apply -> build -> read gates -> bounded
              fix -> rebuild until clean. Two mutually-exclusive ticks; clicking
              the active one turns the loop off (plain one-shot generate). */}
          <LoopTick
            label="Fix errors"
            title="After applying changes, build and read the validator + layout-lint gates; if any ERRORs remain, an agent fixes them and rebuilds (up to 3 rounds) so Generate lands a build with zero lint ERRORs. Warnings stay advisory."
            checked={loopMode === "errors"}
            disabled={runState === "running"}
            onToggle={() => setLoopMode((m) => (m === "errors" ? "off" : "errors"))}
          />
          <LoopTick
            label="Fix errors + warnings"
            title="Same fix loop as 'Fix errors', but the agent also clears every WARNING — it keeps fixing and rebuilding (up to 3 rounds) until both ERRORs and WARNINGs reach zero. INFO stays advisory."
            checked={loopMode === "errors_warnings"}
            disabled={runState === "running"}
            onToggle={() => setLoopMode((m) => (m === "errors_warnings" ? "off" : "errors_warnings"))}
          />
          <button
            onClick={() => {
              refreshLint();
              refreshFresh();
              refreshChangelogCount();
              // Re-pull the rendered sheets too (bumps PngViewer's `bust`, which
              // re-fetches /api/sheets — the new mtimes cache-bust the images),
              // so Refresh shows whatever the current on-disk build is.
              onArtifactsChanged();
            }}
            className="h-9 px-3 inline-flex items-center gap-2 rounded-md border border-edge text-ink-700 text-sm hover:border-ink-300"
          >
            <I.Refresh size={14} />
            Refresh
          </button>
          <span className="text-xs text-ink-500 ml-2">
            sources: {netlistFiles.length ? netlistFiles.join(" · ") : "—"}
          </span>
        </div>

        {/* Changelog — add + view queued changes directly here, under Regenerate
            and above the linter checklist. Styled like the linter SubSection;
            shares state with the Agent rail's copy via the backend. */}
        <ChangelogPanel variant="tab" refreshKey={changelogTick} onCountChange={setQueuedCount} />

        {decisions.length > 0 && (
          <div className="mb-3 rounded-md border border-edge bg-surface-50 p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[12px] font-medium text-ink-700">
                Agent decisions ({decisions.length})
              </span>
              <button
                onClick={openReasoning}
                className="text-[11px] text-ink-500 hover:text-ink-800 underline decoration-dotted"
              >
                {reasoningOpen ? "hide reasoning" : "view reasoning"}
              </button>
            </div>
            <ul className="space-y-1">
              {decisions.map((d, i) => (
                <li key={i} className="flex items-start gap-2 text-[12px]">
                  <span
                    className={
                      "mt-[1px] px-1.5 py-[1px] rounded text-[10px] font-semibold shrink-0 " +
                      (d.outcome === "APPLIED"
                        ? "bg-ok/15 text-ok"
                        : d.outcome === "STOPPED"
                        ? "bg-warn/15 text-warn"
                        : "bg-ink-200 text-ink-700")
                    }
                  >
                    {d.outcome}
                  </span>
                  <span className="text-ink-500 shrink-0">{d.item}</span>
                  <span className="text-ink-700">{d.reason}</span>
                </li>
              ))}
            </ul>
            {reasoningOpen && (
              <pre className="mt-2 max-h-64 overflow-auto thin-scroll rounded border border-edge bg-white text-ink-800 text-[11px] leading-snug p-2 whitespace-pre-wrap">
                {reasoningLog || "loading…"}
              </pre>
            )}
          </div>
        )}

        <SubSection
          title="Linter checklist"
          hint="layout_lint.py rules — pass when no issue fired"
          collapsible
          open={linterOpen}
          onToggle={() => setLinterOpen((o) => !o)}
        >
          <div className="space-y-2 mt-2 mb-3">
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium text-ink-600">Filter:</label>
              <select
                value={ruleFilter}
                onChange={(e) => setRuleFilter(e.target.value)}
                className="text-xs px-2 py-1 rounded border border-edge bg-white text-ink-900"
              >
                <option value="all">All rules</option>
                <option value="ERROR">Errors only</option>
                <option value="WARNING">Warnings only</option>
                <option value="INFO">Info only</option>
                <option value="fired">Fired only</option>
                {(lint?.rules ?? []).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.id}
                  </option>
                ))}
              </select>
            </div>
            {selectedIssues.size > 0 && (
              <button
                onClick={async () => {
                  // Add each selected issue to changelog
                  for (const issueKey of selectedIssues) {
                    const [ruleId, idxStr] = issueKey.split(":");
                    const idx = parseInt(idxStr);
                    const rule = lint?.rules.find((r) => r.id === ruleId);
                    const issues = (byRule[ruleId]?.issues ?? []) as any[];
                    const issue = issues[idx];

                    if (issue && rule) {
                      const summary = `Fix ${rule.id}: [${issue.sheet}] ${issue.message.slice(0, 50)}`;
                      try {
                        await api.changelogAdd(summary);
                      } catch {
                        // ignore
                      }
                    }
                  }
                  setSelectedIssues(new Set());
                  refreshChangelogCount();
                }}
                className="text-xs px-3 py-1.5 rounded bg-warn/10 text-warn border border-warn/30 font-medium hover:bg-warn/15 transition-colors"
              >
                Add {selectedIssues.size} fix{selectedIssues.size !== 1 ? "es" : ""} to changelog
              </button>
            )}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {(lint?.rules ?? [])
              .filter((r) => {
                if (ruleFilter === "all") return true;
                if (ruleFilter === "fired") {
                  const hits = (byRule[r.id]?.issues ?? []) as LintReport["issues"];
                  return hits.length > 0;
                }
                if (ruleFilter === "ERROR" || ruleFilter === "WARNING" || ruleFilter === "INFO") {
                  return r.severity === ruleFilter;
                }
                return r.id === ruleFilter;
              })
              .map((r) => {
              const hits = (byRule[r.id]?.issues ?? []) as LintReport["issues"];
              const top = hits[0];
              const tone = top
                ? top.severity === "ERROR"
                  ? "err"
                  : top.severity === "WARNING"
                  ? "warn"
                  : "neutral"
                : "ok";
              return (
                <div
                  key={r.id}
                  className={
                    "flex items-start gap-3 px-3 py-2 rounded-md border " +
                    (tone === "ok"
                      ? "bg-white border-edge"
                      : tone === "err"
                      ? "bg-err/[0.04] border-err/30"
                      : tone === "warn"
                      ? "bg-warn/[0.04] border-warn/30"
                      : "bg-rail border-edge")
                  }
                >
                  <span
                    className={
                      "mt-0.5 inline-flex items-center justify-center w-5 h-5 rounded-full " +
                      (tone === "ok"
                        ? "bg-ok/10 text-ok"
                        : tone === "err"
                        ? "bg-err/10 text-err"
                        : tone === "warn"
                        ? "bg-warn/10 text-warn"
                        : "bg-edge text-ink-500")
                    }
                  >
                    {tone === "ok" ? <I.Check size={12} /> : <I.Dot size={12} />}
                  </span>
                  <div className="min-w-0">
                    <div className="text-sm text-ink-900">{r.summary}</div>
                    <div className="text-[11px] text-ink-500 font-mono flex items-center gap-1.5">
                      <span>{r.id}</span>
                      {r.severity && (
                        <span
                          title={
                            tone === "ok"
                              ? `Severity if this rule fires: ${r.severity} (currently passing)`
                              : `${r.severity} — this rule fired`
                          }
                          className={
                            "px-1 rounded text-[9.5px] font-semibold uppercase tracking-wide " +
                            // Color the severity chip ONLY when the rule actually
                            // fired. When passing (tone "ok") it's just labeling
                            // the rule's class, so keep it muted — a red ERROR
                            // chip on a passing row reads as a live error.
                            (tone === "ok"
                              ? "bg-edge text-ink-400"
                              : r.severity === "ERROR"
                              ? "bg-err/10 text-err"
                              : r.severity === "WARNING"
                              ? "bg-warn/10 text-warn"
                              : "bg-edge text-ink-500")
                          }
                        >
                          {r.severity}
                        </span>
                      )}
                      {r.scope === "library" && (
                        <span className="px-1 rounded text-[9.5px] bg-edge text-ink-500">lib</span>
                      )}
                    </div>
                    {hits.length > 0 && (
                      <div className="mt-2 space-y-1">
                        <div className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={hits.every((_, i) => selectedIssues.has(`${r.id}:${i}`))}
                            onChange={(e) => {
                              const newSelected = new Set(selectedIssues);
                              if (e.target.checked) {
                                hits.forEach((_, i) => newSelected.add(`${r.id}:${i}`));
                              } else {
                                hits.forEach((_, i) => newSelected.delete(`${r.id}:${i}`));
                              }
                              setSelectedIssues(newSelected);
                            }}
                            className="w-3.5 h-3.5 cursor-pointer"
                            title="Select all instances of this rule"
                          />
                          <span className="text-[10px] text-ink-500 font-medium">Select all {hits.length}</span>
                        </div>
                        {hits.map((h, i) => (
                          <div key={i} className="flex items-start gap-2 text-[11.5px] text-ink-700">
                            <input
                              type="checkbox"
                              checked={selectedIssues.has(`${r.id}:${i}`)}
                              onChange={(e) => {
                                const issueKey = `${r.id}:${i}`;
                                const newSelected = new Set(selectedIssues);
                                if (e.target.checked) {
                                  newSelected.add(issueKey);
                                } else {
                                  newSelected.delete(issueKey);
                                }
                                setSelectedIssues(newSelected);
                              }}
                              className="w-3.5 h-3.5 mt-0.5 cursor-pointer flex-shrink-0"
                            />
                            <div className="min-w-0">
                              <span className={"inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle " + SEV_DOT[h.severity]} />
                              <span className="font-medium">[{h.sheet}]</span>{" "}
                              {h.message}
                              {h.refs.length > 0 && (
                                <span className="text-ink-500"> ({h.refs.join(", ")})</span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
            {(!lint || lint.rules.length === 0) && (
              <div className="text-sm text-ink-500">Run the generator to populate the checklist.</div>
            )}
          </div>
        </SubSection>

        <SubSection
          title="Generator console"
          hint="stdout from gen_schematic.py — streamed live"
        >
          <Console
            lines={lines}
            status={runState}
          />
        </SubSection>
      </div>
    </div>
  );
}

// One of the two mutually-exclusive closed-loop scope ticks next to Generate.
function LoopTick({
  label,
  title,
  checked,
  disabled,
  onToggle,
}: {
  label: string;
  title: string;
  checked: boolean;
  disabled?: boolean;
  onToggle: () => void;
}) {
  return (
    <label
      title={title}
      className={
        "inline-flex items-center gap-1.5 text-[12px] select-none cursor-pointer " +
        (disabled ? "opacity-50 pointer-events-none " : "") +
        (checked ? "text-ink-900" : "text-ink-600")
      }
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        disabled={disabled}
        className="accent-ink-900"
      />
      <I.Refresh size={12} className={checked ? "text-ink-900" : "text-ink-400"} />
      {label}
    </label>
  );
}

function SubSection({
  title,
  hint,
  children,
  collapsible,
  open,
  onToggle,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
  collapsible?: boolean;
  open?: boolean;
  onToggle?: () => void;
}) {
  return (
    <section className="mt-6">
      <div className="flex items-baseline gap-3 mb-2">
        {collapsible && onToggle ? (
          <button
            type="button"
            onClick={onToggle}
            className="flex items-baseline gap-3 hover:opacity-80 transition-opacity"
          >
            <I.Caret
              size={14}
              className={"transition-transform text-ink-500 " + (open ? "rotate-180" : "")}
            />
            <h3 className="text-sm font-semibold text-ink-900">{title}</h3>
            {hint && <span className="text-[11px] text-ink-500">{hint}</span>}
          </button>
        ) : (
          <>
            <h3 className="text-sm font-semibold text-ink-900">{title}</h3>
            {hint && <span className="text-[11px] text-ink-500">{hint}</span>}
          </>
        )}
      </div>
      {!collapsible || open ? children : null}
    </section>
  );
}

function FreshnessBar({ fresh }: { fresh: Freshness | null }) {
  if (!fresh) {
    return (
      <div className="text-xs text-ink-500 italic">Checking freshness…</div>
    );
  }
  const tone =
    fresh.status === "fresh"
      ? { bg: "bg-ok/[0.06]", border: "border-ok/30", text: "text-ok", label: "Up to date" }
      : fresh.status === "stale"
      ? { bg: "bg-warn/[0.06]", border: "border-warn/30", text: "text-warn", label: "Stale" }
      : { bg: "bg-rail", border: "border-edge", text: "text-ink-700", label: "Not generated" };
  const fmt = (ts?: number | null) => {
    if (!ts) return "—";
    const dt = new Date(ts * 1000);
    const now = Date.now() / 1000;
    const diff = now - ts;
    if (diff < 60) return `${Math.floor(diff)}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return dt.toLocaleString();
  };
  return (
    <div className={"rounded-md border px-3 py-2 " + tone.bg + " " + tone.border}>
      <div className="flex items-center gap-2">
        <span
          className={
            "inline-flex items-center justify-center w-5 h-5 rounded-full " +
            (fresh.status === "fresh"
              ? "bg-ok/10 text-ok"
              : fresh.status === "stale"
              ? "bg-warn/10 text-warn"
              : "bg-edge text-ink-500")
          }
        >
          {fresh.status === "fresh" ? <I.Check size={12} /> : <I.Dot size={12} />}
        </span>
        <span className={"text-sm font-medium " + tone.text}>{tone.label}</span>
        <span className="text-xs text-ink-500">{fresh.reason}</span>
      </div>
      {(fresh.newest_input || fresh.oldest_output) && (
        <div className="mt-1 grid grid-cols-2 gap-x-4 text-[11px] text-ink-500 font-mono">
          {fresh.newest_input && (
            <div>
              <span className="text-ink-300">newest input</span>{" "}
              <span className="text-ink-700">{fresh.newest_input.path}</span>{" "}
              <span>· {fmt(fresh.newest_input.mtime)}</span>
            </div>
          )}
          {fresh.oldest_output && (
            <div>
              <span className="text-ink-300">oldest output</span>{" "}
              <span className="text-ink-700">{fresh.oldest_output.path}</span>{" "}
              <span>· {fmt(fresh.oldest_output.mtime)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  tone,
  onClick,
  active,
}: {
  label: string;
  value: number;
  tone: "ok" | "warn" | "err" | "neutral";
  onClick?: () => void;
  active?: boolean;
}) {
  const ring =
    tone === "ok"
      ? "border-ok/30 bg-ok/[0.05]"
      : tone === "warn"
      ? "border-warn/30 bg-warn/[0.05]"
      : tone === "err"
      ? "border-err/30 bg-err/[0.05]"
      : "border-edge bg-rail";
  const num =
    tone === "ok"
      ? "text-ok"
      : tone === "warn"
      ? "text-warn"
      : tone === "err"
      ? "text-err"
      : "text-ink-900";
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={
        "text-left rounded-md border px-3 py-2 transition-shadow " +
        ring +
        (onClick ? " cursor-pointer hover:shadow-sm" : "") +
        (active ? " ring-2 ring-ink-300" : "")
      }
    >
      <div className="text-[11px] uppercase tracking-wide text-ink-500 flex items-center justify-between">
        <span>{label}</span>
        <I.Caret
          size={12}
          className={"transition-transform " + (active ? "rotate-180" : "opacity-40")}
        />
      </div>
      <div className={"text-2xl font-semibold mt-0.5 " + num}>{value}</div>
    </button>
  );
}

function SeverityDetail({
  severity,
  issues,
  onClose,
  onChangelogAdded,
}: {
  severity: Severity;
  issues: LintReport["issues"];
  onClose: () => void;
  onChangelogAdded?: () => void;
}) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [isAdding, setIsAdding] = useState(false);

  const accent =
    severity === "ERROR" ? "text-err" : severity === "WARNING" ? "text-warn" : "text-ink-700";
  // Group by sheet so the list reads like the build report.
  const bySheet = new Map<string, LintReport["issues"]>();
  for (const i of issues) {
    const arr = bySheet.get(i.sheet) ?? [];
    arr.push(i);
    bySheet.set(i.sheet, arr);
  }

  const toggleSelected = (index: number) => {
    setSelected((s) => {
      const ns = new Set(s);
      if (ns.has(index)) ns.delete(index);
      else ns.add(index);
      return ns;
    });
  };

  const addToChangelog = async () => {
    setIsAdding(true);
    try {
      for (const idx of selected) {
        const issue = issues[idx];
        const summary = `Fix "${issue.rule}" on ${issue.sheet}: ${issue.message}`;
        await api.changelogAdd(summary);
      }
      setSelected(new Set());
      onChangelogAdded?.();
    } catch (e) {
      console.error("Failed to add to changelog:", e);
    } finally {
      setIsAdding(false);
    }
  };

  return (
    <div className="mt-2 rounded-md border border-edge bg-white">
      <div className="flex items-center justify-between px-3 py-2 border-b border-edge">
        <div className="text-sm font-medium">
          <span className={accent}>{severity}</span>{" "}
          <span className="text-ink-500">
            — {issues.length} issue{issues.length === 1 ? "" : "s"}
            {selected.size > 0 && <span> ({selected.size} selected)</span>}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-ink-500 hover:text-ink-900 inline-flex items-center gap-1 text-xs"
        >
          <I.X size={12} /> close
        </button>
      </div>
      {issues.length === 0 ? (
        <div className="px-3 py-3 text-sm text-ink-500">
          No {severity.toLowerCase()} issues in the most recent build.
        </div>
      ) : (
        <>
          <div className="px-3 py-2 space-y-2 max-h-72 overflow-auto thin-scroll">
            {[...bySheet.entries()].map(([sheet, items]) => (
              <div key={sheet}>
                <div className="text-[11px] uppercase tracking-wide text-ink-500 mb-1">
                  {sheet}
                </div>
                <div className="space-y-1">
                  {items.map((h, i) => {
                    const globalIdx = issues.indexOf(h);
                    const isChecked = selected.has(globalIdx);
                    return (
                      <label
                        key={i}
                        className="text-[12.5px] text-ink-800 flex items-start gap-2 cursor-pointer hover:bg-ink-50 p-1 rounded -mx-1"
                      >
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => toggleSelected(globalIdx)}
                          className="mt-1 w-4 h-4"
                        />
                        <span
                          className={"inline-block w-1.5 h-1.5 rounded-full mt-1.5 " + SEV_DOT[h.severity]}
                        />
                        <span className="min-w-0">
                          <span className="font-mono text-[11px] text-ink-500">{h.rule}</span>{" "}
                          {h.message}
                          {h.refs.length > 0 && (
                            <span className="text-ink-500"> ({h.refs.join(", ")})</span>
                          )}
                        </span>
                      </label>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
          {selected.size > 0 && (
            <div className="px-3 py-2 border-t border-edge bg-ink-50">
              <button
                onClick={addToChangelog}
                disabled={isAdding}
                className="text-xs px-3 py-1.5 bg-ink-900 text-white rounded hover:bg-black disabled:opacity-50"
              >
                {isAdding ? "Adding..." : `Add ${selected.size} to changelog`}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
