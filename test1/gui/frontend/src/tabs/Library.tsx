import { useEffect, useState } from "react";
import { api, subscribeAgent } from "../api";
import { I } from "../components/Icon";
import type { LibraryPart, SymbolInfo, SymbolPin } from "../types";

export function Library() {
  const [parts, setParts] = useState<LibraryPart[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [sym, setSym] = useState<SymbolInfo | null>(null);
  const [filter, setFilter] = useState<"all" | "populated" | "missing">("all");
  const [genState, setGenState] = useState<"idle" | "running" | "ok" | "fail">("idle");
  const [genLog, setGenLog] = useState<string[]>([]);

  const refreshParts = () =>
    api
      .library()
      .then((r) => setParts(r.parts))
      .catch(() => setParts([]));

  useEffect(() => {
    refreshParts();
  }, []);

  useEffect(() => {
    if (!sel) {
      setSym(null);
      return;
    }
    setSym(null);
    setGenState("idle");
    setGenLog([]);
    api.librarySymbol(sel)
      .then((d) => setSym(d))
      .catch(() => setSym({ present: false, mpn: sel }));
  }, [sel]);

  const generateSymbol = async () => {
    if (!sel) return;
    setGenState("running");
    setGenLog([`▶ spawning symbol-gen subagent for ${sel}…`]);
    try {
      const { run_id, datasheet } = await api.symbolGen(sel);
      setGenLog((l) => [...l, `  datasheet: ${datasheet}`]);
      subscribeAgent(
        run_id,
        (line) => setGenLog((l) => [...l, line]),
        ({ status }) => {
          setGenState(status === "ok" ? "ok" : "fail");
          setGenLog((l) => [...l, `✓ subagent ${status}`]);
          refreshParts();
          if (sel) {
            api.librarySymbol(sel).then(setSym).catch(() => {});
          }
        },
      );
    } catch (e) {
      setGenState("fail");
      setGenLog((l) => [
        ...l,
        `error: ${e instanceof Error ? e.message : String(e)}`,
      ]);
    }
  };

  const filtered = parts.filter((p) => {
    if (filter === "populated") return p.has_symbol;
    if (filter === "missing") return !p.has_symbol;
    return true;
  });

  return (
    <div className="h-full grid grid-cols-[280px_1fr] overflow-hidden">
      <PartList
        parts={filtered}
        allParts={parts}
        filter={filter}
        setFilter={setFilter}
        sel={sel}
        setSel={setSel}
      />
      <PartDetail
        sel={sel}
        sym={sym}
        genState={genState}
        genLog={genLog}
        onGenerate={generateSymbol}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Left column: filter chips + scrollable part list
// ---------------------------------------------------------------------------
function PartList({
  parts,
  allParts,
  filter,
  setFilter,
  sel,
  setSel,
}: {
  parts: LibraryPart[];
  allParts: LibraryPart[];
  filter: "all" | "populated" | "missing";
  setFilter: (f: "all" | "populated" | "missing") => void;
  sel: string | null;
  setSel: (s: string) => void;
}) {
  const counts = {
    all: allParts.length,
    populated: allParts.filter((p) => p.has_symbol).length,
    missing: allParts.filter((p) => !p.has_symbol).length,
  };
  return (
    <div className="border-r border-edge h-full flex flex-col min-h-0">
      <div className="px-4 pt-5 pb-3">
        <div className="text-[11px] tracking-wide uppercase text-ink-500">
          Phase 1 · Library
        </div>
        <h2 className="text-[18px] font-semibold text-ink-900 mt-0.5">
          Parts
        </h2>
      </div>
      <div className="px-3 pb-2 flex flex-wrap gap-1 text-xs">
        {(["all", "populated", "missing"] as const).map((k) => (
          <button
            key={k}
            onClick={() => setFilter(k)}
            className={
              "px-2 py-1 rounded-md border " +
              (filter === k
                ? "bg-ink-900 text-white border-ink-900"
                : "bg-white text-ink-700 border-edge hover:border-ink-300")
            }
          >
            {k === "all"
              ? `All (${counts.all})`
              : k === "populated"
              ? `Symbols (${counts.populated})`
              : `Missing (${counts.missing})`}
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0 overflow-auto thin-scroll">
        {parts.map((p) => (
          <button
            key={p.mpn}
            onClick={() => setSel(p.mpn)}
            className={
              "w-full text-left px-3 py-2 border-b border-edge flex items-center gap-2 hover:bg-rail " +
              (sel === p.mpn ? "bg-rail" : "")
            }
          >
            <span
              className={
                "inline-flex items-center justify-center w-5 h-5 rounded-full shrink-0 " +
                (p.has_symbol ? "bg-ok/10 text-ok" : "bg-edge text-ink-500")
              }
              title={p.has_symbol ? "Symbol present" : "No symbol yet"}
            >
              {p.has_symbol ? <I.Check size={12} /> : <I.Plus size={12} />}
            </span>
            <span className="text-[13px] text-ink-900 truncate flex-1">
              {p.mpn}
            </span>
            <span className="flex items-center gap-1 text-[10px] text-ink-500">
              {p.has_datasheet && (
                <span className="px-1.5 py-0.5 rounded-full border border-edge">
                  DS
                </span>
              )}
              {p.has_fingerprint && (
                <span className="px-1.5 py-0.5 rounded-full border border-edge">
                  FP
                </span>
              )}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Right column: SVG viewer + properties + pin table
// ---------------------------------------------------------------------------
function PartDetail({
  sel,
  sym,
  genState,
  genLog,
  onGenerate,
}: {
  sel: string | null;
  sym: SymbolInfo | null;
  genState: "idle" | "running" | "ok" | "fail";
  genLog: string[];
  onGenerate: () => void;
}) {
  if (!sel) {
    return (
      <div className="h-full grid place-items-center text-ink-500 text-sm">
        Select a part to inspect its symbol, datasheet, and pin table.
      </div>
    );
  }
  if (!sym) {
    return (
      <div className="h-full grid place-items-center text-ink-500 text-sm">
        Loading {sel}…
      </div>
    );
  }
  const hasSymbol = sym.present && (sym.svg_units?.length ?? 0) > 0;
  const properties = sym.properties ?? {};
  const pins = sym.pins ?? [];

  return (
    <div className="h-full overflow-auto thin-scroll">
      <div className="px-6 py-5 max-w-[900px]">
        <div className="flex items-baseline gap-3">
          <div>
            <div className="text-[11px] tracking-wide uppercase text-ink-500">
              Part
            </div>
            <h2 className="text-[18px] font-semibold text-ink-900 mt-0.5">
              {sel}
              {sym.name && sym.name !== sel && (
                <span className="text-ink-500 font-normal text-[14px] ml-2">
                  (symbol: {sym.name})
                </span>
              )}
            </h2>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {properties.Datasheet && (
              <a
                href={api.datasheetUrl(sel)}
                target="_blank"
                rel="noreferrer"
                className="h-7 px-2 text-xs rounded-md border border-edge text-ink-700 hover:border-ink-300 inline-flex items-center gap-1"
              >
                <I.Datasheet size={13} /> Datasheet
              </a>
            )}
            {!sym.present && (
              <button
                onClick={onGenerate}
                disabled={genState === "running"}
                className="h-7 px-2 text-xs rounded-md bg-ink-900 text-white inline-flex items-center gap-1 disabled:opacity-50"
                title="Spawn a Claude subagent to read the datasheet PDF and emit a KiCad symbol"
              >
                <I.Plus size={12} />
                {genState === "running" ? "Generating…" : "Generate symbol"}
              </button>
            )}
          </div>
        </div>

        {sym.render_error && (
          <div className="mt-3 text-[12px] rounded-md border border-warn/30 bg-warn/[0.06] text-warn px-3 py-2">
            SVG render failed: {sym.render_error}
          </div>
        )}

        {hasSymbol ? (
          <SymbolViewer mpn={sel} units={sym.svg_units!} />
        ) : sym.present ? null : (
          <NoSymbolPlaceholder onGenerate={onGenerate} disabled={genState === "running"} />
        )}

        {sym.present && (
          <>
            <PropertiesGrid props={properties} />
            <PinTable pins={pins} />
          </>
        )}

        {genLog.length > 0 && (
          <div className="mt-5">
            <div className="text-[11px] uppercase tracking-wide text-ink-500 mb-1">
              Symbol-gen subagent
            </div>
            <div className="border border-edge rounded-md bg-[#0F1115] text-[#D6DAE0] max-h-[260px] overflow-auto thin-scroll px-2.5 py-1.5 font-mono text-[11px] leading-[1.5]">
              {genLog.map((l, i) => (
                <div key={i} className="whitespace-pre-wrap">
                  {l}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function NoSymbolPlaceholder({
  onGenerate,
  disabled,
}: {
  onGenerate: () => void;
  disabled: boolean;
}) {
  return (
    <div className="mt-4 rounded-md border border-dashed border-edge bg-rail px-4 py-8 grid place-items-center text-center">
      <div className="text-sm text-ink-700">
        No symbol generated for this part yet.
      </div>
      <div className="text-xs text-ink-500 mt-1 max-w-[360px]">
        A Claude subagent can read the datasheet PDF in this part's folder
        and emit a KiCad <code>.kicad_sym</code> with the right pin types.
      </div>
      <button
        onClick={onGenerate}
        disabled={disabled}
        className="mt-3 h-8 px-3 text-xs rounded-md bg-ink-900 text-white inline-flex items-center gap-1 disabled:opacity-50"
      >
        <I.Plus size={12} /> Generate symbol from datasheet
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SVG viewer — uses kicad-cli's exported SVG for each unit
// ---------------------------------------------------------------------------
function SymbolViewer({ mpn, units }: { mpn: string; units: string[] }) {
  const [active, setActive] = useState(0);
  const url = api.symbolSvgUrl(mpn, units[active] ?? units[0]);
  return (
    <div className="mt-4">
      <div className="flex items-baseline gap-3 mb-2">
        <h3 className="text-sm font-semibold text-ink-900">Symbol</h3>
        <span className="text-[11px] text-ink-500">
          rendered via <code>kicad-cli sym export svg</code>
        </span>
        {units.length > 1 && (
          <div className="ml-auto flex items-center gap-1">
            {units.map((u, i) => (
              <button
                key={u}
                onClick={() => setActive(i)}
                className={
                  "text-[11px] px-2 py-0.5 rounded-md border transition " +
                  (i === active
                    ? "bg-ink-900 text-white border-ink-900"
                    : "bg-white text-ink-700 border-edge hover:border-ink-300")
                }
              >
                unit {i + 1}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="border border-edge rounded-md bg-white p-4 grid place-items-center min-h-[280px]">
        <img
          src={url}
          alt={`${mpn} symbol`}
          className="max-h-[520px] max-w-full"
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Properties grid
// ---------------------------------------------------------------------------
const PROPERTY_ORDER = [
  "Reference",
  "Value",
  "Footprint",
  "MPN",
  "Manufacturer",
  "Datasheet",
  "Description",
];

function PropertiesGrid({ props }: { props: Record<string, string> }) {
  const keys = Array.from(
    new Set([...PROPERTY_ORDER.filter((k) => k in props), ...Object.keys(props)]),
  );
  if (keys.length === 0) return null;
  return (
    <div className="mt-5">
      <h3 className="text-sm font-semibold text-ink-900 mb-2">Properties</h3>
      <dl className="grid grid-cols-[140px_1fr] gap-y-1 text-[13px] border border-edge rounded-md bg-white">
        {keys.map((k, i) => (
          <div
            key={k}
            className={
              "contents " +
              (i % 2 === 1 ? "[&>*]:bg-rail/40" : "")
            }
          >
            <dt className="px-3 py-1.5 text-ink-500 border-r border-edge font-medium">
              {k}
            </dt>
            <dd className="px-3 py-1.5 text-ink-900 truncate font-mono text-[12px]">
              {props[k] || <span className="text-ink-300">—</span>}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pin table
// ---------------------------------------------------------------------------
const ETYPE_TONE: Record<string, string> = {
  power_in: "text-warn",
  power_out: "text-warn",
  input: "text-ink-700",
  output: "text-ok",
  bidirectional: "text-ink-900",
  passive: "text-ink-500",
  no_connect: "text-ink-300",
  unspecified: "text-ink-300",
  open_collector: "text-warn",
  open_emitter: "text-warn",
  tri_state: "text-ink-700",
};

function PinTable({ pins }: { pins: SymbolPin[] }) {
  if (pins.length === 0) return null;
  return (
    <div className="mt-5">
      <h3 className="text-sm font-semibold text-ink-900 mb-2">
        Pins
        <span className="ml-2 text-[11px] text-ink-500 font-normal">
          ({pins.length}) · sorted by edge
        </span>
      </h3>
      <div className="border border-edge rounded-md bg-white overflow-hidden">
        <table className="w-full text-[12.5px]">
          <thead>
            <tr className="bg-rail text-ink-500 text-[11px] uppercase tracking-wide">
              <th className="px-3 py-1.5 text-left font-medium w-16">#</th>
              <th className="px-3 py-1.5 text-left font-medium">Name</th>
              <th className="px-3 py-1.5 text-left font-medium w-28">Type</th>
              <th className="px-3 py-1.5 text-left font-medium w-20 hidden sm:table-cell">
                Edge
              </th>
            </tr>
          </thead>
          <tbody>
            {pins.map((p) => (
              <tr key={p.number} className="border-t border-edge">
                <td className="px-3 py-1 font-mono text-ink-700">{p.number}</td>
                <td className="px-3 py-1 text-ink-900">{p.name}</td>
                <td className={"px-3 py-1 font-mono text-[11.5px] " + (ETYPE_TONE[p.etype] ?? "text-ink-700")}>
                  {p.etype}
                </td>
                <td className="px-3 py-1 text-ink-500 hidden sm:table-cell">
                  {p.x < 0 ? "left" : p.x > 0 ? "right" : p.y > 0 ? "top" : "bottom"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
