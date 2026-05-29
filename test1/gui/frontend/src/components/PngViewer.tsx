import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { I } from "./Icon";
import type { SheetMeta } from "../types";

interface Props {
  /** Bumped externally when a run completes so we re-fetch the manifest. */
  bust: number;
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

export function PngViewer({ bust }: Props) {
  const [sheets, setSheets] = useState<SheetMeta[]>([]);
  const [active, setActive] = useState<string>("test1");

  useEffect(() => {
    api
      .sheets()
      .then((r) => setSheets(r.sheets))
      .catch(() => setSheets([]));
  }, [bust]);

  const idx = Math.max(0, sheets.findIndex((s) => s.name === active));
  const meta = sheets[idx];

  const step = (delta: number) => {
    if (!sheets.length) return;
    const i = (idx + delta + sheets.length) % sheets.length;
    setActive(sheets[i].name);
  };

  return (
    <div className="h-full flex flex-col bg-white border-l border-edge min-w-0 min-h-0">
      <Toolbar
        meta={meta}
        idx={idx}
        total={sheets.length}
        onPrev={() => step(-1)}
        onNext={() => step(1)}
      />
      <div className="flex-1 min-h-0">
        {meta ? (
          <Canvas key={meta.name + meta.mtime} src={api.pngUrl(meta.name, meta.mtime)} />
        ) : (
          <div className="h-full grid place-items-center text-ink-500 text-sm">
            No renders yet. Run the generator to produce sheet PNGs.
          </div>
        )}
      </div>
      <div className="border-t border-edge px-2 py-1.5 flex flex-wrap gap-1">
        {sheets.map((s) => (
          <button
            key={s.name}
            onClick={() => setActive(s.name)}
            className={
              "text-[11px] px-2 py-0.5 rounded border transition " +
              (s.name === active
                ? "bg-ink-900 text-white border-ink-900"
                : "bg-white text-ink-700 border-edge hover:border-ink-300")
            }
          >
            {PRETTY[s.name] || s.name}
          </button>
        ))}
      </div>
    </div>
  );
}

function Toolbar({
  meta,
  idx,
  total,
  onPrev,
  onNext,
}: {
  meta?: SheetMeta;
  idx: number;
  total: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <div className="h-10 px-3 flex items-center gap-2 border-b border-edge text-xs text-ink-700 shrink-0">
      <span className="font-medium">
        {meta ? `test1 / ${PRETTY[meta.name] || meta.name}` : "no renders"}
      </span>
      <span className="text-ink-500">{meta ? `${idx + 1} / ${total}` : ""}</span>
      <div className="ml-auto flex items-center gap-1">
        <button onClick={onPrev} className="p-1 hover:bg-rail rounded text-ink-500">
          <I.Back />
        </button>
        <button onClick={onNext} className="p-1 hover:bg-rail rounded text-ink-500">
          <I.Forward />
        </button>
      </div>
    </div>
  );
}

/**
 * Pan/zoom canvas. Transforms an <img> with translate+scale so we can do
 * smooth wheel-zoom-toward-cursor and drag-pan without re-flowing the layout.
 *
 * Controls
 * --------
 *  - Mouse wheel (or trackpad pinch)  → zoom toward cursor
 *  - Click + drag                     → pan
 *  - Double-click                     → fit
 *  - + / - / 0 / F overlay buttons    → zoom in/out / 100% / fit
 */
interface View {
  zoom: number;
  tx: number;
  ty: number;
}

function Canvas({ src }: { src: string }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
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

  // Zoom toward a point (px, py) given in the wrapper's local coordinate space
  // (same space as tx/ty): keep the image point currently under (px, py) fixed.
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

  // Attach non-passive wheel listener so we can preventDefault.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      // Exponential zoom feels smoother than linear. deltaY is +ve when
      // scrolling down → zoom out.
      const factor = Math.exp(-e.deltaY * 0.0015);
      zoomAt(factor, cx, cy);
    };
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, [zoomAt]);

  const onMouseDown = (e: React.MouseEvent) => {
    // Left button only.
    if (e.button !== 0) return;
    dragRef.current = { x: e.clientX, y: e.clientY, tx, ty };
    setGrabbing(true);
    e.preventDefault();
  };
  // Window-level move/up so dragging continues even if the cursor leaves the pane.
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

  // Overlay +/- buttons zoom toward the viewport center.
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
      {/* checkerboard subtle background so the image edges read */}
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
      <img
        ref={imgRef}
        src={src}
        alt="schematic"
        draggable={false}
        onLoad={(e) => {
          const im = e.currentTarget;
          setNat({ w: im.naturalWidth, h: im.naturalHeight });
        }}
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          transform: `translate(${tx}px, ${ty}px) scale(${zoom})`,
          transformOrigin: "0 0",
          imageRendering: zoom >= 2 ? "pixelated" : "auto",
          willChange: "transform",
          userSelect: "none",
          pointerEvents: "none",
          maxWidth: "none",
        }}
      />
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
