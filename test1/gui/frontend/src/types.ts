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
  severity?: Severity;
  scope?: "sheet" | "library";
}

export interface LintReport {
  run_id: string | null;
  status: string;
  issues: LintIssue[];
  rules: LintRule[];
  counts: Record<Severity, number>;
}

export interface FindingAction {
  kind: "fix" | "alt" | "verify" | string;
  text: string;
}

export interface Finding {
  severity?: string;
  category?: string;
  refs?: string[];
  message?: string;
  detail?: string;
  source?: string;
  fix_hint?: string;
  // ---- Voltai-PDF parser extensions (_review_incoming/install_review.py)
  id?: string;                  // stable hash of (component, category, rule)
  component?: string;           // refdes, e.g. "U41"
  rule?: string;                // full shall/imperative statement
  actions?: FindingAction[];    // Fix/Alt/Verify suggestions
  fired_count?: number;         // how many times the source tool emitted this
  status?: "pending" | "queued" | "applied" | "failed" | "dismissed";
  source_pdf?: string;
  [k: string]: unknown;
}

export interface FixQueueEntry {
  finding_id: string;
  action_index: number;
  action_kind: string;
  action_text: string;
  component?: string;
  category?: string;
  rule?: string;
  refs?: string[];
  status: "queued" | "applied" | "failed" | "dismissed";
  queued_at: number;
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

// Editable requirements for a block (pass criteria + boundary params).
export interface SimRequirements {
  block: string;
  sim_types: { type: string; status: string; rationale: string; pass: string | null }[];
  boundaries: Record<string, { stub: string | null; params: Record<string, string | number> }>;
}

export interface SimSeries {
  trace: string;
  signal: string;
  t: number[];
  v: number[];
}

// Parsed node-graph of the SPICE deck — what's actually simulated.
export interface CircuitElement {
  ref: string;                 // SPICE deck ref, e.g. "RSENSE", "XOPA", "MQ40"
  kind: string;                // "resistor" | "mosfet" | "subckt" | …
  nodes: string[];             // nets this element connects to
  value: string;               // value / expr / model / subckt name
  subckt: string | null;       // for X-instances: the referenced subckt
  note: string;                // preceding deck comment (pinout hint)
  refdes: string | null;       // corresponding netlist refdes (R40, U41) or null
  //                              for behavioral scaffolding (ammeter, boundary)
}

export interface CircuitSubckt {
  ports: string[];
  params: Record<string, string>;
}

export interface Circuit {
  title: string;
  elements: CircuitElement[];
  nets: string[];
  subckts: Record<string, CircuitSubckt>;
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
  circuit?: Circuit | null;
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
  | "connecting"
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
