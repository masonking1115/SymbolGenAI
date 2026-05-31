import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { I } from "./Icon";
import { Glyph } from "./Glyphs";
import { buildSchematic, lintSchematic } from "./schematic";
import type { Circuit, CircuitElement, SheetMeta, SimBlock } from "../types";

interface Props {
  /** Bumped externally when a run completes so we re-fetch the manifest. */
  bust: number;
  /** True on the Simulation tab — enables the Schematic | SPICE-model toggle. */
  simMode?: boolean;
  simBlocks?: SimBlock[];
  selectedSimBlock?: string;
}

const PRETTY: Record<string, string> = {
  test1: "root",
  fmc: "FMC",
  power: "power",
  bobcat: "Bobcat",
  eeprom: "EEPROM",
  bias: "bias",
  connectors: "connectors",
};

const MIN_ZOOM = 0.05;
const MAX_ZOOM = 32;

type ViewMode = "schematic" | "model";

interface SheetRegion {
  viewBox: [number, number];
  refdes: Record<string, { x: number; y: number }>;
}
interface SimRegion {
  sheets: Record<string, SheetRegion>;   // stem -> located refdes on that sheet
  sheets_with_parts: string[];           // sheets to highlight in the tab strip
  refdes: string[];                      // all real refdes the block simulates
  primary: string | null;                // sheet to switch to first
}

export function PngViewer({ bust, simMode, simBlocks, selectedSimBlock }: Props) {
  const [sheets, setSheets] = useState<SheetMeta[]>([]);
  const [active, setActive] = useState<string>("test1");
  const [mode, setMode] = useState<ViewMode>("schematic");

  useEffect(() => {
    api
      .sheets()
      .then((r) => setSheets(r.sheets))
      .catch(() => setSheets([]));
  }, [bust]);

  // Leaving the Simulation tab falls back to the schematic.
  useEffect(() => {
    if (!simMode && mode === "model") setMode("schematic");
  }, [simMode, mode]);

  const idx = Math.max(0, sheets.findIndex((s) => s.name === active));
  const meta = sheets[idx];

  const step = (delta: number) => {
    if (!sheets.length) return;
    const i = (idx + delta + sheets.length) % sheets.length;
    setActive(sheets[i].name);
  };

  const block = simBlocks?.find((b) => b.id === selectedSimBlock);

  // Simulated-region highlight (MULTI-SHEET): when a sim block is selected,
  // fetch which parts it simulates + where they sit on EACH sheet, so the
  // Schematic view can box them per sheet and the tab strip can flag sheets that
  // contain a simulated part. Auto-switches to the block's primary sheet.
  const [region, setRegion] = useState<SimRegion | null>(null);
  const [showRegion, setShowRegion] = useState(true);
  useEffect(() => {
    if (!simMode || !block) { setRegion(null); return; }
    let cancelled = false;
    api.simRegion(block.id)
      .then((r) => { if (!cancelled) setRegion(r.sheets_with_parts.length ? r : null); })
      .catch(() => { if (!cancelled) setRegion(null); });
    return () => { cancelled = true; };
  }, [simMode, block?.id, bust]);
  // When the region resolves (schematic side), jump to its primary sheet.
  useEffect(() => {
    if (mode === "schematic" && region?.primary && sheets.some((s) => s.name === region.primary))
      setActive(region.primary);
  }, [region?.primary, mode, sheets]);

  // sheets that contain a simulated part — for highlighting the tab strip
  const simSheets = useMemo(
    () => new Set(mode === "schematic" && region ? region.sheets_with_parts : []),
    [mode, region],
  );
  const activeRegion = region?.sheets[active];           // located refdes on the active sheet
  const regionActive = !!activeRegion && showRegion && mode === "schematic";

  return (
    <div className="h-full flex flex-col bg-white border-l border-edge min-w-0 min-h-0">
      <Toolbar
        meta={meta}
        idx={idx}
        total={sheets.length}
        onPrev={() => step(-1)}
        onNext={() => step(1)}
        simMode={!!simMode}
        mode={mode}
        onMode={setMode}
        block={block}
        regionCount={activeRegion ? Object.keys(activeRegion.refdes).length : 0}
        showRegion={showRegion}
        onToggleRegion={() => setShowRegion((v) => !v)}
      />
      <div className="flex-1 min-h-0">
        {mode === "model" ? (
          <ModelView block={block} bust={bust} />
        ) : meta ? (
          // Key by sheet NAME only — NOT mtime — so a Refresh (which bumps the
          // sheet mtime) does not remount Canvas and throw away the user's
          // zoom/pan. The fresh image still loads: mtime stays in the ImgLayer
          // src (cache-bust), and Canvas re-fits only if the new image's natural
          // size actually changed (its fit effect keys on `nat`).
          <Canvas key={meta.name}>
            <ImgLayer src={api.pngUrl(meta.name, meta.mtime)} />
            {regionActive && <RegionOverlay region={activeRegion!} />}
          </Canvas>
        ) : (
          <div className="h-full grid place-items-center text-ink-500 text-sm">
            No renders yet. Run the generator to produce sheet PNGs.
          </div>
        )}
      </div>
      {(mode === "schematic" || simSheets.size > 0) && sheets.length > 0 && (
        <div className="border-t border-edge px-2 py-1.5 flex flex-wrap items-center gap-1">
          {sheets.map((s) => {
            const isActive = s.name === active && mode === "schematic";
            const hasSim = simSheets.has(s.name);
            const count = region?.sheets[s.name]
              ? Object.keys(region.sheets[s.name].refdes).length : 0;
            return (
              <button
                key={s.name}
                onClick={() => { setActive(s.name); if (mode !== "schematic") setMode("schematic"); }}
                title={hasSim ? `${count} simulated parts on ${s.name}` : undefined}
                className={
                  "text-[11px] px-2 py-0.5 rounded border transition inline-flex items-center gap-1 " +
                  (isActive
                    ? "bg-ink-900 text-white border-ink-900"
                    : hasSim
                      ? "bg-blue-50 text-blue-700 border-blue-300 hover:border-blue-400"
                      : "bg-white text-ink-700 border-edge hover:border-ink-300")
                }
              >
                {hasSim && (
                  <span className={"w-1.5 h-1.5 rounded-full " + (isActive ? "bg-white" : "bg-blue-500")} />
                )}
                {PRETTY[s.name] || s.name}
                {hasSim && count > 0 && (
                  <span className={"tabular-nums " + (isActive ? "text-white/80" : "text-blue-500")}>
                    {count}
                  </span>
                )}
              </button>
            );
          })}
          {simSheets.size > 0 && (
            <span className="ml-1 text-[10px] text-ink-400">● = simulated parts</span>
          )}
        </div>
      )}
    </div>
  );
}

