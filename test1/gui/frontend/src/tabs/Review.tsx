import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { DiffAndAccept } from "../components/DiffAndAccept";
import type { DiffMode } from "../components/DiffPanes";
import { FindingsSummary } from "../components/FindingsSummary";
import { I } from "../components/Icon";
import { LoopTick } from "../components/LoopTick";
import { PageHeader } from "../components/PageHeader";
import { RoundsPicker } from "../components/RoundsPicker";
import { WorkflowSection } from "../components/WorkflowSection";
import { RulesSection } from "../components/RulesSection";
import type { Finding, FindingAction, FindingsReport, FixQueueEntry,
  LoopSummary, Severity } from "../types";

// Diff data shape mirrored from DiffPanes for the controls' props. Kept inline
// to avoid pulling the visual-pane module into this tab's import graph.
interface DiffData {
  loop_id: string;
  sheets: Record<string, {
    viewBox: string;
    added: Record<string, { x: number; y: number; kind: "added" }>;
    removed: Record<string, { x: number; y: number; kind: "removed" }>;
    changed: Record<string, { x: number; y: number; kind: "changed"; from_value: string; to_value: string }>;
    count: number;
    renderable?: boolean;
    unrenderable_reason?: string;
  }>;
}

interface Props {
  onArtifactsChanged: () => void;
  setHealth: (h: { text: string; tone: "ok" | "warn" | "err" | "neutral" } | undefined) => void;
  /** Bumped (App's `bust`) whenever the design artifacts change — a build /
   *  generate / loop. Re-fetch findings so the Review header never goes stale
   *  relative to the current build (the cross-tab consistency fix). */
  refreshSignal?: number;
  /** Navigate back to the Generator tab after autofix completes. */
  // Loop state lifted to App.tsx so the right pane can swap PngViewer for
  // DiffPanes when a completed loop is awaiting accept/reject.
  activeLoopId: string | null;
  setActiveLoopId: (id: string | null) => void;
  loopSummary: LoopSummary | null;
  setLoopSummary: (s: LoopSummary | null) => void;
  loopDiff: DiffData | null;
  diffSheet: string | null;
  setDiffSheet: (s: string) => void;
  diffMode: DiffMode;
  setDiffMode: (m: DiffMode) => void;
  // Right-pane diff-view gating. hasRealDiff = at least one sheet has changes.
  // diffVisible = current effective visibility (auto OR override). The setter
  // accepts null to clear the override (revert to auto).
  hasRealDiff: boolean;
  diffVisible: boolean;
  setDiffVisibleOverride: (v: boolean | null) => void;
}

type RunState = "idle" | "running" | "ok" | "fail";

const SEV_TONE: Record<Severity, { dot: string; text: string }> = {
  ERROR: { dot: "bg-err", text: "text-err" },
  WARNING: { dot: "bg-warn", text: "text-warn" },
  INFO: { dot: "bg-ink-300", text: "text-ink-500" },
};

// Map each finding's id -> its current queue entry (if any), so per-row UI can
// show a status badge without an extra fetch per row.
function indexQueue(q: FixQueueEntry[]): Map<string, FixQueueEntry> {
  const m = new Map<string, FixQueueEntry>();
  for (const e of q) m.set(e.finding_id, e);
  return m;
}

