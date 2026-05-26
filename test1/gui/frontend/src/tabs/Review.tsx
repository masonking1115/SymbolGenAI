import { useCallback, useEffect, useState } from "react";
import { api, subscribeRun } from "../api";
import { Console } from "../components/Console";
import { I } from "../components/Icon";
import type { Finding, FindingsReport, Severity } from "../types";

interface Props {
  onArtifactsChanged: () => void;
  setHealth: (h: { text: string; tone: "ok" | "warn" | "err" | "neutral" } | undefined) => void;
  /** Navigate back to the Generator tab after autofix completes. */
  onAutofixCompleted: () => void;
}

type RunState = "idle" | "running" | "ok" | "fail";

const SEV_TONE: Record<Severity, { dot: string; text: string }> = {
  ERROR: { dot: "bg-err", text: "text-err" },
  WARNING: { dot: "bg-warn", text: "text-warn" },
  INFO: { dot: "bg-ink-300", text: "text-ink-500" },
};

export function Review({ onArtifactsChanged, setHealth, onAutofixCompleted }: Props) {
  const [report, setReport] = useState<FindingsReport | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [runState, setRunState] = useState<RunState>("idle");
  const [errorLog, setErrorLog] = useState<string>("");

  const refresh = useCallback(async () => {
    try {
      const r = await api.findings();
      setReport(r);
      const s = r.summary;
      const tone = s.ERROR > 0 ? "err" : s.WARNING > 0 ? "warn" : "ok";
      setHealth({ text: `${s.ERROR}E · ${s.WARNING}W · ${s.INFO}I`, tone });
    } catch {
      // ignore
    }
    try {
      const e = await api.errorLog();
      setErrorLog(e.content || "");
    } catch {
      setErrorLog("");
    }
  }, [setHealth]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const startRun = async (autofix: boolean) => {
    setLines([]);
    setRunState("running");
    setHealth({ text: "running…", tone: "neutral" });
    const { run_id } = autofix
      ? await api.runAutofix()
      : await api.runReview();
    subscribeRun(
      run_id,
      (line) => setLines((prev) => [...prev, line]),
      ({ status }) => {
        setRunState(status === "ok" ? "ok" : "fail");
        onArtifactsChanged();
        setTimeout(() => {
          refresh();
          if (autofix && status === "ok") onAutofixCompleted();
        }, 250);
      },
    );
  };

  const sum = report?.summary ?? { ERROR: 0, WARNING: 0, INFO: 0 };
  const items: Finding[] = [...(report?.findings ?? []), ...(report?.semantic ?? [])];
  const isHealthy = sum.ERROR === 0 && sum.WARNING === 0 && sum.INFO === 0 && (report?.error_log_exists ?? false);

  return (
    <div className="h-full overflow-auto thin-scroll">
      <div className="px-6 py-5 max-w-[1100px]">
        <div className="text-[11px] tracking-wide uppercase text-ink-500">Phase 3 · Design Review</div>
        <h2 className="text-[18px] font-semibold text-ink-900 mt-0.5">
          Cross-reference schematic against datasheets + requirements
        </h2>

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
              <div className="text-[11px] uppercase tracking-wide">System</div>
              <div className="text-sm font-medium">
                {isHealthy ? "healthy" : "needs review"}
              </div>
            </div>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            onClick={() => startRun(false)}
            disabled={runState === "running"}
            className="h-9 px-3 inline-flex items-center gap-2 rounded-md bg-ink-900 text-white text-sm font-medium hover:bg-black disabled:opacity-50"
          >
            <I.Play size={14} /> Run review
          </button>
          <button
            onClick={() => startRun(true)}
            disabled={runState === "running"}
            className="h-9 px-3 inline-flex items-center gap-2 rounded-md border border-edge text-ink-700 text-sm hover:border-ink-300 disabled:opacity-50"
          >
            <I.Wrench size={14} /> Run review + autofix trivial
          </button>
          <button
            onClick={refresh}
            className="h-9 px-3 inline-flex items-center gap-2 rounded-md border border-edge text-ink-700 text-sm hover:border-ink-300"
          >
            <I.Refresh size={14} /> Refresh
          </button>
          <span className="text-xs text-ink-500 ml-2">
            After an autofix the GUI jumps back to Schematic Generator to re-lint.
          </span>
        </div>

        <section className="mt-6">
          <div className="flex items-baseline gap-3 mb-2">
            <h3 className="text-sm font-semibold text-ink-900">Findings</h3>
            <span className="text-[11px] text-ink-500">
              from review/findings.json + review/semantic_findings.json
            </span>
          </div>
          {items.length === 0 ? (
            <div className="rounded-md border border-edge bg-rail px-4 py-6 text-sm text-ink-500">
              No findings. Run review to populate, or — if the run was already clean — the design is currently green.
            </div>
          ) : (
            <div className="space-y-2">
              {items.map((f, i) => (
                <FindingRow key={i} f={f} />
              ))}
            </div>
          )}
        </section>

        <section className="mt-6">
          <div className="flex items-baseline gap-3 mb-2">
            <h3 className="text-sm font-semibold text-ink-900">Run output</h3>
            <span className="text-[11px] text-ink-500">stdout from run_review.py</span>
          </div>
          <Console lines={lines} status={runState} />
        </section>

        {errorLog && (
          <section className="mt-6">
            <div className="flex items-baseline gap-3 mb-2">
              <h3 className="text-sm font-semibold text-ink-900">error_log.md</h3>
              <span className="text-[11px] text-ink-500">latest report on disk</span>
            </div>
            <pre className="border border-edge rounded-md bg-white p-3 text-[12px] text-ink-700 whitespace-pre-wrap font-mono max-h-[400px] overflow-auto thin-scroll">
              {errorLog}
            </pre>
          </section>
        )}
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

function FindingRow({ f }: { f: Finding }) {
  const sev = ((f.severity as string) || "INFO").toUpperCase() as Severity;
  const tone = SEV_TONE[sev] ?? SEV_TONE.INFO;
  return (
    <div className="rounded-md border border-edge bg-white px-3 py-2.5">
      <div className="flex items-start gap-3">
        <span className={"mt-1.5 inline-block w-2 h-2 rounded-full " + tone.dot} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-xs">
            <span className={"font-medium " + tone.text}>{sev}</span>
            {f.category && (
              <span className="text-ink-500 font-mono">{f.category}</span>
            )}
            {(f.refs ?? []).length > 0 && (
              <span className="text-ink-500">· {(f.refs ?? []).join(", ")}</span>
            )}
            {f.source && (
              <span className="text-ink-500 ml-auto">{f.source}</span>
            )}
          </div>
          <div className="text-sm text-ink-900 mt-0.5">{f.message}</div>
          {f.detail && (
            <div className="text-xs text-ink-700 mt-1 whitespace-pre-wrap">
              {f.detail}
            </div>
          )}
          {f.fix_hint && (
            <div className="mt-1.5 text-[11.5px] text-ink-500 italic">
              hint: {f.fix_hint}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