function Toolbar({
  meta,
  idx,
  total,
  onPrev,
  onNext,
  simMode,
  mode,
  onMode,
  block,
  regionCount,
  showRegion,
  onToggleRegion,
}: {
  meta?: SheetMeta;
  idx: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
  simMode: boolean;
  mode: ViewMode;
  onMode: (m: ViewMode) => void;
  block?: SimBlock;
  regionCount?: number;
  showRegion?: boolean;
  onToggleRegion?: () => void;
}) {
  return (
    <div className="h-10 px-3 flex items-center gap-2 border-b border-edge text-xs text-ink-700 shrink-0">
      {simMode ? (
        <>
          <Segmented mode={mode} onMode={onMode} />
          <span className="text-ink-500 truncate">
            {mode === "model"
              ? block
                ? `${block.title} · simulated model`
                : "select a block"
              : meta
                ? `test1 / ${PRETTY[meta.name] || meta.name}`
                : "no renders"}
          </span>
        </>
      ) : (
        <span className="font-medium">
          {meta ? `test1 / ${PRETTY[meta.name] || meta.name}` : "no renders"}
        </span>
      )}
      {mode === "schematic" && (
        <>
          {/* simulated-region toggle: only when THIS sheet has simulated parts */}
          {!!regionCount && onToggleRegion && (
            <button
              onClick={onToggleRegion}
              title={`${regionCount} simulated parts on this sheet`}
              className={
                "ml-1 px-2 py-0.5 rounded border text-[11px] transition " +
                (showRegion
                  ? "bg-blue-50 border-blue-300 text-blue-700"
                  : "bg-white border-edge text-ink-500 hover:border-ink-300")
              }
            >
              ◳ simulated ({regionCount})
            </button>
          )}
          <span className="text-ink-500 ml-auto">{meta ? `${idx + 1} / ${total}` : ""}</span>
          <div className="flex items-center gap-1">
            <button onClick={onPrev} className="p-1 hover:bg-rail rounded text-ink-500">
              <I.Back />
            </button>
            <button onClick={onNext} className="p-1 hover:bg-rail rounded text-ink-500">
              <I.Forward />
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function Segmented({ mode, onMode }: { mode: ViewMode; onMode: (m: ViewMode) => void }) {
  const tab = (m: ViewMode, label: string) => (
    <button
      onClick={() => onMode(m)}
      className={
        "px-2 py-0.5 text-[11px] rounded transition " +
        (mode === m ? "bg-white text-ink-900 shadow-sm" : "text-ink-500 hover:text-ink-700")
      }
    >
      {label}
    </button>
  );
  return (
    <div className="inline-flex items-center gap-0.5 rounded-md border border-edge bg-rail p-0.5">
      {tab("schematic", "Schematic")}
      {tab("model", "SPICE model")}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SPICE-model view: fetch the parsed circuit for the selected block and draw it.

function ModelView({ block, bust }: { block?: SimBlock; bust: number }) {
  const [circuit, setCircuit] = useState<Circuit | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "empty" | "ready">("idle");

  // A block's topology is shared across its sim types; pick a representative
  // implemented sim type to build the deck from.
  const simType = useMemo(
    () => block?.sim_types.find((s) => s.status === "implemented")?.type,
    [block],
  );

  useEffect(() => {
    if (!block || !simType) {
      setCircuit(null);
      setState(block ? "empty" : "idle");
      return;
    }
    let cancelled = false;
    setState("loading");
    api
      .simCircuit(block.id, simType)
      .then((r) => {
        if (cancelled) return;
        setCircuit(r.circuit);
        setState(r.circuit && r.circuit.elements.length ? "ready" : "empty");
      })
      .catch(() => {
        if (cancelled) return;
        setCircuit(null);
        setState("empty");
      });
    return () => {
      cancelled = true;
    };
  }, [block, simType, bust]);

  // Selected component (by ref) for the detail side panel. Lives here so the
  // panel can render OUTSIDE the pan/zoom canvas as a fixed overlay.
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => { setSelected(null); }, [block?.id, simType]);

  if (state === "idle")
    return <Hint>Select a test block to see its simulated circuit.</Hint>;
  if (state === "loading")
    return <Hint>Building the SPICE model…</Hint>;
  if (state === "empty" || !circuit)
    return (
      <Hint>
        No SPICE model for this block
        {block ? <> — <span className="font-mono">{block.id}</span> has no runnable deck.</> : null}
      </Hint>
    );

  const selEl = selected ? circuit.elements.find((e) => e.ref === selected) ?? null : null;

  return (
    <div className="relative h-full w-full">
      <Canvas key={block?.id + (simType ?? "")}>
        <SchematicView circuit={circuit} selected={selected} onSelect={setSelected} />
      </Canvas>
      {selEl && (
        <ComponentPanel el={selEl} circuit={circuit} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

// Side panel: full parameters for the selected component. Reads what we already
// have — element value/nets/note + (for X-instances) the subckt's model params.
function ComponentPanel({ el, circuit, onClose }: {
  el: CircuitElement; circuit: Circuit; onClose: () => void;
}) {
  const sub = el.subckt ? circuit.subckts[el.subckt] : undefined;
  const row = (k: string, v: React.ReactNode) => (
    <div className="flex justify-between gap-3 py-0.5 border-b border-edge/40 text-[11px]">
      <span className="text-ink-500">{k}</span>
      <span className="font-mono text-ink-900 text-right break-all">{v}</span>
    </div>
  );
  return (
    <div className="absolute top-2 right-2 w-64 max-h-[calc(100%-1rem)] overflow-auto
                    rounded-md border border-edge bg-white/95 backdrop-blur shadow-lg p-3 text-xs">
      <div className="flex items-center justify-between mb-2">
        <span className="font-mono font-semibold text-ink-900 text-sm">{el.ref}</span>
        <button onClick={onClose} className="text-ink-400 hover:text-ink-700 px-1">✕</button>
      </div>
      {/* tie back to the real schematic: the netlist refdes, or model-only */}
      <div className="mb-2">
        {el.refdes ? (
          <span className="inline-flex items-center gap-1 rounded border border-blue-300 bg-blue-50 px-1.5 py-0.5 text-[11px] text-blue-700">
            schematic part <span className="font-mono font-semibold">{el.refdes}</span>
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded border border-edge bg-rail px-1.5 py-0.5 text-[11px] text-ink-500"
                title="behavioral element (boundary source, ammeter, or load stub) — no physical part on the schematic">
            model-only
          </span>
        )}
      </div>
      {row("kind", el.kind)}
      {el.subckt ? row("subckt", el.subckt) : el.value ? row("value", el.value) : null}
      {row("nets", el.nodes.join(", "))}
      {sub && sub.ports.length > 0 && row("ports", sub.ports.join(" "))}
      {sub && Object.keys(sub.params).length > 0 && (
        <div className="mt-2">
          <div className="text-[10px] uppercase tracking-wide text-ink-500 mb-1">model params</div>
          {Object.entries(sub.params).map(([k, v]) => row(k, v))}
        </div>
      )}
      {el.note && (
        <div className="mt-2">
          <div className="text-[10px] uppercase tracking-wide text-ink-500 mb-1">deck note</div>
          <div className="text-[11px] text-ink-700 leading-snug">{el.note}</div>
        </div>
      )}
    </div>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return (
    <div className="h-full grid place-items-center px-6 text-center text-ink-500 text-sm">
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Schematic view: real device glyphs (op-amp triangle, R zig-zag, cap, MOSFET,
// ground) placed on a grid and connected by orthogonal wires — an LTspice-style
// drawing of the simulated deck. Layout/routing live in schematic.ts; glyph
// drawing in Glyphs.tsx.

function SchematicView({ circuit, selected, onSelect }: {
  circuit: Circuit;
  selected: string | null;
  onSelect: (ref: string | null) => void;
}) {
  const sch = useMemo(() => buildSchematic(circuit), [circuit]);
  // Dev-time regression guard: the layout aims for zero body-crossings/overlaps;
  // warn (don't fail) if a deck shape slips past the router so it's visible.
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    const issues = lintSchematic(sch);
    if (issues.length) console.warn(`[schematic] ${circuit.title}:`, issues);
  }, [sch, circuit.title]);
  const [litNet, setLitNet] = useState<string | null>(null);
  const [hoverRef, setHoverRef] = useState<string | null>(null);
  const hovered = sch.glyphs.find((g) => g.ref === hoverRef);

  return (
    <svg viewBox={`0 0 ${sch.W} ${sch.H}`} width={sch.W} height={sch.H}
         className="select-none" style={{ overflow: "visible" }}>
      {/* wires (under glyphs) */}
      {sch.wires.map((w, i) => {
        const lit = litNet === w.net;
        return (
          <line key={i} x1={w.x1} y1={w.y1} x2={w.x2} y2={w.y2}
                stroke={lit ? "#2563eb" : "#1E293B"} strokeWidth={lit ? 2 : 1.3}
                onMouseEnter={() => setLitNet(w.net)} onMouseLeave={() => setLitNet(null)} />
        );
      })}
      {/* junction dots */}
      {sch.junctions.map((j, i) => (
        <circle key={i} cx={j.x} cy={j.y} r={2.6}
                fill={litNet === j.net ? "#2563eb" : "#1E293B"} />
      ))}
      {/* ground symbols */}
      {sch.grounds.map((gnd, i) => (
        <GroundSym key={i} x={gnd.x} y={gnd.y} lit={litNet === gnd.net}
                   onEnter={() => setLitNet(gnd.net)} onLeave={() => setLitNet(null)} />
      ))}
      {/* net labels — backing rect keeps them legible over wires */}
      {sch.labels.map((l, i) => {
        const anchor = l.anchor ?? "middle";
        const w = l.text.length * 5.4 + 4;
        const rx = anchor === "start" ? l.x - 2 : l.x - w / 2;
        return (
          <g key={i} onMouseEnter={() => setLitNet(l.text)} onMouseLeave={() => setLitNet(null)}>
            <rect x={rx} y={l.y - 8} width={w} height={11} fill="#FCFCFD" opacity={0.85} />
            <text x={l.x} y={l.y} textAnchor={anchor} fontSize={9}
                  fontFamily="ui-monospace, monospace"
                  fill={litNet === l.text ? "#2563eb" : "#64748B"}>
              {l.text}
            </text>
          </g>
        );
      })}
      {/* glyphs (on top). Each has a padded transparent hit-rect so it's easy
          to click, a selection highlight box, and click-to-select. */}
      {sch.glyphs.map((g) => {
        const pad = 14;
        const isSel = selected === g.ref;
        const isHot = isSel || hoverRef === g.ref;
        return (
          <g key={g.ref}
             onMouseEnter={() => setHoverRef(g.ref)} onMouseLeave={() => setHoverRef(null)}
             onClick={(e) => { e.stopPropagation(); onSelect(isSel ? null : g.ref); }}
             style={{ cursor: "pointer" }}>
            <title>
              {`${g.ref}  (${g.el.kind})\n` +
                (g.el.refdes ? `schematic: ${g.el.refdes}\n` : "model-only\n") +
                (g.el.subckt ? `subckt: ${g.el.subckt}\n` : g.value ? `value: ${g.value}\n` : "") +
                `nodes: ${g.el.nodes.join(", ")}` + (g.note ? `\n${g.note}` : "")}
            </title>
            {/* selection highlight */}
            {isSel && (
              <rect x={g.x - pad} y={g.y - pad} width={g.w + pad * 2} height={g.h + pad * 2}
                    rx={4} fill="#2563eb" fillOpacity={0.08} stroke="#2563eb"
                    strokeOpacity={0.5} strokeDasharray="4 3" />
            )}
            <Glyph g={g} lit={isHot} />
            {/* transparent hit target (drawn last so it captures clicks) */}
            <rect x={g.x - pad} y={g.y - pad} width={g.w + pad * 2} height={g.h + pad * 2}
                  fill="transparent" />
          </g>
        );
      })}
      {/* hover detail card */}
      {hovered && (hovered.note || hovered.value) && (
        <g>
          <rect x={6} y={sch.H - 38} width={Math.min(sch.W - 12, 380)} height={32} rx={4}
                fill="#0F172A" opacity={0.92} />
          <text x={14} y={sch.H - 24} fontSize={10} fontWeight={700}
                fontFamily="ui-monospace, monospace" fill="#fff">
            {hovered.ref}
            <tspan fontWeight={400} fill="#94A3B8"> · {hovered.el.subckt ?? hovered.value}</tspan>
          </text>
          <text x={14} y={sch.H - 12} fontSize={9}
                fontFamily="ui-monospace, monospace" fill="#CBD5E1">
            {trunc(hovered.note || hovered.el.nodes.join(", "), 58)}
          </text>
        </g>
      )}
    </svg>
  );
}

function GroundSym({ x, y, lit, onEnter, onLeave }: {
  x: number; y: number; lit: boolean; onEnter: () => void; onLeave: () => void;
}) {
  const s = lit ? "#2563eb" : "#1E293B";
  return (
    <g onMouseEnter={onEnter} onMouseLeave={onLeave}>
      <line x1={x} y1={y} x2={x} y2={y + 6} stroke={s} strokeWidth={1.3} />
      <line x1={x - 8} y1={y + 6} x2={x + 8} y2={y + 6} stroke={s} strokeWidth={1.3} />
      <line x1={x - 5} y1={y + 9} x2={x + 5} y2={y + 9} stroke={s} strokeWidth={1.3} />
      <line x1={x - 2} y1={y + 12} x2={x + 2} y2={y + 12} stroke={s} strokeWidth={1.3} />
    </g>
  );
}

function trunc(s: string, n: number): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}


// ---------------------------------------------------------------------------
// Pan/zoom canvas. Wraps arbitrary content (an <img> or an <svg>) and applies a
// translate+scale transform so we get smooth wheel-zoom-toward-cursor and
// drag-pan without re-flowing the layout. Content reports its natural size via
// the NaturalSizeContext so "fit" works for both images and SVG graphs.
//
// Controls
// --------
//  - Mouse wheel (or trackpad pinch)  → zoom toward cursor
//  - Click + drag                     → pan
//  - Double-click                     → fit
//  - + / - / 0 / F overlay buttons    → zoom in/out / 100% / fit
interface View {
  zoom: number;
  tx: number;
  ty: number;
}

const NaturalSizeContext = createContext<(w: number, h: number) => void>(() => {});

export function ImgLayer({ src }: { src: string }) {
  const setNat = useContext(NaturalSizeContext);
  return (
    <img
      src={src}
      alt="schematic"
      draggable={false}
      onLoad={(e) => setNat(e.currentTarget.naturalWidth, e.currentTarget.naturalHeight)}
      style={{
        position: "absolute", left: 0, top: 0,
        transformOrigin: "0 0",
        willChange: "transform",
        userSelect: "none", pointerEvents: "none", maxWidth: "none",
      }}
    />
  );
}

// Highlight the simulated parts on the rendered sheet. The sheet is an SVG-as-
// <img>, so its natural size == the viewBox; this overlay SVG matches that size
// and sits at (0,0) in the same transformed space, aligning 1:1 with the image.
// Draws a dim wash over the whole sheet, then a bright box around each simulated
// designator (the SVG gives the label anchor; we box a part-sized area near it).
function RegionOverlay({ region }: { region: SheetRegion }) {
  const [w, h] = region.viewBox;
  if (!w || !h) return null;
  // designator label sits just above/left of the body; bias the box to cover it.
  const BW = 150, BH = 120, DX = -70, DY = -30;
  const boxes = Object.entries(region.refdes).map(([ref, p]) => ({
    ref, x: p.x + DX, y: p.y + DY,
  }));
  return (
    <svg
      width={w} height={h} viewBox={`0 0 ${w} ${h}`}
      style={{ position: "absolute", left: 0, top: 0, transformOrigin: "0 0",
               pointerEvents: "none", overflow: "visible" }}
    >
      <defs>
        <mask id="simholes">
          <rect x={0} y={0} width={w} height={h} fill="white" />
          {boxes.map((b, i) => (
            <rect key={i} x={b.x} y={b.y} width={BW} height={BH} rx={8} fill="black" />
          ))}
        </mask>
      </defs>
      {/* dim everything except the simulated boxes */}
      <rect x={0} y={0} width={w} height={h} fill="#FCFCFD" opacity={0.62} mask="url(#simholes)" />
      {/* bright outline on each simulated part */}
      {boxes.map((b, i) => (
        <rect key={i} x={b.x} y={b.y} width={BW} height={BH} rx={8}
              fill="#2563eb" fillOpacity={0.07} stroke="#2563eb" strokeOpacity={0.7}
              strokeWidth={2.5} />
      ))}
    </svg>
  );
}

export function Canvas({ children }: { children: React.ReactNode }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  // zoom/tx/ty live in ONE state object and are always updated together by a
  // single pure updater. They are interdependent during zoom-toward-cursor, and
  // nesting setTx/setTy inside a setZoom updater is an impure side-effect that
  // React.StrictMode double-invokes in dev — that double-applied the zoom
  // translation, so the focal point landed below-right of the cursor instead of
  // under it. One object + one updater removes that whole class of bug.
  const [view, setView] = useState<View>({ zoom: 1, tx: 0, ty: 0 });
  const { zoom, tx, ty } = view;
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null);
  const [grabbing, setGrabbing] = useState(false);
  const dragRef = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null);

  const reportNat = useCallback((w: number, h: number) => setNat({ w, h }), []);

  const fit = useCallback(() => {
    if (!wrapRef.current || !nat) return;
    const r = wrapRef.current.getBoundingClientRect();
    const margin = 16;
    const scale = Math.min(
      (r.width - margin * 2) / nat.w,
      (r.height - margin * 2) / nat.h,
    );
    const z = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, scale));
    setView({
      zoom: z,
      tx: (r.width - nat.w * z) / 2,
      ty: (r.height - nat.h * z) / 2,
    });
  }, [nat]);

  // Fit on load and on container resize.
  useEffect(() => {
    if (!nat) return;
    fit();
    const obs = new ResizeObserver(() => fit());
    if (wrapRef.current) obs.observe(wrapRef.current);
    return () => obs.disconnect();
  }, [nat, fit]);

  // Zoom toward a point (px, py) in the wrapper's local coords: keep the content
  // point currently under (px, py) fixed.
  const zoomAt = useCallback((factor: number, px: number, py: number) => {
    setView((v) => {
      const next = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, v.zoom * factor));
      if (next === v.zoom) return v; // clamped — no change, avoid drift
      const ratio = next / v.zoom;
      return {
        zoom: next,
        tx: px - (px - v.tx) * ratio,
        ty: py - (py - v.ty) * ratio,
      };
    });
  }, []);

  // Non-passive wheel listener so we can preventDefault.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      const factor = Math.exp(-e.deltaY * 0.0015);
      zoomAt(factor, cx, cy);
    };
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, [zoomAt]);

  const onMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    dragRef.current = { x: e.clientX, y: e.clientY, tx, ty };
    setGrabbing(true);
    e.preventDefault();
  };
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const d = dragRef.current;
      if (!d) return;
      setView((v) => ({ ...v, tx: d.tx + (e.clientX - d.x), ty: d.ty + (e.clientY - d.y) }));
    };
    const onUp = () => {
      if (!dragRef.current) return;
      dragRef.current = null;
      setGrabbing(false);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  const zoomBy = (factor: number) => {
    if (!wrapRef.current) return;
    const r = wrapRef.current.getBoundingClientRect();
    zoomAt(factor, r.width / 2, r.height / 2);
  };

  const reset100 = () => {
    if (!wrapRef.current || !nat) return;
    const r = wrapRef.current.getBoundingClientRect();
    setView({ zoom: 1, tx: (r.width - nat.w) / 2, ty: (r.height - nat.h) / 2 });
  };

  return (
    <div
      ref={wrapRef}
      onMouseDown={onMouseDown}
      onDoubleClick={fit}
      style={{ cursor: grabbing ? "grabbing" : "grab" }}
      className="relative w-full h-full overflow-hidden bg-[#FCFCFD] select-none"
    >
      {/* checkerboard subtle background so content edges read */}
      <div
        aria-hidden
        className="absolute inset-0 opacity-[0.35] pointer-events-none"
        style={{
          backgroundImage:
            "linear-gradient(45deg, #F0F1F4 25%, transparent 25%, transparent 75%, #F0F1F4 75%), linear-gradient(45deg, #F0F1F4 25%, transparent 25%, transparent 75%, #F0F1F4 75%)",
          backgroundSize: "16px 16px",
          backgroundPosition: "0 0, 8px 8px",
        }}
      />
      <div
        ref={contentRef}
        style={{
          position: "absolute", left: 0, top: 0,
          transform: `translate(${tx}px, ${ty}px) scale(${zoom})`,
          transformOrigin: "0 0",
          willChange: "transform",
          imageRendering: zoom >= 2 ? "pixelated" : "auto",
        }}
      >
        <NaturalSizeContext.Provider value={reportNat}>
          <MeasuredContent onSize={reportNat}>{children}</MeasuredContent>
        </NaturalSizeContext.Provider>
      </div>
      <ZoomOverlay
        zoom={zoom}
        onIn={() => zoomBy(1.25)}
        onOut={() => zoomBy(1 / 1.25)}
        onFit={fit}
        on100={reset100}
        disabled={!nat}
      />
    </div>
  );
}

// For SVG content (no onLoad), measure the rendered size once and report it so
// `fit` works. Images report via ImgLayer's onLoad and ignore this.
function MeasuredContent({ children, onSize }: { children: React.ReactNode; onSize: (w: number, h: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current?.firstElementChild as SVGSVGElement | HTMLElement | null;
    if (!el) return;
    // SVG: prefer its intrinsic width/height attributes; else measured box.
    const w = (el as SVGSVGElement).width?.baseVal?.value || el.getBoundingClientRect().width;
    const h = (el as SVGSVGElement).height?.baseVal?.value || el.getBoundingClientRect().height;
    if (w && h) onSize(w, h);
  }, [children, onSize]);
  return <div ref={ref} style={{ display: "inline-block" }}>{children}</div>;
}

function ZoomOverlay({
  zoom,
  onIn,
  onOut,
  onFit,
  on100,
  disabled,
}: {
  zoom: number;
  onIn: () => void;
  onOut: () => void;
  onFit: () => void;
  on100: () => void;
  disabled: boolean;
}) {
  const btn = "px-2 py-1 text-xs hover:bg-rail rounded";
  return (
    <div className="absolute bottom-2 right-2 flex items-center gap-0.5 bg-white/90 backdrop-blur border border-edge rounded-md shadow-sm">
      <button disabled={disabled} onClick={onOut} className={btn} title="Zoom out">
        −
      </button>
      <span className="text-[11px] text-ink-500 w-10 text-center tabular-nums">
        {Math.round(zoom * 100)}%
      </span>
      <button disabled={disabled} onClick={onIn} className={btn} title="Zoom in">
        +
      </button>
      <span className="w-px h-4 bg-edge mx-1" />
      <button disabled={disabled} onClick={onFit} className={btn} title="Fit">
        fit
      </button>
      <button disabled={disabled} onClick={on100} className={btn} title="100%">
        1:1
      </button>
    </div>
  );
}
