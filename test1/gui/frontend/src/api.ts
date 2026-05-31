import type {
  AgentDecision,
  ChangelogItem,
  ChatSession,
  BomItem,
  ChatSessionMeta,
  Circuit,
  DatasheetItem,
  FindingsReport,
  FixQueueEntry,
  Freshness,
  LibraryPart,
  LintReport,
  LoopEvent,
  LoopSummary,
  RequirementDoc,
  Rule,
  RulesListResponse,
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

  // ---- Apply-fix queue ------------------------------------------------
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
  changelogAdd: (
    summary: string,
    origin?: { source?: "sim" | "user" | "closed_loop"; sim_block?: string; sim_type?: string },
  ) =>
    j<ChangelogItem>("/api/changelog", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ summary, ...(origin ?? {}) }),
    }),
  changelogDelete: (id: string) =>
    j<{ ok: boolean }>(`/api/changelog/${id}`, { method: "DELETE" }),
  changelogClear: () =>
    j<{ ok: boolean }>("/api/changelog/clear", { method: "POST" }),

  applyAndGenerate: (loopReview = false, fixWarnings = false, maxRounds?: number) =>
    j<{ apply_run_id: string | null; generate_run_id: string | null; queued_items: number; loop_review?: boolean; fix_warnings?: boolean; max_rounds?: number }>(
      "/api/run/apply-and-generate",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ loop_review: loopReview, fix_warnings: fixWarnings, max_rounds: maxRounds }),
      },
    ),
  symbolGen: (mpn: string) =>
    j<{ run_id: string; datasheet: string }>(
      `/api/library/${encodeURIComponent(mpn)}/generate-symbol`,
      { method: "POST" },
    ),

  // Agent reasoning audit: per-item decisions + persisted reasoning logs.
  agentDecisions: () =>
    j<{ run_id?: string; kind?: string; status?: string; decisions?: AgentDecision[] }>(
      "/api/agent/decisions",
    ),
  agentRuns: () =>
    j<{ runs: { run_id: string; header: string; mtime: number }[] }>("/api/agent/runs"),
  agentRunLog: (runId: string) =>
    j<{ run_id: string; body: string }>(`/api/agent/runs/${runId}/log`),

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
  // The ACTIVE design_requirements.md spec (project root) — GET/PUT content.
  activeRequirement: () =>
    j<{ exists: boolean; content: string }>("/api/requirements"),
  saveActiveRequirement: (content: string) =>
    j<{ ok: boolean; name: string; bytes: number }>("/api/requirements", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }),
  // In-app editor: plain-text content of a requirements doc (text exts only).
  requirementContent: (name: string) =>
    j<{ name: string; content: string; size: number }>(
      `/api/resources/requirements/content?name=${encodeURIComponent(name)}`,
    ),
  saveRequirementContent: (name: string, content: string) =>
    j<{ ok: boolean; name: string; bytes: number }>(
      `/api/resources/requirements/content?name=${encodeURIComponent(name)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      },
    ),
  // BOM (bill of materials) — .xlsx/.csv, stored in resources/bom/
  resourcesBom: () =>
    j<{ bom: BomItem[]; generated_exists: boolean }>("/api/resources/bom"),
  uploadBom: (filename: string, contentB64: string) =>
    j<{ ok: boolean; file: string; size: number }>("/api/resources/bom", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename, content_b64: contentB64 }),
    }),
  bomFileUrl: (name: string) =>
    `/api/resources/bom/file?name=${encodeURIComponent(name)}`,
  // In-app editor: plain-text content of a BOM file (CSV/TSV only; xlsx is 415).
  bomContent: (name: string) =>
    j<{ name: string; content: string; size: number }>(
      `/api/resources/bom/content?name=${encodeURIComponent(name)}`,
    ),
  saveBomContent: (name: string, content: string) =>
    j<{ ok: boolean; name: string; bytes: number }>(
      `/api/resources/bom/content?name=${encodeURIComponent(name)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      },
    ),
  resourcesSkills: () => j<{ skills: SkillItem[] }>("/api/resources/skills"),
  // Raw endpoint URL for a skill (JSON {slug, content}) — used as the
  // OpenFile.url for the editor's "open in new tab" affordance.
  skillFileUrl: (slug: string) =>
    `/api/resources/skills/${encodeURIComponent(slug)}`,
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

  // ---- Closed-loop design review: rules CRUD --------------------------
  // NOTE: doc-driven rule GENERATION was retired (the Regenerate button is gone;
  // rules are now managed manually via add/edit/delete). The /generate* client +
  // RuleGen* types were removed as dead code. The backend /generate* routes
  // remain for CLI use but are unused by the GUI.
  rules: () => j<RulesListResponse>("/api/review/rules"),
  editRule: (rule_id: string, patch: Partial<Rule>) =>
    j<{ ok: boolean; rule: Rule }>("/api/review/rules/edit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rule_id, ...patch }),
    }),
  deleteRule: (rule_id: string, hard = false) =>
    j<{ ok: boolean; rule_id: string; enabled?: boolean; deleted?: boolean }>(
      `/api/review/rules/${encodeURIComponent(rule_id)}${hard ? "?hard=true" : ""}`,
      { method: "DELETE" },
    ),
  // Manually add a user-authored (semantic) rule — replaces doc-driven regenerate.
  addRule: (body: {
    id: string; family?: string; severity?: string; title: string; prompt: string;
    sheet?: string; refdes?: string; net?: string; block?: string;
    source_doc?: string; source_loc?: string; source_quote?: string; fix_hint?: string;
  }) =>
    j<{ ok: boolean; rule: Rule }>("/api/review/rules/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  // ---- Closed-loop design review: loop orchestration (Phase 4) -------------
  loopStart: async (maxRounds?: number): Promise<{ loop_id: string; max_rounds?: number }> => {
    const r = await fetch("/api/loop/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ max_rounds: maxRounds }),
    });
    if (!r.ok) throw new Error("loop start failed");
    return r.json();
  },
  loopLatest: async (): Promise<LoopSummary | { loop_id: null }> => {
    const r = await fetch("/api/loop/latest");
    return r.json();
  },
  loopGet: async (loop_id: string): Promise<LoopSummary> => {
    const r = await fetch(`/api/loop/${loop_id}`);
    if (!r.ok) throw new Error("loop fetch failed");
    return r.json();
  },
  loopCancel: async (loop_id: string): Promise<{ ok: boolean }> => {
    const r = await fetch(`/api/loop/${loop_id}/cancel`, { method: "POST" });
    if (!r.ok) throw new Error("cancel failed");
    return r.json();
  },
  loopAccept: async (loop_id: string): Promise<{ ok: boolean }> => {
    const r = await fetch(`/api/loop/${loop_id}/accept`, { method: "POST" });
    if (!r.ok) throw new Error("accept failed");
    return r.json();
  },
  loopReject: async (
    loop_id: string,
    revert?: string[],
  ): Promise<{
    ok: boolean;
    rolled_forward?: boolean;
    reason?: string;
    rebuild_status?: boolean;
    rebuild_log_tail?: string;
  }> => {
    const r = await fetch(`/api/loop/${loop_id}/reject`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ revert }),
    });
    if (!r.ok) throw new Error("reject failed");
    return r.json();
  },
  // Clear a loop's review residue WITHOUT reverting the design (drops the
  // closed-loop changelog items + removes the snapshot so the diff stops showing).
  loopClear: async (
    loop_id: string,
  ): Promise<{ ok: boolean; changelog_removed: number; snapshot_removed: boolean }> => {
    const r = await fetch(`/api/loop/${loop_id}/clear`, { method: "POST" });
    if (!r.ok) throw new Error("clear failed");
    return r.json();
  },
  loopDiff: async (loop_id: string): Promise<{
    loop_id: string;
    sheets: Record<string, {
      viewBox: string;
      snapViewBox?: string;
      added: Record<string, { x: number; y: number; kind: "added" }>;
      removed: Record<string, { x: number; y: number; kind: "removed" }>;
      changed: Record<string, { x: number; y: number; from_x?: number; from_y?: number; kind: "changed"; from_value: string; to_value: string }>;
      count: number;
      renderable?: boolean;
      unrenderable_reason?: string;
    }>;
  }> => {
    const r = await fetch(`/api/loop/${loop_id}/diff`);
    if (!r.ok) throw new Error("diff fetch failed");
    return r.json();
  },

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

