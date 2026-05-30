import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { I } from "./Icon";
import type { Rule, RulesListResponse } from "../types";

interface Props {
  loopRunning: boolean;          // disable buttons while a loop is in flight
}

const SEV_DOT: Record<string, string> = {
  ERROR: "bg-err", WARNING: "bg-warn", INFO: "bg-ink-300",
};

const FAMILY_LABEL: Record<string, string> = {
  // schematic -> "general checks", design -> "components" (the simulation family
  // was retired — its checks are covered, more strictly, by the block rules; any
  // rule that runs a real ngspice sim carries a "simulated" tag instead).
  schematic: "general checks", design: "components", blocks: "blocks",
};

// Display order + label for the per-block sub-groups under the Blocks dropdown.
// Keys are the rule's applies_to.block; anything unlisted falls through alphabetically.
const BLOCK_LABEL: Record<string, string> = {
  opa_bias: "opa_bias — V-to-I bias loop",
  ldo_rail: "ldo_rail — TPS7A8401A LDO",
  loadsw: "loadsw — VADJ→VDDIO switch",
  vddio_pdn: "vddio_pdn — VDDIO decoupling",
  vddd_pdn: "vddd_pdn — VDDD decoupling",
  vdda1_pdn: "vdda1_pdn — VDDA1 decoupling",
  vdda2_pdn: "vdda2_pdn — VDDA2 decoupling",
  eeprom: "eeprom — 24AA08 I²C",
};
const BLOCK_ORDER = ["opa_bias", "ldo_rail", "loadsw",
  "vddio_pdn", "vddd_pdn", "vdda1_pdn", "vdda2_pdn", "eeprom"];

