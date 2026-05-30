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
  group: string;          // functional-domain id (keys into SimGroup)
  status: SimBlockStatus;
  description: string;
  models_needed: string[];
  datasheets: SimDatasheet[];
  sim_types: SimType[];
  // SPICE-model lifecycle. has_model=false → offer "Generate SPICE model";
  // model_status="stale" → schematic changed under the model, offer "Update".
  has_model: boolean;
  model_status: "none" | "unknown" | "fresh" | "stale";
}

// Per-agent LLM selection (sim agents). The backend owns the list + defaults.
// `model`/`default` are EXACT Anthropic model ids (e.g. "claude-opus-4-8").
export interface AgentModelEntry {
  kind: string;
  label: string;
  group: string;          // section the agent belongs to (Simulation / Schematic)
  model: string;          // current model id
  default: string;        // per-kind default id
  overridden: boolean;
}
// The exact model the picker offers (full pinned-snapshot id + display meta).
export interface ModelChoice {
  id: string;
  label: string;
  family: "opus" | "sonnet" | "haiku";
  tier: string;
  latest: boolean;
}
export interface AgentModelConfig {
  models: ModelChoice[];
  agents: AgentModelEntry[];
}

// A functional grouping for the Simulation tab + sidebar. The ordered list comes
// from the backend (SIM_GROUPS in app.py); blocks are bucketed by `block.group`.
export interface SimGroup {
  id: string;
  label: string;
  blurb: string;
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
  source: "agent" | "user" | "sim";
  sim_block?: string;
  sim_type?: string;
  ts: number;
}

export interface AgentDecision {
  item: string;
  outcome: "APPLIED" | "STOPPED" | "CLARIFY";
  reason: string;
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

// ---- Closed-loop design review: Rule schema (mirrors rule_schema.py) ----
export interface RuleSource {
  doc: string;
  loc: string;
  quote?: string;
}

export interface RuleAppliesTo {
  refdes?: string;
  pins?: string[];
  net?: string;
  rail?: string;
  sheet?: string;
  sim_block?: string;
  sim_type?: string;
  mpn?: string;
  role_spec?: Record<string, unknown>;
}

export interface RulePredicate {
  kind: string;
  [arg: string]: unknown;
}

export interface Rule {
  id: string;
  family: "schematic" | "simulation" | "design";
  evaluation: "structural" | "semantic";
  severity: "ERROR" | "WARNING" | "INFO";
  title: string;
  applies_to: RuleAppliesTo;
  source: RuleSource[];
  fix_hint?: string;
  enabled: boolean;
  origin: "generated" | "user" | "imported";
  predicate?: RulePredicate;
  prompt?: string;
}

export interface RulesListResponse {
  version: number;
  generated_at: string;
  rules: Rule[];
  sources_seen: { path: string; mtime: number }[];
  stale_sources: { path: string; current_mtime: number; recorded_mtime: number }[];
  by_family: { schematic: number; simulation: number; design: number };
  by_origin: { generated: number; user: number; imported: number };
}
