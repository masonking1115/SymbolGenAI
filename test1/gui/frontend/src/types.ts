export type Severity = "ERROR" | "WARNING" | "INFO";

export interface LintIssue {
  sheet: string;
  severity: Severity;
  rule: string;
  message: string;
  refs: string[];
}

export interface LintRule {
  id: string;
  summary: string;
}

export interface LintReport {
  run_id: string | null;
  status: string;
  issues: LintIssue[];
  rules: LintRule[];
  counts: Record<Severity, number>;
}

export interface Finding {
  severity?: string;
  category?: string;
  refs?: string[];
  message?: string;
  detail?: string;
  source?: string;
  fix_hint?: string;
  [k: string]: unknown;
}

export interface FindingsReport {
  findings: Finding[];
  semantic: Finding[];
  summary: Record<Severity, number>;
  error_log_exists: boolean;
}

export interface SheetMeta {
  name: string;
  size: number;
  mtime: number;
}

export interface LibraryPart {
  mpn: string;
  has_datasheet: boolean;
  datasheet: string | null;
  has_fingerprint: boolean;
  has_symbol: boolean;
}

export interface SymbolPin {
  number: string;
  name: string;
  etype: string;
  x: number;
  y: number;
  rotation: number;
}

export interface SymbolInfo {
  present: boolean;
  mpn: string;
  name?: string;
  properties?: Record<string, string>;
  pins?: SymbolPin[];
  pin_count?: number;
  svg_units?: string[];
  unit_names?: string[];
  render_error?: string;
}

export interface RunHandle {
  run_id: string;
}

export interface RunStatus {
  run_id: string;
  kind: string;
  status: "running" | "ok" | "fail";
  returncode: number | null;
  cmd: string[];
  lines: string[];
}

export type TabKey =
  | "resources"
  | "library"
  | "generator"
  | "review"
  | "simulation";

export type ResourceSubTab = "datasheets" | "requirements" | "skills";

export interface DatasheetItem {
  mpn: string;
  file: string;
  size: number;
}

export interface RequirementDoc {
  name: string;
  size: number;
}

export interface SkillItem {
  slug: string;
  title: string;
  size: number;
  updated: number;
}

export type SimBlockStatus = "implemented" | "planned" | "not_simulatable";

export interface SimType {
  type: string;
  rationale: string;
  pass: string;
  status: "implemented" | "planned";
  defer_reason?: string;
}

export interface SimXAxis {
  label: string;
  unit: string;
  scale: number;
  log: boolean;
}

export interface SimDatasheet {
  mpn: string;
  file: string;
}

export interface SimBlock {
  id: string;
  title: string;
  sheet: string;
  status: SimBlockStatus;
  description: string;
  models_needed: string[];
  datasheets: SimDatasheet[];
  sim_types: SimType[];
}

export interface SimSeries {
  trace: string;
  signal: string;
  t: number[];
  v: number[];
}

export interface SimResult {
  block: string;
  sim_type: string;
  pass_criterion: string | null;
  ok: boolean;
  status: string;
  message?: string;
  ngspice_ok?: boolean;
  analysis?: Record<string, unknown> | null;
  op_point?: Record<string, number>;
  plot: SimSeries[];
  x_axis?: SimXAxis | null;
  y_label?: string;
  deck?: string;
}

export interface FreshnessStamp {
  path: string;
  mtime: number;
}

export interface Freshness {
  status: "fresh" | "stale" | "never";
  reason: string;
  newest_input: FreshnessStamp | null;
  oldest_output: FreshnessStamp | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  ts: number;
}

export interface ChatSessionMeta {
  id: string;
  title: string;
  created: number;
  updated: number;
  is_default: boolean;
  message_count: number;
  has_summary: boolean;
}

export interface ChatSession extends ChatSessionMeta {
  messages: ChatMessage[];
  summary: string | null;
}

export interface ChangelogItem {
  id: string;
  summary: string;
  source: "agent" | "user";
  ts: number;
}

export type StagePhase =
  | "idle"
  | "agent-thinking"
  | "applying-changelog"
  | "generating"
  | "linting"
  | "done"
  | "error";

export type PhaseEvent =
  | { kind: "header"; text: string }
  | { kind: "phase"; phase: string; text: string }
  | { kind: "sheet"; sheet: string; lint: string; text: string }
  | { kind: "lint"; text: string }
  | { kind: "agent"; text: string }
  | { kind: "error"; text: string }
  | { kind: "log"; text: string };

export interface RunSummary {
  present: boolean;
  run_id?: string;
  kind?: string;
  status?: "running" | "ok" | "fail";
  returncode?: number | null;
  phases?: PhaseEvent[];
  raw_tail?: string[];
}