export function RulesSection({ loopRunning }: Props) {
  const [data, setData] = useState<RulesListResponse | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});  // by family
  const [error, setError] = useState<string>("");
  const [adding, setAdding] = useState(false);   // show the "add rule" form

  const refresh = useCallback(async () => {
    try { setData(await api.rules()); setError(""); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const toggleRule = async (rule_id: string, enabled: boolean) => {
    await api.editRule(rule_id, { enabled });
    await refresh();
  };

  // Hard-delete a rule (the trash control). Confirm first — it removes the rule
  // from rules.yaml entirely (the doc-driven regenerate that used to re-add
  // generated rules is gone, so deletion is permanent unless re-added manually).
  const deleteRule = async (rule_id: string) => {
    if (!window.confirm(`Delete rule ${rule_id}? This removes it permanently.`)) return;
    await api.deleteRule(rule_id, true);
    await refresh();
  };

  const addRule = async (body: Parameters<typeof api.addRule>[0]) => {
    setError("");
    try { await api.addRule(body); setAdding(false); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };

  if (!data) return (
    <section className="mt-5">
      <div className="text-sm text-ink-500">Loading rules…{error && ` (${error})`}</div>
    </section>
  );

  const stale = data.stale_sources.length > 0;
  const empty = data.rules.length === 0;

  return (
    <section className="mt-5 rounded-md border border-edge bg-white">
      <header className="px-4 py-2.5 flex items-center gap-2 border-b border-edge">
        <I.Schematic size={14} />
        <span className="text-sm font-semibold text-ink-900">Rules</span>
        <span className="text-[11px] text-ink-500">
          {data.rules.length} active · {data.by_origin.user} user · {data.rules.filter(r=>!r.enabled).length} disabled
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          {!empty && (
            <a
              href="/api/review/rules/pdf"
              download
              className="h-7 px-2.5 inline-flex items-center gap-1 text-[11.5px] rounded border border-edge text-ink-700 hover:border-ink-300"
              title="Download the full rule set as a PDF"
            >
              <I.Datasheet size={12} /> PDF
            </a>
          )}
          {/* Rules are managed MANUALLY now (regenerate-from-docs removed): add a
              rule here, toggle/delete per row below. */}
          <button
            onClick={() => setAdding(a => !a)}
            disabled={loopRunning}
            className="h-7 px-2.5 inline-flex items-center gap-1 text-[11.5px] rounded border border-edge text-ink-700 hover:border-ink-300 disabled:opacity-50"
          >
            <I.Plus size={12} /> {adding ? "Cancel" : "Add rule"}
          </button>
        </div>
      </header>

      {error && (
        <div className="px-4 py-2 text-[12px] text-err bg-err/[0.04] border-b border-edge">
          {error}
        </div>
      )}

      {adding && <AddRuleForm onAdd={addRule} onCancel={() => setAdding(false)} />}

      {empty && !adding && (
        <div className="px-4 py-6 text-center text-sm text-ink-500">
          No rules yet. Click <em>Add rule</em> to create one manually.
        </div>
      )}

      {stale && (
        <div className="px-4 py-2 text-[12px] bg-warn/[0.06] text-ink-700 border-b border-edge">
          <strong>⚠ Sources changed</strong> since rules were generated —
          {data.stale_sources.length} files newer:
          <ul className="mt-1 list-disc pl-5">
            {data.stale_sources.slice(0, 5).map(s => (
              <li key={s.path} className="font-mono text-[11px]">{s.path}</li>
            ))}
          </ul>
        </div>
      )}

      {!empty && (
        <div className="px-4 py-3 space-y-2">
          {(["schematic", "design"] as const).map(fam => {
            const rules = data.rules.filter(r => r.family === fam);
            if (rules.length === 0) return null;
            const open = !!expanded[fam];
            return (
              <div key={fam}>
                <button
                  onClick={() => setExpanded(e => ({ ...e, [fam]: !open }))}
                  className="text-[11.5px] text-ink-700 hover:text-ink-900 flex items-center gap-1.5"
                >
                  {open ? "▾" : "▸"} {FAMILY_LABEL[fam]} ({rules.length})
                </button>
                {open && (
                  <div className="mt-1.5 ml-3 space-y-1">
                    {rules.map(r => (
                      <RuleRow key={r.id} r={r} onToggle={toggleRule} onDelete={deleteRule} />
                    ))}
                  </div>
                )}
              </div>
            );
          })}

          {/* Blocks: the block family, grouped per functional block (block →
              its strict rule set). A two-level dropdown: blocks > <block> > rules. */}
          <BlocksGroup
            rules={data.rules.filter(r => r.family === "block")}
            open={!!expanded.blocks}
            onToggleGroup={() => setExpanded(e => ({ ...e, blocks: !e.blocks }))}
            blockOpen={expanded}
            onToggleBlock={(b) => setExpanded(e => ({ ...e, [b]: !e[b] }))}
            onToggleRule={toggleRule}
            onDeleteRule={deleteRule}
          />
        </div>
      )}
    </section>
  );
}

// ---- Blocks dropdown (block family, nested per-block) -------------------
function BlocksGroup({
  rules, open, onToggleGroup, blockOpen, onToggleBlock, onToggleRule, onDeleteRule,
}: {
  rules: Rule[];
  open: boolean;
  onToggleGroup: () => void;
  blockOpen: Record<string, boolean>;
  onToggleBlock: (block: string) => void;
  onToggleRule: (id: string, enabled: boolean) => void;
  onDeleteRule: (id: string) => void;
}) {
  if (rules.length === 0) return null;
  // Bucket rules by their block tag.
  const byBlock: Record<string, Rule[]> = {};
  for (const r of rules) {
    const b = r.applies_to.block || "other";
    (byBlock[b] ??= []).push(r);
  }
  // Ordered block keys: known order first, then any extras alphabetically.
  const keys = [
    ...BLOCK_ORDER.filter(b => byBlock[b]),
    ...Object.keys(byBlock).filter(b => !BLOCK_ORDER.includes(b)).sort(),
  ];
  const errCount = rules.filter(r => r.severity === "ERROR").length;
  return (
    <div>
      <button
        onClick={onToggleGroup}
        className="text-[11.5px] text-ink-700 hover:text-ink-900 flex items-center gap-1.5"
      >
        {open ? "▾" : "▸"} {FAMILY_LABEL.blocks} ({rules.length})
        <span className="text-[10px] text-ink-500">· {keys.length} blocks
          {errCount > 0 && <span className="text-err"> · {errCount} ERROR</span>}
        </span>
      </button>
      {open && (
        <div className="mt-1.5 ml-3 space-y-1.5">
          {keys.map(b => {
            const brules = byBlock[b];
            const bopen = !!blockOpen[`block:${b}`];
            const bErr = brules.filter(r => r.severity === "ERROR").length;
            return (
              <div key={b} className="rounded border border-edge/70 bg-rail/10">
                <button
                  onClick={() => onToggleBlock(`block:${b}`)}
                  className="w-full text-left px-2 py-1 text-[11px] text-ink-800 hover:text-ink-900 flex items-center gap-1.5"
                >
                  {bopen ? "▾" : "▸"}
                  <span className="font-medium">{BLOCK_LABEL[b] || b}</span>
                  <span className="text-[10px] text-ink-500">
                    ({brules.length}{bErr > 0 && <span className="text-err"> · {bErr}E</span>})
                  </span>
                </button>
                {bopen && (
                  <div className="px-2 pb-2 ml-2 space-y-1">
                    {brules.map(r => (
                      <RuleRow key={r.id} r={r} onToggle={onToggleRule} onDelete={onDeleteRule} />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function RuleRow({ r, onToggle, onDelete }: {
  r: Rule; onToggle: (id: string, en: boolean) => void; onDelete: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className={"rounded border px-2 py-1.5 text-[11.5px] group " + (r.enabled ? "border-edge bg-white" : "border-edge/50 bg-ink-100/50")}>
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={r.enabled}
          onChange={(e) => onToggle(r.id, e.target.checked)}
          className="mt-0.5"
        />
        <span className={"mt-1 inline-block w-2 h-2 rounded-full " + SEV_DOT[r.severity]} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="font-mono text-[10px] text-ink-500">{r.id}</span>
            <span className="text-ink-500">·</span>
            <span className="text-ink-500">{r.evaluation}</span>
            {/* "simulated" = the rule is evaluated by running a real ngspice sim
                (sim_review predicate), as opposed to a structural/semantic check. */}
            {r.predicate?.kind === "sim_review" && (
              <span className="text-[10px] px-1 rounded bg-blue-500/15 text-blue-600"
                title="evaluated by running a real ngspice simulation">simulated</span>
            )}
            {r.origin === "user" && <span className="text-[10px] px-1 rounded bg-warn/15 text-warn">user</span>}
            <button
              onClick={() => onDelete(r.id)}
              title="Delete this rule (permanent)"
              className="ml-auto opacity-0 group-hover:opacity-100 text-ink-400 hover:text-err transition-opacity"
            >
              <I.Trash size={12} />
            </button>
          </div>
          <div className="text-ink-900">{r.title}</div>
          {open && (
            <div className="mt-1.5 pl-2 border-l border-edge text-[11px] text-ink-700">
              {r.source.map((s, i) => (
                <div key={i} className="mb-1">
                  <span className="font-mono text-ink-500">{s.doc}:{s.loc}</span>
                  {s.quote && <div className="italic text-ink-500">"{s.quote}"</div>}
                </div>
              ))}
              {r.fix_hint && <div className="mt-1"><strong>fix:</strong> {r.fix_hint}</div>}
              {r.predicate && (
                <pre className="mt-1 text-[10.5px] bg-rail/40 px-1.5 py-1 rounded overflow-auto">
{JSON.stringify(r.predicate, null, 2)}
                </pre>
              )}
              {r.prompt && (
                <div className="mt-1">
                  <strong>prompt:</strong>
                  <div className="text-[11px] text-ink-700 whitespace-pre-wrap">{r.prompt}</div>
                </div>
              )}
            </div>
          )}
          <button
            onClick={() => setOpen(o => !o)}
            className="mt-1 text-[10px] text-ink-500 hover:text-ink-900"
          >
            {open ? "hide details" : "details"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---- Manual rule entry --------------------------------------------------
// A user-authored rule is a SEMANTIC check: a title + a prompt the LLM judges
// against the design (the structural predicates aren't human-authorable here).
// Family picks which dropdown it lands in; block-family rules also take a block.
function AddRuleForm({ onAdd, onCancel }: {
  onAdd: (b: Parameters<typeof api.addRule>[0]) => void;
  onCancel: () => void;
}) {
  const [id, setId] = useState("");
  const [family, setFamily] = useState("design");
  const [severity, setSeverity] = useState("WARNING");
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [block, setBlock] = useState("");
  const [sheet, setSheet] = useState("");
  const valid = /^[A-Za-z0-9_]+$/.test(id) && title.trim() && prompt.trim()
    && (family !== "block" || block.trim());

  const field = "text-[12px] border border-edge rounded px-2 py-1 focus:outline-none focus:border-ink-300";
  return (
    <div className="px-4 py-3 border-b border-edge bg-rail/10 space-y-2">
      <div className="flex flex-wrap gap-2">
        <input className={field + " font-mono w-44"} placeholder="RULE_ID (A-Z0-9_)"
          value={id} onChange={e => setId(e.target.value.toUpperCase())} />
        <select className={field} value={family} onChange={e => setFamily(e.target.value)}>
          <option value="schematic">general checks</option>
          <option value="design">components</option>
          <option value="block">blocks</option>
        </select>
        <select className={field} value={severity} onChange={e => setSeverity(e.target.value)}>
          <option>ERROR</option><option>WARNING</option><option>INFO</option>
        </select>
        {family === "block" && (
          <input className={field + " w-40"} placeholder="block (e.g. opa_bias)"
            value={block} onChange={e => setBlock(e.target.value)} />
        )}
        <input className={field + " w-32"} placeholder="sheet (optional)"
          value={sheet} onChange={e => setSheet(e.target.value)} />
      </div>
      <input className={field + " w-full"} placeholder="Title — one-line summary of the check"
        value={title} onChange={e => setTitle(e.target.value)} />
      <textarea className={field + " w-full h-20 resize-y"}
        placeholder="Prompt — the check the reviewer LLM judges (e.g. 'Verify R60/R61 pull SCL/SDA to +3V3 with 2.2k'). Be specific; state PASS/FAIL conditions."
        value={prompt} onChange={e => setPrompt(e.target.value)} />
      <div className="flex items-center gap-2">
        <button
          disabled={!valid}
          onClick={() => onAdd({
            id: id.trim(), family, severity, title: title.trim(), prompt: prompt.trim(),
            block: family === "block" ? block.trim() : undefined,
            sheet: sheet.trim() || undefined,
          })}
          className="h-7 px-3 text-[11.5px] rounded bg-ink-900 text-white font-medium hover:bg-black disabled:opacity-40"
        >
          Add rule
        </button>
        <button onClick={onCancel} className="h-7 px-3 text-[11.5px] rounded border border-edge text-ink-700 hover:border-ink-300">
          Cancel
        </button>
        <span className="text-[10px] text-ink-500">Added rules are semantic (LLM-judged) + tagged <span className="px-1 rounded bg-warn/15 text-warn">user</span>.</span>
      </div>
    </div>
  );
}
