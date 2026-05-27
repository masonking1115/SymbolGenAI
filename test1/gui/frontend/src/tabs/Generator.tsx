import { useCallback, useEffect, useMemo, useState } from "react";
import { api, subscribeAgent, subscribeRun } from "../api";
import { Console } from "../components/Console";
import { I } from "../components/Icon";
import type {
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
}: Props) {
  const [lines, setLines] = useState<string[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [runState, setRunState] = useState<RunState>("idle");
  const [lint, setLint] = useState<LintReport | null>(null);
  const [netlistFiles, setNetlistFiles] = useState<string[]>([]);
  const [fresh, setFresh] = useState<Freshness | null>(null);
  const [queuedCount, setQueuedCount] = useState(0);

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
  }, [refreshLint, refreshFresh, refreshChangelogCount]);

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

    // Stage 1+2: apply changelog (if any), then generate. Single backend
    // call orchestrates both runs.
    const { apply_run_id, generate_run_id } = await api.applyAndGenerate();

    if (apply_run_id) {
      setStage("applying-changelog");
      setSubPhase(`apply ${queuedCount} bullet${queuedCount === 1 ? "" : "s"}`);
      pushActivity(`▶ apply pass (${queuedCount} item${queuedCount === 1 ? "" : "s"})`);
      // Stream the agent's tool calls into the rail.
      await new Promise<void>((resolve) => {
        subscribeAgent(
          apply_run_id,
          (line) => {
            pushActivity(line);
            // Pull the trailing detail out of "tool: Edit file_path=…"
            // so the topbar hint shows the file being touched.
            const m = /^tool: (\w+)\s+(.*)$/.exec(line);
            if (m) setSubPhase(`${m[1]} ${m[2]}`.slice(0, 80));
          },
          ({ status }) => {
            pushActivity(`✓ apply ${status}`);
            resolve();
          },
        );
      });
    }

    setStage("generating");
    setSubPhase("starting gen_schematic.py");
    pushActivity("▶ gen_schematic.py");
    setRunId(generate_run_id);
    subscribeRun(
      generate_run_id,
      (line) => {
        setLines((prev) => [...prev, line]);
        pushActivity(line);
        // Surface "wrote <sheet>.kicad_sch" / "Phase N …" lines as the
        // sub-phase hint so the user can see progress in real time.
        const sheetM = /wrote\s+(\S+\.kicad_sch)/.exec(line);
        if (sheetM) {
          setSubPhase(`wrote ${sheetM[1]}`);
        } else if (line.startsWith("Phase ")) {
          setSubPhase(line.trim());
        } else if (/kicad-cli|export svg|render/.test(line.toLowerCase())) {
          setSubPhase("kicad-cli rendering PNGs");
        }
      },
      ({ status }) => {
        setRunState(status === "ok" ? "ok" : "fail");
        onArtifactsChanged();
        setStage("linting");
        setSubPhase("parsing lint report");
        pushActivity(`✓ generate ${status}`);
        // Slight delay so the file system catches up before re-fetching.
        setTimeout(() => {
          refreshLint();
          refreshFresh();
          refreshChangelogCount();
          // Pull the structured phases so the dropdown updates.
          api.runPhases(generate_run_id)
            .then((r) => setPhases(r.phases ?? []))
            .catch(() => {});
          setStage(status === "ok" ? "done" : "error");
          setSubPhase(undefined);
        }, 250);
      },
    );
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
        <SectionHeader
          eyebrow="Phase 2 · Schematic Generator"
          title="Build, render, and lint the schematic from the YAML netlists"
        />

        <div className="mt-4 grid grid-cols-3 gap-3">
          <StatCard label="ERRORs" value={counts.ERROR} tone={counts.ERROR ? "err" : "ok"} />
          <StatCard label="WARNINGs" value={counts.WARNING} tone={counts.WARNING ? "warn" : "ok"} />
          <StatCard label="INFOs" value={counts.INFO} tone="neutral" />
        </div>

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

        <SubSection title="Linter checklist" hint="layout_lint.py rules — pass when no issue fired">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2">
            {(lint?.rules ?? []).map((r) => {
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
                          className={
                            "px-1 rounded text-[9.5px] font-semibold uppercase tracking-wide " +
                            (r.severity === "ERROR"
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
                      <div className="mt-1 space-y-0.5">
                        {hits.slice(0, 4).map((h, i) => (
                          <div key={i} className="text-[11.5px] text-ink-700">
                            <span className={"inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle " + SEV_DOT[h.severity]} />
                            <span className="font-medium">[{h.sheet}]</span>{" "}
                            {h.message}
                            {h.refs.length > 0 && (
                              <span className="text-ink-500"> ({h.refs.join(", ")})</span>
                            )}
                          </div>
                        ))}
                        {hits.length > 4 && (
                          <div className="text-[11px] text-ink-500">
                            +{hits.length - 4} more
                          </div>
                        )}
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

function SectionHeader({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div>
      <div className="text-[11px] tracking-wide uppercase text-ink-500">{eyebrow}</div>
      <h2 className="text-[18px] font-semibold text-ink-900 mt-0.5">{title}</h2>
    </div>
  );
}

function SubSection({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-6">
      <div className="flex items-baseline gap-3 mb-2">
        <h3 className="text-sm font-semibold text-ink-900">{title}</h3>
        {hint && <span className="text-[11px] text-ink-500">{hint}</span>}
      </div>
      {children}
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
}: {
  label: string;
  value: number;
  tone: "ok" | "warn" | "err" | "neutral";
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
    <div className={"rounded-md border px-3 py-2 " + ring}>
      <div className="text-[11px] uppercase tracking-wide text-ink-500">{label}</div>
      <div className={"text-2xl font-semibold mt-0.5 " + num}>{value}</div>
    </div>
  );
}
