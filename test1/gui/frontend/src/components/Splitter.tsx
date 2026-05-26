import { useEffect, useRef, useState, ReactNode } from "react";

interface Props {
  /** Element on the left/top side. */
  left: ReactNode;
  /** Element on the right/bottom side. */
  right: ReactNode;
  /** Which side the stored `size` is measured from. "left" keeps the left
   *  pane a fixed pixel width (used for the sidebar); "right" keeps the
   *  right pane a fixed pixel width (used for the PNG inspector). */
  anchor: "left" | "right";
  /** Initial pixel size of the anchored pane. */
  initial: number;
  /** Min/max for the anchored pane in pixels. */
  min: number;
  max: number;
  /** localStorage key — persists the user's chosen size across reloads. */
  storageKey?: string;
}

export function Splitter({ left, right, anchor, initial, min, max, storageKey }: Props) {
  const [size, setSize] = useState<number>(() => {
    if (storageKey) {
      const raw = localStorage.getItem(storageKey);
      if (raw) {
        const n = parseInt(raw, 10);
        if (!Number.isNaN(n) && n >= min && n <= max) return n;
      }
    }
    return initial;
  });
  const containerRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);

  useEffect(() => {
    if (storageKey) localStorage.setItem(storageKey, String(size));
  }, [size, storageKey]);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const px = anchor === "left" ? e.clientX - rect.left : rect.right - e.clientX;
      const clamped = Math.min(max, Math.max(min, px));
      setSize(clamped);
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
  }, [anchor, min, max]);

  const onHandleDown = (e: React.MouseEvent) => {
    e.preventDefault();
    draggingRef.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  };

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
        onDoubleClick={() => setSize(initial)}
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