export function Review({
  onArtifactsChanged, setHealth, refreshSignal,
  activeLoopId, setActiveLoopId, loopSummary, setLoopSummary,
  loopDiff, diffSheet, setDiffSheet, diffMode, setDiffMode,
  hasRealDiff, diffVisible, setDiffVisibleOverride,
}: Props) {
  const [report, setReport] = useState<FindingsReport | null>(null);
  const [runState, setRunState] = useState<RunState>("idle");
  // How many rounds the closed-loop review may run (1–10; 3 recommended).
  const [reviewRounds, setReviewRounds] = useState(3);
  // Run mode (mirrors the Generator's loopMode):
  //   "review_only"     — evaluate + report findings, run NO fix rounds.
  //   "errors"          — auto-fix loop until ERROR findings clear (default).
  //   "errors_warnings" — auto-fix loop until ERROR + WARNING findings clear.
  const [reviewMode, setReviewMode] = useState<"review_only" | "errors" | "errors_warnings">("errors");
  const [queue, setQueue] = useState<Map<string, FixQueueEntry>>(new Map());

  const refresh = useCallback(async () => {
    try {
      const r = await api.findings();
      setReport(r);
      const s = r.summary;
      const tone = s.ERROR > 0 ? "err" : s.WARNING > 0 ? "warn" : "ok";
      // Prefix the source so this never reads as "the same status" as the
      // Generator's layout-lint counts (the two measure different things:
      // review = rule/semantic findings, generator = geometric lint).
      setHealth({ text: `review: ${s.ERROR}E · ${s.WARNING}W · ${s.INFO}I`, tone });
    } catch {
      // ignore
    }
    try {
      const q = await api.fixQueue();
      setQueue(indexQueue(q.queue));
    } catch {
      // ignore
    }
  }, [setHealth]);

  // ---- Per-finding apply / dismiss --------------------------------------
  const onApply = useCallback(async (f: Finding, a: FindingAction, idx: number) => {
    if (!f.id) return;
    await api.applyFinding(f.id, idx, a.kind, a.text);
    await refresh();
  }, [refresh]);
  const onDismiss = useCallback(async (f: Finding) => {
    if (!f.id) return;
    await api.dismissFix(f.id);
    await refresh();
  }, [refresh]);

  // Closed-loop findings have no action list — "Apply suggested fix" drops the
  // hint into the changelog (tagged closed_loop) so the existing Regenerate /
  // apply-and-generate machinery picks it up (apply -> build -> re-eval). We
  // build a self-contained instruction so the apply agent has full context.
  const onApplyToChangelog = useCallback(async (f: Finding, fix: string) => {
    const rid = (f.rule_id as string) || "";
    const subj = (f.component as string) || (f.sheet as string) || "";
    const title = (f.title as string) || f.message || f.rule || "";
    const summary = [
      rid && `[${rid}]`,
      subj && `${subj}:`,
      fix,
      title && `(finding: ${title})`,
    ].filter(Boolean).join(" ");
    await api.changelogAdd(summary, { source: "closed_loop" });
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Re-fetch findings when the design artifacts change elsewhere (build / generate
  // / loop bumps refreshSignal), so the Review header stays in sync with the
  // current build instead of showing stale findings from a prior state.
  useEffect(() => {
    if (refreshSignal === undefined) return;
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal]);

  // Re-attach to the most recent loop on mount (so reload doesn't lose state).
  // Skip if a fresh start has already populated activeLoopId.
  useEffect(() => {
    if (activeLoopId) return;
    void api.loopLatest().then((l) => {
      if ("loop_id" in l && l.loop_id) setActiveLoopId(l.loop_id);
    }).catch(() => { /* ignore */ });
    // Intentionally empty deps: only run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Stable callbacks passed to IterationSection + DiffAndAccept. Without
  // useCallback these would be fresh fns on every render, and the children's
  // effects (with these in deps) would re-subscribe to SSE / refetch on every
  // parent render — causing a fetch loop + visible schematic flicker.
  const onLoopCompleted = useCallback((status: string) => {
    setRunState(status === "all_clear" ? "ok" : "fail");
    onArtifactsChanged();
  }, [onArtifactsChanged]);
  const onDiffResolved = useCallback(() => {
    setActiveLoopId(null);
    onArtifactsChanged();
  }, [onArtifactsChanged]);

  const startLoop = async () => {
    setRunState("running");
    setHealth({ text: "loop starting…", tone: "neutral" });
    try {
      const { loop_id } = await api.loopStart(reviewRounds, {
        fixWarnings: reviewMode === "errors_warnings",
        reviewOnly: reviewMode === "review_only",
      });
      setActiveLoopId(loop_id);
      // The loop can finish almost instantly when the design already passes
      // every rule (0 findings → 0 rounds → all_clear in ~100ms). In that case
      // the SSE may deliver only a terminal frame; fetch the summary directly so
      // the Iteration panel always shows a result (and runState resolves) rather
      // than appearing to do "nothing".
      try {
        const s = await api.loopGet(loop_id);
        if (s.status !== "running") onLoopCompleted(s.status);
      } catch {
        /* IterationSection's own fetch/subscribe will still populate it */
      }
    } catch {
      setHealth({ text: "loop start failed", tone: "err" });
      setRunState("fail");
    }
  };

  const sum = report?.summary ?? { ERROR: 0, WARNING: 0, INFO: 0 };
  const items: Finding[] = [...(report?.findings ?? []), ...(report?.semantic ?? [])];
  // Healthy = no findings of any severity. (Previously also required
  // error_log.md to exist, but the closed-loop review never writes that file —
  // only the legacy CLI did — so the badge could never turn green. Dropped.)
  const isHealthy = sum.ERROR === 0 && sum.WARNING === 0 && sum.INFO === 0;

  return (
    <div className="h-full overflow-auto thin-scroll">
      <div className="px-6 py-5 max-w-[1100px]">
        <PageHeader
          eyebrow="Phase 3 · Design Review"
          title="Cross-reference schematic against datasheets + requirements"
        />

        <div className="mt-4 grid grid-cols-4 gap-3">
          <Stat label="ERRORs" v={sum.ERROR} tone={sum.ERROR ? "err" : "ok"} />
          <Stat label="WARNINGs" v={sum.WARNING} tone={sum.WARNING ? "warn" : "ok"} />
          <Stat label="INFOs" v={sum.INFO} tone="neutral" />
          <div
            className={
              "rounded-md border px-3 py-2 flex items-center gap-2 " +
              (isHealthy
                ? "border-ok/30 bg-ok/[0.05] text-ok"
                : "border-edge bg-rail text-ink-700")
            }
          >
            <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-white/70">
              {isHealthy ? <I.Check size={12} /> : <I.Dot size={12} />}
            </span>
            <div>
              <div className="text-[11px] uppercase tracking-wide" title="Status of the design-review rules/findings — separate from the Generator's layout-lint">Review findings</div>
              <div className="text-sm font-medium">
                {isHealthy ? "all clear" : "needs review"}
              </div>
            </div>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            onClick={startLoop}
            disabled={runState === "running"}
            className="h-9 px-3 inline-flex items-center gap-2 rounded-md bg-ink-900 text-white text-sm font-medium hover:bg-black disabled:opacity-50"
          >
            <I.Play size={14} /> {reviewMode === "review_only" ? "Run review" : "Design review"}
          </button>
          {/* Run-mode ticks (mirror the Generator). review_only is the implicit
              base state; ticking a fix scope flips it on, re-ticking returns to
              review-only. Mutually exclusive. */}
          <LoopTick
            label="Auto-fix errors"
            title="After evaluating the rules, an agent fixes the ERROR findings, rebuilds, and re-checks (up to the chosen number of rounds). WARNING/INFO stay advisory. Untick for review-only (evaluate + report, no edits)."
            checked={reviewMode === "errors"}
            disabled={runState === "running"}
            onToggle={() => setReviewMode((m) => (m === "errors" ? "review_only" : "errors"))}
          />
          <LoopTick
            label="Auto-fix errors + warnings"
            title="Same auto-fix loop, but the agent also clears every WARNING finding — it keeps fixing and rebuilding until both ERRORs and WARNINGs reach zero. INFO stays advisory."
            checked={reviewMode === "errors_warnings"}
            disabled={runState === "running"}
            onToggle={() => setReviewMode((m) => (m === "errors_warnings" ? "review_only" : "errors_warnings"))}
          />
          <RoundsPicker
            value={reviewRounds}
            onChange={setReviewRounds}
            disabled={runState === "running" || reviewMode === "review_only"}
          />
          <button
            onClick={refresh}
            className="h-9 px-3 inline-flex items-center gap-2 rounded-md border border-edge text-ink-700 text-sm hover:border-ink-300"
          >
            <I.Refresh size={14} /> Refresh
          </button>
          <span className="text-xs text-ink-500 ml-2">
            {reviewMode === "review_only"
              ? "Run review evaluates every rule and reports findings — no edits, no rebuild."
              : "Design review runs the closed loop: evaluate rules → auto-correct findings → rebuild → re-check, then Diff & Accept."}
          </span>
        </div>

        <RulesSection
          loopRunning={runState === "running"}
        />

        <WorkflowSection
          loopId={activeLoopId}
          onLoopCompleted={onLoopCompleted}
          setHealth={setHealth}
          onSummary={setLoopSummary}
        />

        {activeLoopId && loopSummary && loopSummary.status !== "running" && loopDiff && (
          <DiffAndAccept
            loopId={activeLoopId}
            loopStatus={loopSummary.status}
            diff={loopDiff}
            activeSheet={diffSheet}
            setActiveSheet={setDiffSheet}
            mode={diffMode}
            setMode={setDiffMode}
            hasRealDiff={hasRealDiff}
            diffVisible={diffVisible}
            setDiffVisibleOverride={setDiffVisibleOverride}
            onResolved={onDiffResolved}
          />
        )}

        <section className="mt-6">
          <div className="flex items-baseline gap-3 mb-2">
            <h3 className="text-sm font-semibold text-ink-900">Findings</h3>
            <span className="text-[11px] text-ink-500">
              from review/findings.json + review/semantic_findings.json
            </span>
          </div>
          {items.length === 0 ? (
            <div className="rounded-md border border-edge bg-rail px-4 py-6 text-sm text-ink-500">
              No findings. Run review above; the design is currently green if it comes back empty.
            </div>
          ) : (
            <>
              <FindingsSummary items={items} />
              <div className="space-y-2">
              {items.map((f, i) => (
                <FindingRow
                  key={f.id ?? i}
                  f={f}
                  queued={f.id ? queue.get(f.id) : undefined}
                  loopRunning={runState === "running"}
                  onApply={onApply}
                  onDismiss={onDismiss}
                  onApplyToChangelog={onApplyToChangelog}
                />
              ))}
              </div>
            </>
          )}
        </section>

      </div>
    </div>
  );
}

function Stat({
  label,
  v,
  tone,
}: {
  label: string;
  v: number;
  tone: "ok" | "warn" | "err" | "neutral";
}) {
  const ring =
    tone === "ok" ? "border-ok/30 bg-ok/[0.05]" :
    tone === "warn" ? "border-warn/30 bg-warn/[0.05]" :
    tone === "err" ? "border-err/30 bg-err/[0.05]" :
    "border-edge bg-rail";
  const num =
    tone === "ok" ? "text-ok" :
    tone === "warn" ? "text-warn" :
    tone === "err" ? "text-err" :
    "text-ink-900";
  return (
    <div className={"rounded-md border px-3 py-2 " + ring}>
      <div className="text-[11px] uppercase tracking-wide text-ink-500">{label}</div>
      <div className={"text-2xl font-semibold mt-0.5 " + num}>{v}</div>
    </div>
  );
}

interface FindingRowProps {
  f: Finding;
  queued?: FixQueueEntry;
  loopRunning: boolean;
  onApply: (f: Finding, a: FindingAction, idx: number) => void;
  onDismiss: (f: Finding) => void;
  onApplyToChangelog: (f: Finding, fix: string) => Promise<void>;
}

const STATUS_TONE: Record<string, { bg: string; text: string; label: string }> = {
  queued:    { bg: "bg-warn/15",  text: "text-warn",    label: "queued for agent" },
  applied:   { bg: "bg-ok/15",    text: "text-ok",      label: "applied" },
  failed:    { bg: "bg-err/15",   text: "text-err",     label: "apply failed" },
  dismissed: { bg: "bg-ink-100",  text: "text-ink-500", label: "dismissed" },
};

const ACTION_TONE: Record<string, string> = {
  fix:    "border-ok/40 bg-ok/[0.05]",
  alt:    "border-warn/40 bg-warn/[0.04]",
  verify: "border-edge bg-rail/40",
};

// Pull a readable string off a Finding by key, tolerating the `unknown` index
// signature (closed-loop findings carry observed/impact/title/sheet there).
function fstr(f: Finding, key: string): string | undefined {
  const v = (f as Record<string, unknown>)[key];
  return typeof v === "string" && v.trim() ? v.trim() : undefined;
}

function FindingRow({ f, queued, loopRunning, onApply, onDismiss, onApplyToChangelog }: FindingRowProps) {
  const sev = ((f.severity as string) || "INFO").toUpperCase() as Severity;
  const tone = SEV_TONE[sev] ?? SEV_TONE.INFO;
  const actions: FindingAction[] = (f.actions as FindingAction[]) ?? [];
  // Default-select the first "fix" action; fall back to first item.
  const defaultIdx = Math.max(
    0, actions.findIndex((a) => a.kind === "fix"));
  const [picked, setPicked] = useState<number>(defaultIdx);
  const [open, setOpen] = useState<boolean>(false);
  // Local lifecycle for the "Apply suggested fix" → changelog button (the
  // changelog is a flat list, not per-finding, so this row owns its own state).
  const [clState, setClState] = useState<"idle" | "adding" | "added" | "error">("idle");
  const status = queued?.status;
  const statusTone = status ? STATUS_TONE[status] : undefined;

  // Headline: the closed-loop writes the descriptive text in `title`; the
  // PDF/linter path uses `message`. Show whichever exists, title first.
  const headline = fstr(f, "title") || f.message || f.rule || "(finding)";

  // Suggested fix: prefer an explicit "fix" action's text, else the fix_hint.
  const fixAction = actions.find((a) => a.kind === "fix");
  const suggestedFix = fixAction?.text || fstr(f, "fix_hint");

  // Extra structured context (closed-loop). Only render rows that exist.
  const observed = fstr(f, "observed");
  const impact = fstr(f, "impact");
  const sheet = fstr(f, "sheet");
  const detail = fstr(f, "detail");
  // Anything worth expanding for?
  const hasDetail =
    !!suggestedFix || !!observed || !!impact || !!detail ||
    actions.length > 0 || (f.refs ?? []).length > 0;

  return (
    <div className="rounded-md border border-edge bg-white overflow-hidden">
      {/* ── Header (always visible; the click target that toggles details) ── */}
      <button
        type="button"
        onClick={() => hasDetail && setOpen((v) => !v)}
        className={
          "w-full text-left flex items-start gap-2.5 px-3 py-2.5 " +
          (hasDetail ? "cursor-pointer hover:bg-rail/30" : "cursor-default")
        }
        aria-expanded={open}
      >
        {hasDetail ? (
          <I.Caret
            size={11}
            className={"mt-1 shrink-0 text-ink-400 transition-transform " + (open ? "rotate-180" : "")}
          />
        ) : (
          <span className="mt-1 w-[11px] shrink-0" />
        )}
        <span className={"mt-1 inline-block w-2 h-2 rounded-full shrink-0 " + tone.dot} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-xs flex-wrap">
            <span className={"font-medium " + tone.text}>{sev}</span>
            {f.component && (
              <span className="text-ink-900 font-mono font-medium">{f.component}</span>
            )}
            {f.category && <span className="text-ink-500">· {f.category}</span>}
            {f.rule_id && (
              <span className="text-[10px] font-mono text-ink-500 bg-rail/40 rounded px-1">
                {f.rule_id}
              </span>
            )}
            {f.iteration_round !== undefined && (
              <span className="text-[10px] text-ink-500">round {f.iteration_round}</span>
            )}
            {(f.fired_count ?? 1) > 1 && (
              <span
                className="text-[10px] text-ink-500 border border-edge rounded px-1"
                title="The review tool emitted this rule this many times"
              >
                ×{f.fired_count}
              </span>
            )}
            {statusTone && (
              <span className={"text-[10px] rounded px-1.5 py-0.5 ml-auto " + statusTone.bg + " " + statusTone.text}>
                {statusTone.label}
              </span>
            )}
            {!statusTone && f.source && (
              <span className="text-ink-500 ml-auto">{f.source}</span>
            )}
          </div>
          {/* One-line headline (clamped) when collapsed; full text when open. */}
          <div className={"text-sm text-ink-900 mt-0.5 " + (open ? "" : "truncate")}>
            {headline}
          </div>
          {/* A peek at the fix even when collapsed, so the row is actionable
              at a glance — full fix lives in the expanded panel. */}
          {!open && suggestedFix && (
            <div className="text-[11.5px] text-ink-500 italic mt-0.5 truncate">
              fix: {suggestedFix}
            </div>
          )}
        </div>
      </button>

      {/* ── Expanded detail: Suggested fix + structured context + actions ── */}
      {open && hasDetail && (
        <div className="px-3 pb-3 pt-0 border-t border-edge/60 space-y-2.5">
          {/* Suggested fix — the headline of the dropdown. For closed-loop
              findings (no explicit action list) this also offers an inline
              "Apply" that queues the hint for the chat agent to implement. */}
          {suggestedFix && (
            <div className="mt-2.5 rounded-md border border-ok/30 bg-ok/[0.05] px-2.5 py-2">
              <div className="flex items-center gap-1.5 text-[11px] font-medium text-ok mb-0.5">
                <I.Wrench size={12} /> Suggested fix
              </div>
              <div className="text-[12.5px] text-ink-900">{suggestedFix}</div>
              {/* Only when there's no explicit action picker below — otherwise
                  the picker's Apply button is the canonical control. This adds
                  the fix to the changelog; Regenerate then applies + rebuilds. */}
              {actions.length === 0 && (
                <div className="flex items-center gap-2 mt-2 flex-wrap">
                  <button
                    onClick={async () => {
                      setClState("adding");
                      try {
                        await onApplyToChangelog(f, suggestedFix);
                        setClState("added");
                      } catch {
                        setClState("error");
                      }
                    }}
                    disabled={clState === "adding" || clState === "added" || loopRunning}
                    className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md bg-ink-900 text-white text-[11.5px] font-medium hover:bg-black disabled:opacity-50"
                    title="Add this fix to the changelog; Regenerate then applies it (apply → build → re-eval)"
                  >
                    <I.Wrench size={12} />
                    {clState === "adding" ? "Adding…" :
                     clState === "added" ? "Added to changelog" :
                     "Apply suggested fix"}
                  </button>
                  {clState === "added" && (
                    <span className="text-[11px] text-ok inline-flex items-center gap-1">
                      <I.Check size={12} /> queued — hit Regenerate to apply
                    </span>
                  )}
                  {clState === "error" && (
                    <span className="text-[11px] text-err">couldn't add — try again</span>
                  )}
                  {clState === "idle" && loopRunning && (
                    <span className="text-[10.5px] text-ink-400">loop running…</span>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Structured context fields (closed-loop). */}
          {(observed || impact || sheet || (f.refs ?? []).length > 0) && (
            <dl className="text-[12px] grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
              {observed && (
                <>
                  <dt className="text-ink-500">Observed</dt>
                  <dd className="text-ink-800 whitespace-pre-wrap">{observed}</dd>
                </>
              )}
              {impact && (
                <>
                  <dt className="text-ink-500">Impact</dt>
                  <dd className="text-ink-800 whitespace-pre-wrap">{impact}</dd>
                </>
              )}
              {sheet && (
                <>
                  <dt className="text-ink-500">Sheet</dt>
                  <dd className="text-ink-800 font-mono">{sheet}</dd>
                </>
              )}
              {(f.refs ?? []).length > 0 && (
                <>
                  <dt className="text-ink-500">Refs</dt>
                  <dd className="text-ink-800 font-mono">{(f.refs ?? []).join(", ")}</dd>
                </>
              )}
            </dl>
          )}

          {/* Action picker (PDF-parser findings carry Fix/Alt/Verify options). */}
          {actions.length > 0 && (
            <div className="space-y-1">
              {actions.map((a, i) => (
                <label
                  key={i}
                  className={
                    "block rounded border px-2 py-1.5 text-[11.5px] cursor-pointer transition " +
                    (picked === i
                      ? (ACTION_TONE[a.kind] ?? "border-ink-300 bg-rail/40")
                      : "border-edge hover:border-ink-300")
                  }
                >
                  <div className="flex items-start gap-2">
                    <input
                      type="radio"
                      className="mt-0.5"
                      name={`action-${f.id}`}
                      checked={picked === i}
                      onChange={() => setPicked(i)}
                    />
                    <div className="min-w-0">
                      <span className="font-mono uppercase text-[10px] mr-1.5 text-ink-500">{a.kind}</span>
                      <span className="text-ink-900">{a.text}</span>
                    </div>
                  </div>
                </label>
              ))}
              <div className="flex items-center gap-2 mt-1">
                <button
                  onClick={() => onApply(f, actions[picked], picked)}
                  disabled={!f.id || status === "queued" || status === "applied" || loopRunning}
                  className="h-7 px-2.5 inline-flex items-center gap-1 rounded-md bg-ink-900 text-white text-[11.5px] font-medium hover:bg-black disabled:opacity-50"
                >
                  <I.Wrench size={12} />
                  {status === "queued" ? "Queued" :
                   status === "applied" ? "Applied" :
                   `Apply ${actions[picked]?.kind ?? "fix"}`}
                </button>
                {status === "queued" && (
                  <button
                    onClick={() => onDismiss(f)}
                    className="h-7 px-2 text-[11.5px] text-ink-500 hover:text-ink-900"
                  >
                    cancel
                  </button>
                )}
              </div>
            </div>
          )}

          {detail && (
            <div className="text-xs text-ink-700 whitespace-pre-wrap border-t border-edge pt-2">
              {detail}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
