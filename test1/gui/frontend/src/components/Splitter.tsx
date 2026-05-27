import { useEffect, useMemo, useRef, useState, ReactNode } from "react";

interface Props {
  /** Element on the left/top side. */
  left: ReactNode;
  /** Element on the right/bottom side. */
  right: ReactNode;
  /** Which side the stored size is measured from. "left" anchors the left
   *  pane (used for the sidebar); "right" anchors the right pane (chat / PNG). */
  anchor: "left" | "right";
  /** Seed pixel size of the anchored pane — converted to a proportion of the
   *  container on first measure, then maintained as a fraction so the layout
   *  scales evenly when the window/display width changes. */
  initial: number;
  /** Min/max for the anchored pane in pixels. */
  min: number;
  max: number;
  /** Minimum pixels always kept visible for the *non-anchored* pane, so a
   *  drag can never collapse it to zero or push it off-screen. */
  minOther?: number;
  /** localStorage key — persists the chosen proportion across reloads. */
  storageKey?: string;
}

const HANDLE_PX = 6; // matches w-1.5

export function Splitter({ left, right, anchor, initial, min, max, minOther = 220, storageKey }: Props) {
  // Stored as a fraction (0..1) of the container so the split holds its
  // proportions across resizes and across displays of different widths.
  const [frac, setFrac] = useState<number | null>(() => {
    if (storageKey) {
      const f = parseFloat(localStorage.getItem(storageKey) ?? "");
      if (!Number.isNaN(f) && f > 0 && f < 1) return f;
    }
    return null;
  });
  const [containerW, setContainerW] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);

  // Clamp the anchored pane to [min, max] AND small enough that the other pane
  // keeps `minOther` px inside the current container.
  const clamp = (px: number, w: number) => {
    const upper = Math.max(min, Math.min(max, w - minOther - HANDLE_PX));
    return Math.min(upper, Math.max(min, px));
  };

  // Track the container width; recompute the pane size from the fraction.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setContainerW(el.getBoundingClientRect().width);
    update();
    const obs = new ResizeObserver(update);
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // Seed the fraction from the pixel `initial` once we know the container.
  useEffect(() => {
    if (frac == null && containerW > 0) {
      setFrac(clamp(initial, containerW) / containerW);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frac, containerW, initial]);

  useEffect(() => {
    if (storageKey && frac != null) localStorage.setItem(storageKey, frac.toFixed(4));
  }, [frac, storageKey]);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      if (rect.width <= 0) return;
      const px = anchor === "left" ? e.clientX - rect.left : rect.right - e.clientX;
      setFrac(clamp(px, rect.width) / rect.width);
    };
    const onUp = () => {
      if (!draggingRef.current) return;
      draggingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchor, min, max, minOther]);

  const onHandleDown = (e: React.MouseEvent) => {
    e.preventDefault();
    draggingRef.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

  const size = useMemo(
    () => (containerW > 0 && frac != null ? clamp(frac * containerW, containerW) : initial),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [containerW, frac, initial, min, max, minOther],
  );

  const leftStyle = anchor === "left" ? { width: size } : undefined;
  const rightStyle = anchor === "right" ? { width: size } : undefined;

  return (
    <div ref={containerRef} className="h-full flex min-h-0">
      <div
        className={anchor === "left" ? "shrink-0 h-full min-h-0" : "flex-1 min-w-0 h-full min-h-0"}
        style={leftStyle}
      >
        {left}
      </div>
      <div
        onMouseDown={onHandleDown}
        onDoubleClick={() => setFrac(null)}
        className="w-1.5 cursor-col-resize bg-edge/40 hover:bg-ink-300 active:bg-ink-500 transition-colors relative group"
        title="Drag to resize · double-click to reset"
      >
        <span className="absolute inset-y-0 -left-1 -right-1" />
      </div>
      <div
        className={anchor === "right" ? "shrink-0 h-full min-h-0" : "flex-1 min-w-0 h-full min-h-0"}
        style={rightStyle}
      >
        {right}
      </div>
    </div>
  );
}
