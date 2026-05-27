import type {
  ChangelogItem,
  ChatSession,
  ChatSessionMeta,
  DatasheetItem,
  FindingsReport,
  Freshness,
  LibraryPart,
  LintReport,
  RequirementDoc,
  RunHandle,
  RunStatus,
  RunSummary,
  SheetMeta,
  SimBlock,
  SimResult,
  SkillItem,
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

  chatSessions: () =>
    j<{ sessions: ChatSessionMeta[]; default_id: string | null }>(
      "/api/chat/sessions",
    ),
  chatSession: (id: string) =>
    j<ChatSession>(`/api/chat/sessions/${encodeURIComponent(id)}`),
  chatCreateSession: (title?: string) =>
    j<ChatSessionMeta>("/api/chat/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: title ?? null }),
    }),
  chatRenameSession: (id: string, title: string) =>
    j<{ ok: boolean }>(`/api/chat/sessions/${encodeURIComponent(id)}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  chatSetDefault: (id: string) =>
    j<{ ok: boolean }>(`/api/chat/sessions/${encodeURIComponent(id)}/default`, {
      method: "POST",
    }),
  chatClearSession: (id: string) =>
    j<{ ok: boolean }>(`/api/chat/sessions/${encodeURIComponent(id)}/clear`, {
      method: "POST",
    }),
  chatDeleteSession: (id: string) =>
    j<{ ok: boolean }>(`/api/chat/sessions/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  chatCompact: (id: string) =>
    j<{ run_id: string }>(
      `/api/chat/sessions/${encodeURIComponent(id)}/compact`,
      { method: "POST" },
    ),
  chatSend: (content: string, sessionId?: string) =>
    j<{ run_id: string; session_id: string }>("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, session_id: sessionId ?? null }),
    }),

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
  datasheetUrl: (mpn: string, name?: string) =>
    `/api/library/${encodeURIComponent(mpn)}/datasheet${
      name ? `?name=${encodeURIComponent(name)}` : ""
    }`,

  // ---- Design Resources ----
  resourcesDatasheets: () =>
    j<{ datasheets: DatasheetItem[] }>("/api/resources/datasheets"),
  uploadDatasheet: (mpn: string, filename: string, contentB64: string) =>
    j<{ ok: boolean; mpn: string; file: string; size: number }>(
      "/api/resources/datasheets",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mpn, filename, content_b64: contentB64 }),
      },
    ),
  resourcesRequirements: () =>
    j<{ active_md_exists: boolean; docs: RequirementDoc[] }>(
      "/api/resources/requirements",
    ),
  uploadRequirement: (filename: string, contentB64: string) =>
    j<{ ok: boolean; file: string; size: number }>(
      "/api/resources/requirements",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename, content_b64: contentB64 }),
      },
    ),
  requirementFileUrl: (name: string) =>
    `/api/resources/requirements/file?name=${encodeURIComponent(name)}`,
  resourcesSkills: () => j<{ skills: SkillItem[] }>("/api/resources/skills"),
  resourcesSkill: (slug: string) =>
    j<{ slug: string; content: string }>(
      `/api/resources/skills/${encodeURIComponent(slug)}`,
    ),
  saveSkill: (title: string, content: string, slug?: string) =>
    j<{ ok: boolean; slug: string }>("/api/resources/skills", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, content, slug: slug ?? null }),
    }),
  deleteSkill: (slug: string) =>
    j<{ ok: boolean }>(`/api/resources/skills/${encodeURIComponent(slug)}`, {
      method: "DELETE",
    }),

  simBlocks: () => j<{ blocks: SimBlock[] }>("/api/sim/blocks"),
  simRun: (block: string, simType: string, voutSet = 1.8) =>
    j<SimResult>("/api/sim/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ block, sim_type: simType, vout_set: voutSet }),
    }),
  simSetup: (block: string, simType: string) =>
    j<{ fresh: boolean; run_id?: string; skipped?: string }>("/api/sim/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ block, sim_type: simType }),
    }),
  simInterpret: (block: string, simType: string, voutSet = 1.8) =>
    j<{ run_id: string; sim_ok: boolean }>("/api/sim/interpret", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ block, sim_type: simType, vout_set: voutSet }),
    }),

  librarySymbol: (mpn: string) =>
    j<SymbolInfo>(`/api/library/${encodeURIComponent(mpn)}/symbol`),
  symbolSvgUrl: (mpn: string, unit: string) =>
    `/api/library/${encodeURIComponent(mpn)}/symbol/svg/${encodeURIComponent(unit)}`,
  uploadSymbol: (mpn: string, filename: string, contentB64: string) =>
    j<{ ok: boolean; mpn: string; symbols: string[]; size: number }>(
      `/api/library/${encodeURIComponent(mpn)}/symbol`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename, content_b64: contentB64 }),
      },
    ),
  // Deep link to the matching part on Ultra Librarian (free symbol/footprint
  // download in 30+ CAD formats incl. Altium). `queryText` is UL's search param.
  ultraLibrarianUrl: (mpn: string) =>
    `https://app.ultralibrarian.com/search?queryText=${encodeURIComponent(mpn)}`,
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