/** Subscribe to a closed-loop iteration's SSE stream. Returns an unsubscribe fn. */
export function subscribeLoop(
  loop_id: string,
  onEvent: (ev: LoopEvent) => void,
  onDone: (status: string) => void,
): () => void {
  let closed = false;
  const es = new EventSource(`/api/loop/${loop_id}/stream`);
  const handle = (eventName: string) => (e: MessageEvent) => {
    if (closed) return;
    try {
      const data = JSON.parse(e.data);
      onEvent({ event: eventName as LoopEvent["event"], data } as LoopEvent);
    } catch { /* ignore parse errors */ }
  };
  for (const name of [
    "eval_start", "eval_progress", "eval_done",
    "loop_start", "round_start", "action_start", "action_end", "build_start",
    "build_end", "sim_results", "round_done", "plateau", "error",
  ]) {
    es.addEventListener(name, handle(name));
  }
  es.addEventListener("done", (e: MessageEvent) => {
    if (closed) return;
    try {
      const data = JSON.parse(e.data);
      onEvent({ event: "done", data });
      onDone(data.status);
    } catch { /* ignore parse errors */ }
    closed = true;
    es.close();
  });
  es.onerror = () => {
    if (!closed) { closed = true; es.close(); onDone("stream_error"); }
  };
  return () => { closed = true; es.close(); };
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
