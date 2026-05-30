// Structured summary that sits at the top of the Review tab's Findings section.
// Turns the flat finding list into: (1) a one-line severity bar graph, and
// (2) a breakdown table grouped by rule family (general checks / components /
// blocks → per-block) × severity. The detailed, actionable per-finding rows
// still render below this — this is the "what am I looking at" overview.
//
// Family is not stored on a Finding, so we join each finding's `rule_id` to the
// rules list (which carries family + applies_to.block) fetched once on mount.
// Findings whose rule_id isn't a known review rule (e.g. layout-linter or
// PDF-imported findings) fall into an "other" bucket so nothing is dropped.

import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { I } from "./Icon";
import type { Finding, Rule, Severity } from "../types";

const SEVS: Severity[] = ["ERROR", "WARNING", "INFO"];

const SEV_BAR: Record<Severity, string> = {
  ERROR: "bg-err",
  WARNING: "bg-warn",
  INFO: "bg-ink-300",
};
const SEV_TEXT: Record<Severity, string> = {
  ERROR: "text-err",
  WARNING: "text-warn",
  INFO: "text-ink-500",
};

// Rule.family ("block") -> the human label used elsewhere in the UI.
const FAMILY_LABEL: Record<string, string> = {
  schematic: "general checks",
  design: "components",
  block: "blocks",
  simulation: "simulated",
  other: "other / linter",
};
// Stable display order of the family groups.
const FAMILY_ORDER = ["schematic", "design", "block", "simulation", "other"];

interface GroupRow {
  key: string;            // family key, or "block:<name>" for a per-block sub-row
  label: string;
  depth: number;          // 0 = family, 1 = block under "blocks"
  counts: Record<Severity, number>;
  total: number;
}

function sev(f: Finding): Severity {
  const s = ((f.severity as string) || "INFO").toUpperCase();
  return (SEVS.includes(s as Severity) ? s : "INFO") as Severity;
}

function emptyCounts(): Record<Severity, number> {
  return { ERROR: 0, WARNING: 0, INFO: 0 };
}

