import type {
  ChangelogItem,
  ChatMessage,
  FindingsReport,
  Freshness,
  LibraryPart,
  LintReport,
  RunHandle,
  RunStatus,
  RunSummary,
  SheetMeta,
  SymbolInfo,
} from "./types";

const BASE = ""; // Vite dev proxy forwards /api to FastAPI.

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, init);
  if (!r.ok) throw new Error(`${path}: ${r.status} ${r.statusText}`);
  return r.json();
}

export const api = {
  health: () => j<{ ok: boolean; project: string }>("/api/health"),
  state: () => j<{ sheets: string[]; runs: unknown[] }>("/api/state"),
  sheets: () => j<{ sheets: SheetMeta[] }>("/api/sheets"),
  freshness: () => j<Freshness>("/api/freshness"),
  lint: (runId?: string) =>
    j<LintReport>(`/api/lint${runId ? `?run_id=${runId}` : ""}`),
  findings: () => j<FindingsReport>("/api/findings"),
  errorLog: () => j<{ content: string; exists: boolean }>("/api/error-log"),
  library: () => j<{ parts: LibraryPart[] }>("/api/library"),
  libraryItem: (mpn: string) =>
    j<{ mpn: string; datasheets: string[]; has_symbol: boolean }>(
      `/api/library/${encodeURIComponent(mpn)}`,
    ),
  netlistList: () => j<{ files: string[] }>("/api/netlist"),
  fileRead: (path: string) =>
    j<{ path: string; exists: boolean; content: string }>(
      `/api/file?path=${encodeURIComponent(path)}`,
    ),
  fileWrite: (path: string, content: string) =>
    j<{ ok: boolean }>("/api/file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, content }),
    }),
  requirements: () => j<{ exists: boolean; content: string }>("/api/requirements"),
  runGenerate: () =>
    j<RunHandle>("/api/run/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ no_reopen: true }),
    }),
  runReview: (opts: { autofix?: boolean; applyTrivial?: boolean } = {}) =>
    j<RunHandle>("/api/run/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        no_semantic: true,
        autofix: !!opts.autofix,
        apply_trivial: !!opts.applyTrivial,
      }),
    }),
  runAutofix: () =>
    j<RunHandle>("/api/run/autofix", { method: "POST" }),
  runStatus: (id: string) => j<RunStatus>(`/api/run/${id}`),
  runLatest: (kind: "generate" | "review" | "autofix" = "generate") =>
    j<RunSummary>(`/api/run/latest?kind=${kind}`),
  runPhases: (id: string) =>
    j<RunSummary>(`/api/run/${id}/phases`),

  chatHistory: () => j<{ messages: ChatMessage[] }>("/api/chat/history"),
  chatSend: (content: string) =>
    j<{ run_id: string }>("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }),
  chatClear: () =>
    j<{ ok: boolean }>("/api/chat/clear", { method: "POST" }),

  changelog: () => j<{ items: ChangelogItem[] }>("/api/changelog"),
  changelogAdd: (summary: string) =>
    j<ChangelogItem>("/api/changelog", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ summary }),
    }),
  changelogDelete: (id: string) =>
    j<{ ok: boolean }>(`/api/changelog/${id}`, { method: "DELETE" }),
  changelogClear: () =>
    j<{ ok: boolean }>("/api/changelog/clear", { method: "POST" }),

  applyAndGenerate: () =>
    j<{ apply_run_id: string | null; generate_run_id: string; queued_items: number }>(
      "/api/run/apply-and-generate",
      { method: "POST" },
    ),
  symbolGen: (mpn: string) =>
    j<{ run_id: string; datasheet: string }>(
      `/api/library/${encodeURIComponent(mpn)}/generate-symbol`,
      { method: "POST" },
    ),

  pngUrl: (sheet: string, bust?: number | string) =>
    `/api/png/${encodeURIComponent(sheet)}${bust !== undefined ? `?t=${bust}` : ""}`,
  datasheetUrl: (mpn: string) =>
    `/api/library/${encodeURIComponent(mpn)}/datasheet`,

  librarySymbol: (mpn: string) =>
    j<SymbolInfo>(`/api/library/${encodeURIComponent(mpn)}/symbol`),
  symbolSvgUrl: (mpn: string, unit: string) =>
    `/api/library/${encodeURIComponent(mpn)}/symbol/svg/${encodeURIComponent(unit)}`,
};

/** Subscribe to an agent run's SSE stream. */
export function subscribeAgent(
  runId: string,
  onLine: (line: string) => void,
  onDone?: (status: { status: string; rc: number | null; text?: string }) => void,
): () => void {
  const es = new EventSource(`/api/agent/${runId}/stream`);
  es.onmessage = (e) => {
    try {
      const j = JSON.parse(e.data);
      if (j.line !== undefined) onLine(j.line);
    } catch {
      // ignore
    }
  };
  es.addEventListener("done", (e: MessageEvent) => {
    try {
      onDone?.(JSON.parse(e.data));
    } catch {
      // ignore
    }
    es.close();
  });
  es.onerror = () => es.close();
  return () => es.close();
}

/** Subscribe to a run's SSE stream. Returns an unsubscribe function. */
export function subscribeRun(
  runId: string,
  onLine: (line: string) => void,
  onDone?: (status: { status: string; rc: number | null }) => void,
): () => void {
  const es = new EventSource(`/api/run/${runId}/stream`);
  es.onmessage = (e) => {
    try {
      const j = JSON.parse(e.data);
      if (j.line !== undefined) onLine(j.line);
    } catch {
      // ignore
    }
  };
  es.addEventListener("done", (e: MessageEvent) => {
    try {
      onDone?.(JSON.parse(e.data));
    } catch {
      // ignore
    }
    es.close();
  });
  es.onerror = () => {
    es.close();
  };
  return () => es.close();
}
