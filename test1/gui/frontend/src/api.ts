import type {
  ChangelogItem,
  ChatSession,
  ChatSessionMeta,
  Circuit,
  DatasheetItem,
  FindingsReport,
  FixQueueEntry,
  Freshness,
  LibraryPart,
  LintReport,
  RequirementDoc,
  RunHandle,
  RunStatus,
  RunSummary,
  AgentModelConfig,
  SheetMeta,
  SimBlock,
  SimGroup,
  SimRequirements,
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
  refresh: () => j<{ ok: boolean; lint: LintReport; sheets: { sheets: SheetMeta[] }; findings: FindingsReport; timestamp: number }>("/api/refresh", { method: "POST" }),
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

  // ---- Voltai PDF review ingest + Apply-fix queue --------------------
  uploadReview: (filename: string, contentB64: string) =>
    j<{ ok: boolean; file: string; size: number; parse_log: string;
        findings_after: FindingsReport }>("/api/review/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename, content_b64: contentB64 }),
    }),
  applyFinding: (findingId: string, actionIndex: number,
                 actionKind = "", actionText = "") =>
    j<{ ok: boolean; queued: number; finding_id: string }>(
      `/api/findings/${encodeURIComponent(findingId)}/apply`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action_index: actionIndex,
          action_kind: actionKind,
          action_text: actionText,
        }),
      },
    ),
  fixQueue: () =>
    j<{ queue: FixQueueEntry[];
        counts: { queued: number; applied: number; failed: number;
                  dismissed: number } }>("/api/fix-queue"),
  dismissFix: (findingId: string) =>
    j<{ ok: boolean; removed: number }>(
      `/api/fix-queue/${encodeURIComponent(findingId)}`,
      { method: "DELETE" },
    ),
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

  applyAndGenerate: (loopReview = false) =>
    j<{ apply_run_id: string | null; generate_run_id: string | null; queued_items: number; loop_review?: boolean; max_rounds?: number }>(
      "/api/run/apply-and-generate",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ loop_review: loopReview }),
      },
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

  simBlocks: () => j<{ blocks: SimBlock[]; groups: SimGroup[] }>("/api/sim/blocks"),
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
  // Cancel a running agent (terminates its claude -p process) — backs the
  // Simulation tab's Cancel button.
  cancelAgent: (runId: string) =>
    j<{ run_id: string; cancelled: boolean }>(`/api/agent/${runId}/cancel`, {
      method: "POST",
    }),

  // --- SPICE-model lifecycle (generate / update / chat-edit) ----------------
  // Generate a SPICE model for a block that has none (agent authors the deck).
  simGenerateModel: (block: string) =>
    j<{ run_id: string }>("/api/sim/generate-model", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ block, sim_type: "" }),
    }),
  // Update a stale model to match the current schematic.
  simUpdateModel: (block: string) =>
    j<{ run_id: string }>("/api/sim/update-model", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ block, sim_type: "" }),
    }),
  // Apply a natural-language edit to a block's sim (foundation for chat editing).
  simChatEdit: (block: string, instruction: string) =>
    j<{ run_id: string }>("/api/sim/chat-edit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ block, instruction }),
    }),

  // --- per-agent model selection (which Claude model each sim agent runs on) --
  simAgentModels: () => j<AgentModelConfig>("/api/sim/agent-models"),
  simSetAgentModel: (kind: string, model: string | null) =>
    j<AgentModelConfig>("/api/sim/agent-models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, model }),
    }),

  // --- per-sim requirements (editable pass criteria + boundary params) ------
  simRequirements: (block: string) =>
    j<SimRequirements>(`/api/sim/requirements?block=${encodeURIComponent(block)}`),
  simEditField: (block: string, simType: string, field: "pass" | "rationale", value: string) =>
    j<{ ok: boolean; requirements: SimRequirements }>("/api/sim/requirements", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ block, sim_type: simType, field, value }),
    }),
  simEditBoundary: (block: string, net: string, key: string, paramValue: string) =>
    j<{ ok: boolean; requirements: SimRequirements }>("/api/sim/requirements", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ block, net, key, param_value: paramValue }),
    }),
  // --- clear a block's sim cache (scope: scenario | params | all) -----------
  simClearCache: (block: string, scope: "scenario" | "params" | "all") =>
    j<{ block: string; scope: string; scenario_cleared?: boolean; counters_cleared?: number; params_cleared?: string[] }>(
      "/api/sim/cache/clear", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ block, scope }),
      }),
  // Parsed node-graph of the deck (no ngspice run) — for the "SPICE model" view.
  simCircuit: (block: string, simType: string) =>
    j<{ block: string; sim_type: string; circuit: Circuit | null }>(
      `/api/sim/circuit?block=${encodeURIComponent(block)}&sim_type=${encodeURIComponent(simType)}`,
    ),
  // Which schematic parts the block simulates + where they sit, ACROSS sheets
  // (a block can span sheets). Per-sheet {viewBox, refdes}, the list of sheets
  // that contain a simulated part (for tab highlighting), and the sheet to
  // switch to first.
  simRegion: (block: string) =>
    j<{
      sheets: Record<string, { viewBox: [number, number]; refdes: Record<string, { x: number; y: number }> }>;
      sheets_with_parts: string[];
      refdes: string[];
      primary: string | null;
    }>(`/api/sim/simulated-region?block=${encodeURIComponent(block)}`),

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
  let settled = false;                 // ensure onDone fires exactly once
  const finish = (status: { status: string; rc: number | null; text?: string }) => {
    if (settled) return;
    settled = true;
    es.close();
    onDone?.(status);
  };
  es.onmessage = (e) => {
    try {
      const j = JSON.parse(e.data);
      if (j.line !== undefined) onLine(j.line);
    } catch {
      // ignore
    }
  };
  es.addEventListener("done", (e: MessageEvent) => {
    let parsed: { status: string; rc: number | null; text?: string } = { status: "done", rc: null };
    try { parsed = JSON.parse(e.data); } catch { /* keep default */ }
    finish(parsed);
  });
  // A dropped/failed stream (e.g. the backend restarted mid-run) must NOT leave
  // the caller waiting forever — resolve to a terminal state so the UI can move
  // on. EventSource auto-reconnects on transient errors; only treat it as fatal
  // once the connection is actually CLOSED.
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) finish({ status: "stream_error", rc: null });
  };
  return () => { settled = true; es.close(); };
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
