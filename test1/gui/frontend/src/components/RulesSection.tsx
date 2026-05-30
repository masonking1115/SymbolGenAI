import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { I } from "./Icon";
import type { Rule, RulesListResponse } from "../types";

interface Props {
  onApproveAndRun: () => void;   // start a loop after user clicks "Approve & Run"
  loopRunning: boolean;          // disable buttons while a loop is in flight
}

const SEV_DOT: Record<string, string> = {
  ERROR: "bg-err", WARNING: "bg-warn", INFO: "bg-ink-300",
};

const FAMILY_LABEL: Record<string, string> = {
  schematic: "schematic", simulation: "simulation", design: "design",
};

export function RulesSection({ onApproveAndRun, loopRunning }: Props) {
  const [data, setData] = useState<RulesListResponse | null>(null);
  const [generating, setGenerating] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});  // by family
  const [error, setError] = useState<string>("");

  const refresh = useCallback(async () => {
    try { setData(await api.rules()); setError(""); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const generate = async () => {
    setGenerating(true); setError("");
    try { await api.generateRules(); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setGenerating(false); }
  };

  const toggleRule = async (rule_id: string, enabled: boolean) => {
    await api.editRule(rule_id, { enabled });
    await refresh();
  };

  if (!data) return (
    <section className="mt-5">
      <div className="text-sm text-ink-500">Loading rules…{error && ` (${error})`}</div>
    </section>
  );

  // Approval state is heuristic for now: any user-origin rule means
  // the user has touched the set → approved. Refine with a dedicated
  // approved_at flag in later iteration.

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
          <button
            onClick={generate}
            disabled={generating || loopRunning}
            className="h-7 px-2.5 text-[11.5px] rounded border border-edge text-ink-700 hover:border-ink-300 disabled:opacity-50"
          >
            {generating ? "Generating…" : empty ? "Generate rules" : "Regenerate"}
          </button>
          {!empty && (
            <button
              onClick={onApproveAndRun}
              disabled={loopRunning}
              className="h-7 px-2.5 text-[11.5px] rounded bg-ink-900 text-white font-medium hover:bg-black disabled:opacity-50"
            >
              ✓ Approve &amp; Run loop
            </button>
          )}
        </div>
      </header>

      {error && (
        <div className="px-4 py-2 text-[12px] text-err bg-err/[0.04] border-b border-edge">
          {error}
        </div>
      )}

      {empty && (
        <div className="px-4 py-6 text-center text-sm text-ink-500">
          No rules yet. Click <em>Generate rules</em> to build them from the
          project docs.
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
          {(["schematic", "simulation", "design"] as const).map(fam => {
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
                      <RuleRow key={r.id} r={r} onToggle={toggleRule} />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function RuleRow({ r, onToggle }: { r: Rule; onToggle: (id: string, en: boolean) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={"rounded border px-2 py-1.5 text-[11.5px] " + (r.enabled ? "border-edge bg-white" : "border-edge/50 bg-ink-100/50")}>
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
            {r.origin === "user" && <span className="text-[10px] px-1 rounded bg-warn/15 text-warn">user</span>}
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