export function FindingsSummary({ items }: { items: Finding[] }) {
  const [rules, setRules] = useState<Rule[] | null>(null);

  useEffect(() => {
    let alive = true;
    api.rules().then(r => { if (alive) setRules(r.rules); }).catch(() => { if (alive) setRules([]); });
    return () => { alive = false; };
  }, []);

  const { totals, grandTotal, groups } = useMemo(() => {
    const ruleById = new Map<string, Rule>();
    for (const r of rules ?? []) ruleById.set(r.id, r);

    const totals = emptyCounts();
    // family -> counts; and for the blocks family, block name -> counts
    const famCounts = new Map<string, Record<Severity, number>>();
    const blockCounts = new Map<string, Record<Severity, number>>();

    for (const f of items) {
      const s = sev(f);
      totals[s] += 1;
      const rid = (f.rule_id as string) || (f.rule as string) || "";
      const rule = rid ? ruleById.get(rid) : undefined;
      const fam = rule?.family ?? "other";
      if (!famCounts.has(fam)) famCounts.set(fam, emptyCounts());
      famCounts.get(fam)![s] += 1;
      if (fam === "block") {
        const blk = rule?.applies_to?.block || "(unspecified)";
        if (!blockCounts.has(blk)) blockCounts.set(blk, emptyCounts());
        blockCounts.get(blk)![s] += 1;
      }
    }

    const groups: GroupRow[] = [];
    for (const fam of FAMILY_ORDER) {
      const c = famCounts.get(fam);
      if (!c) continue;
      const total = c.ERROR + c.WARNING + c.INFO;
      if (total === 0) continue;
      groups.push({ key: fam, label: FAMILY_LABEL[fam] ?? fam, depth: 0, counts: c, total });
      if (fam === "block") {
        const blks = [...blockCounts.entries()].sort((a, b) =>
          (b[1].ERROR + b[1].WARNING + b[1].INFO) - (a[1].ERROR + a[1].WARNING + a[1].INFO));
        for (const [blk, bc] of blks) {
          groups.push({
            key: `block:${blk}`, label: blk, depth: 1, counts: bc,
            total: bc.ERROR + bc.WARNING + bc.INFO,
          });
        }
      }
    }

    const grandTotal = totals.ERROR + totals.WARNING + totals.INFO;
    return { totals, grandTotal, groups };
  }, [items, rules]);

  if (grandTotal === 0) return null;

  return (
    <details className="rounded-md border border-edge bg-white mb-3" open>
      <summary className="px-3 py-2 cursor-pointer select-none flex items-center gap-2 text-[12px] text-ink-800 hover:bg-rail/30">
        <I.Caret size={11} />
        <span className="font-medium">Summary</span>
        <span className="text-ink-500">
          {grandTotal} finding{grandTotal === 1 ? "" : "s"}
        </span>
        {/* inline severity pills so the headline reads at a glance even collapsed */}
        <span className="ml-auto flex items-center gap-2 text-[11px]">
          {SEVS.map(s => totals[s] > 0 && (
            <span key={s} className={"inline-flex items-center gap-1 " + SEV_TEXT[s]}>
              <span className={"inline-block w-2 h-2 rounded-full " + SEV_BAR[s]} />
              {totals[s]}
            </span>
          ))}
        </span>
      </summary>

      <div className="px-3 pb-3 pt-1 space-y-3">
        {/* (1) severity bar graph — proportions of the whole */}
        <div>
          <div className="flex h-3 rounded-full overflow-hidden border border-edge bg-rail">
            {SEVS.map(s => totals[s] > 0 && (
              <div
                key={s}
                className={SEV_BAR[s]}
                style={{ width: `${(totals[s] / grandTotal) * 100}%` }}
                title={`${s}: ${totals[s]} (${Math.round((totals[s] / grandTotal) * 100)}%)`}
              />
            ))}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
            {SEVS.map(s => (
              <span key={s} className="inline-flex items-center gap-1.5 text-ink-600">
                <span className={"inline-block w-2.5 h-2.5 rounded-sm " + SEV_BAR[s]} />
                <span className={SEV_TEXT[s]}>{s}</span>
                <span className="font-mono text-ink-500">{totals[s]}</span>
              </span>
            ))}
          </div>
        </div>

        {/* (2) breakdown table — grouped by family, blocks expanded per-block */}
        <table className="w-full text-[11.5px] border-collapse">
          <thead>
            <tr className="text-ink-500 border-b border-edge">
              <th className="text-left font-medium py-1 pr-2">Group</th>
              <th className="text-right font-medium py-1 px-2 w-14"><span className="text-err">ERR</span></th>
              <th className="text-right font-medium py-1 px-2 w-14"><span className="text-warn">WARN</span></th>
              <th className="text-right font-medium py-1 px-2 w-14"><span className="text-ink-500">INFO</span></th>
              <th className="text-right font-medium py-1 pl-2 w-14">Total</th>
            </tr>
          </thead>
          <tbody>
            {groups.map(g => (
              <tr
                key={g.key}
                className={"border-b border-edge/60 " + (g.depth === 0 ? "text-ink-800" : "text-ink-600")}
              >
                <td className={"py-1 pr-2 " + (g.depth === 1 ? "pl-4" : "")}>
                  {g.depth === 1 && <span className="text-ink-300 mr-1">└</span>}
                  <span className={g.depth === 0 ? "font-medium" : "font-mono text-[11px]"}>{g.label}</span>
                </td>
                <td className="text-right py-1 px-2 font-mono">{cell(g.counts.ERROR, "text-err")}</td>
                <td className="text-right py-1 px-2 font-mono">{cell(g.counts.WARNING, "text-warn")}</td>
                <td className="text-right py-1 px-2 font-mono">{cell(g.counts.INFO, "text-ink-500")}</td>
                <td className="text-right py-1 pl-2 font-mono font-medium text-ink-800">{g.total}</td>
              </tr>
            ))}
            <tr className="text-ink-900 font-medium">
              <td className="py-1 pr-2">All</td>
              <td className="text-right py-1 px-2 font-mono">{cell(totals.ERROR, "text-err")}</td>
              <td className="text-right py-1 px-2 font-mono">{cell(totals.WARNING, "text-warn")}</td>
              <td className="text-right py-1 px-2 font-mono">{cell(totals.INFO, "text-ink-500")}</td>
              <td className="text-right py-1 pl-2 font-mono">{grandTotal}</td>
            </tr>
          </tbody>
        </table>

        {rules === null && (
          <div className="text-[10.5px] text-ink-400 italic">grouping by rule family…</div>
        )}
      </div>
    </details>
  );
}

// Render a count cell: tinted when non-zero, dimmed dash when zero.
function cell(n: number, tone: string) {
  if (n === 0) return <span className="text-ink-300">·</span>;
  return <span className={tone}>{n}</span>;
}
