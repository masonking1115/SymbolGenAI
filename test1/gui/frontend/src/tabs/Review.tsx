import { useCallback, useEffect, useRef, useState } from "react";
import { api, subscribeRun } from "../api";
import { Console } from "../components/Console";
import { I } from "../components/Icon";
import type { Finding, FindingAction, FindingsReport, FixQueueEntry,
  Severity } from "../types";

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

// Map each finding's id -> its current queue entry (if any), so per-row UI can
// show a status badge without an extra fetch per row.
function indexQueue(q: FixQueueEntry[]): Map<string, FixQueueEntry> {
  const m = new Map<string, FixQueueEntry>();
  for (const e of q) m.set(e.finding_id, e);
  return m;
}

export function Review({ onArtifactsChanged, setHealth, onAutofixCompleted }: Props) {
  const [report, setReport] = useState<FindingsReport | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [runState, setRunState] = useState<RunState>("idle");
  const [errorLog, setErrorLog] = useState<string>("");
  const [queue, setQueue] = useState<Map<string, FixQueueEntry>>(new Map());
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string>("");
  const fileInputRef = useRef<HTMLInputElement | null>(null);

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
    try {
      const q = await api.fixQueue();
      setQueue(indexQueue(q.queue));
    } catch {
      // ignore
    }
  }, [setHealth]);

  // ---- Upload a review PDF (drag-drop or file-picker) -------------------
  const uploadPdf = useCallback(async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setUploadMsg(`'${file.name}' is not a PDF`);
      return;
    }
    setUploading(true);
    setUploadMsg(`uploading ${file.name}…`);
    try {
      const ab = await file.arrayBuffer();
      // base64-encode in-browser (chunked to avoid call-stack issues on
      // large files)
      const bytes = new Uint8Array(ab);
      let bin = "";
      for (let i = 0; i < bytes.length; i += 0x8000) {
        bin += String.fromCharCode.apply(
          null, Array.from(bytes.subarray(i, i + 0x8000)));
      }
      const b64 = btoa(bin);
      const r = await api.uploadReview(file.name, b64);
      const s = r.findings_after.summary;
      setUploadMsg(`parsed — ${s.ERROR}E / ${s.WARNING}W / ${s.INFO}I`);
      await refresh();
    } catch (e: unknown) {
      setUploadMsg(`upload failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setUploading(false);
    }
  }, [refresh]);

  const onDropZoneFile = (ev: React.ChangeEvent<HTMLInputElement>) => {
    const f = ev.target.files?.[0];
    if (f) void uploadPdf(f);
    ev.target.value = "";
  };
  const onDrop = (ev: React.DragEvent) => {
    ev.preventDefault();
    const f = ev.dataTransfer.files?.[0];
    if (f) void uploadPdf(f);
  };

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

        {/* ---- Drop a Voltai review PDF -------------------------------- */}
        <section className="mt-5">
          <label
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
            className={
              "block rounded-md border-2 border-dashed px-4 py-5 text-center cursor-pointer transition " +
              (uploading
                ? "border-ink-300 bg-rail/60 text-ink-500"
                : "border-edge hover:border-ink-300 hover:bg-rail/40 text-ink-700")
            }
          >
            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf,.pdf"
              className="hidden"
              onChange={onDropZoneFile}
              disabled={uploading}
            />
            <div className="flex items-center justify-center gap-2 text-sm">
              <I.Upload size={14} />
              <span>
                {uploading
                  ? "Parsing…"
                  : "Drop a Voltai review PDF here, or click to pick a file"}
              </span>
            </div>
            <div className="mt-1 text-[11px] text-ink-500">
              Saved into <code>_review_incoming/</code> and parsed via{" "}
              <code>install_review.py</code>. Findings appear below on success.
            </div>
            {uploadMsg && (
              <div className="mt-2 text-[11px] text-ink-700">{uploadMsg}</div>
            )}
          </label>
        </section>

        <section className="mt-6">
          <div className="flex items-baseline gap-3 mb-2">
            <h3 className="text-sm font-semibold text-ink-900">Findings</h3>
            <span className="text-[11px] text-ink-500">
              from review/findings.json + review/semantic_findings.json
            </span>
          </div>
          {items.length === 0 ? (
            <div className="rounded-md border border-edge bg-rail px-4 py-6 text-sm text-ink-500">
              No findings. Run review or drop a review PDF above; the design is currently green if both come back empty.
            </div>
          ) : (
            <div className="space-y-2">
              {items.map((f, i) => (
                <FindingRow
                  key={f.id ?? i}
                  f={f}
                  queued={f.id ? queue.get(f.id) : undefined}
                  onApply={onApply}
                  onDismiss={onDismiss}
                />
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

interface FindingRowProps {
  f: Finding;
  queued?: FixQueueEntry;
  onApply: (f: Finding, a: FindingAction, idx: number) => void;
  onDismiss: (f: Finding) => void;
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

function FindingRow({ f, queued, onApply, onDismiss }: FindingRowProps) {
  const sev = ((f.severity as string) || "INFO").toUpperCase() as Severity;
  const tone = SEV_TONE[sev] ?? SEV_TONE.INFO;
  const actions: FindingAction[] = (f.actions as FindingAction[]) ?? [];
  // Default-select the first "fix" action; fall back to first item.
  const defaultIdx = Math.max(
    0, actions.findIndex((a) => a.kind === "fix"));
  const [picked, setPicked] = useState<number>(defaultIdx);
  const [expanded, setExpanded] = useState<boolean>(false);
  const status = queued?.status;
  const statusTone = status ? STATUS_TONE[status] : undefined;

  return (
    <div className="rounded-md border border-edge bg-white px-3 py-2.5">
      <div className="flex items-start gap-3">
        <span className={"mt-1.5 inline-block w-2 h-2 rounded-full " + tone.dot} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-xs flex-wrap">
            <span className={"font-medium " + tone.text}>{sev}</span>
            {f.component && (
              <span className="text-ink-900 font-mono font-medium">
                {f.component}
              </span>
            )}
            {f.category && (
              <span className="text-ink-500">· {f.category}</span>
            )}
            {(f.refs ?? []).length > 0 && (
              <span className="text-ink-500 truncate max-w-[40%]">
                · {(f.refs ?? []).join(", ")}
              </span>
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
              <span
                className={
                  "text-[10px] rounded px-1.5 py-0.5 ml-auto " +
                  statusTone.bg + " " + statusTone.text
                }
              >
                {statusTone.label}
              </span>
            )}
            {!statusTone && f.source && (
              <span className="text-ink-500 ml-auto">{f.source}</span>
            )}
          </div>
          <div className="text-sm text-ink-900 mt-0.5">{f.message}</div>

          {/* Action items: expanded picker; default-selected first Fix.   */}
          {actions.length > 0 && (
            <div className="mt-2 space-y-1">
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
                      <span className="font-mono uppercase text-[10px] mr-1.5 text-ink-500">
                        {a.kind}
                      </span>
                      <span className="text-ink-900">{a.text}</span>
                    </div>
                  </div>
                </label>
              ))}
              <div className="flex items-center gap-2 mt-1">
                <button
                  onClick={() => onApply(f, actions[picked], picked)}
                  disabled={!f.id || status === "queued" || status === "applied"}
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
                <button
                  onClick={() => setExpanded((v) => !v)}
                  className="h-7 px-2 text-[11.5px] text-ink-500 hover:text-ink-900 ml-auto"
                >
                  {expanded ? "hide details" : "details"}
                </button>
              </div>
            </div>
          )}

          {/* Fallback: legacy single fix_hint for findings without an
              actions array (KiCad path). */}
          {actions.length === 0 && f.fix_hint && (
            <div className="mt-1.5 text-[11.5px] text-ink-500 italic">
              hint: {f.fix_hint}
            </div>
          )}

          {expanded && f.detail && (
            <div className="text-xs text-ink-700 mt-2 whitespace-pre-wrap border-t border-edge pt-2">
              {f.detail}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
