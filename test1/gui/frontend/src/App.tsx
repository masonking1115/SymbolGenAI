import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { PngViewer } from "./components/PngViewer";
import { DiffPanes, type DiffMode } from "./components/DiffPanes";
import { Splitter } from "./components/Splitter";
import { AgentRail } from "./components/AgentRail";
import type { OpenFile } from "./components/ResourceEditor";
// Lazy so CodeMirror (~550KB) only loads when a file is actually opened.
const ResourceEditor = lazy(() =>
  import("./components/ResourceEditor").then((m) => ({ default: m.ResourceEditor })));
import { Generator } from "./tabs/Generator";
import { Library } from "./tabs/Library";
import { Resources } from "./tabs/Resources";
import { Review } from "./tabs/Review";
import { Simulation } from "./tabs/Simulation";
import type { LoopSummary, PhaseEvent, SimBlock, SimGroup, StagePhase, TabKey } from "./types";

// Diff data shape (kept in App.tsx because the right pane reads it). Matches
// the structure returned by api.loopDiff(loopId).
interface DiffData {
  loop_id: string;
  sheets: Record<string, {
    viewBox: string;
    added: Record<string, { x: number; y: number; kind: "added" }>;
    removed: Record<string, { x: number; y: number; kind: "removed" }>;
    changed: Record<string, { x: number; y: number; kind: "changed"; from_value: string; to_value: string }>;
    count: number;
  }>;
}

const TAB_TITLES: Record<TabKey, string> = {
  resources: "Design Resources / test1",
  library: "Library / Bobcat Carrier",
  generator: "Schematic Generator / test1",
  review: "Design Review / test1",
  simulation: "Simulation / test1",
};

const TAB_LS_KEY = "test1.activeTab";
const VALID_TABS: TabKey[] = ["resources", "library", "generator", "review", "simulation"];
function initialTab(): TabKey {
  try {
    const v = localStorage.getItem(TAB_LS_KEY) as TabKey | null;
    if (v && VALID_TABS.includes(v)) return v;
  } catch { /* ignore */ }
  return "generator";
}

// Persist whether the schematic/file right pane is shown, so hiding it survives a
// refresh. Default to shown when nothing's stored.
const PNG_OPEN_LS_KEY = "test1.pngOpen";
function initialPngOpen(): boolean {
  try {
    return localStorage.getItem(PNG_OPEN_LS_KEY) !== "0";
  } catch { /* ignore */ }
  return true;
}

export default function App() {
  // Persist the active tab so a refresh keeps you on the tab you were on.
  const [tab, setTabRaw] = useState<TabKey>(initialTab);
  const setTab = useCallback((t: TabKey) => {
    setTabRaw(t);
    // An open file viewer belongs to the tab it was opened from — drop it on
    // any tab switch so the schematic is the default again.
    setOpenFile(null);
    setRightView("schematic");
    try { localStorage.setItem(TAB_LS_KEY, t); } catch { /* ignore */ }
  }, []);

  // Cross-tab deep-link to a library part: Design Resources → Datasheets has a
  // "view part" link per MPN that switches to the Library tab and auto-selects
  // it. Mirrors the selectSimBlock → setTab("simulation") pattern below.
  const [pendingPart, setPendingPart] = useState<string | null>(null);
  const goToPart = useCallback((mpn: string) => {
    setPendingPart(mpn);
    setTab("library");
  }, [setTab]);

  // Whether the shared right pane (schematic / file viewer) is open at all.
  // Persisted so hiding it is retained across a refresh.
  const [pngOpen, setPngOpenRaw] = useState(initialPngOpen);
  const setPngOpen = useCallback((next: boolean | ((v: boolean) => boolean)) => {
    setPngOpenRaw((prev) => {
      const v = typeof next === "function" ? next(prev) : next;
      try { localStorage.setItem(PNG_OPEN_LS_KEY, v ? "1" : "0"); } catch { /* ignore */ }
      return v;
    });
  }, []);
  // A resource/datasheet file opened from Library or Design Resources. When set,
  // it takes over the shared right pane (replacing the schematic viewer), with a
  // toggle to flip back. Cleared on Close or when switching tabs.
  const [openFile, setOpenFile] = useState<OpenFile | null>(null);
  // Which view the shared right pane shows: the schematic or the open file.
  const [rightView, setRightView] = useState<"schematic" | "file">("schematic");
  const onOpenFile = useCallback((f: OpenFile) => {
    setOpenFile(f);
    setRightView("file");
    setPngOpen(true);   // ensure the pane is visible
  }, []);
  const closeFile = useCallback(() => {
    setOpenFile(null);
    setRightView("schematic");
  }, []);
  // Live mirror of `tab` for callbacks that must read the CURRENT tab without
  // re-binding (e.g. the gated setHealth handed to the always-mounted Simulation).
  const tabRef = useRef(tab);
  tabRef.current = tab;
  const [bust, setBust] = useState(0);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [health, setHealth] = useState<
    { text: string; tone: "ok" | "warn" | "err" | "neutral" } | undefined
  >(undefined);
  const [healthError, setHealthError] = useState(false);

  // Pipeline-stage state, owned here so the AgentRail (on the right) and
  // the Generator tab (in the middle) stay in lockstep.
  const [stage, setStage] = useState<StagePhase>("idle");
  const [activity, setActivity] = useState<string[]>([]);
  const [phases, setPhases] = useState<PhaseEvent[]>([]);
  const [subPhase, setSubPhase] = useState<string | undefined>(undefined);
  const pushActivity = useCallback(
    (line: string) => setActivity((prev) => [...prev, line]),
    [],
  );
  const clearActivity = useCallback(() => setActivity([]), []);

  // Simulation test-block catalog + selection, owned here so the sidebar
  // dropdown and the Simulation detail pane stay in sync.
  const [simBlocks, setSimBlocks] = useState<SimBlock[]>([]);
  const [simGroups, setSimGroups] = useState<SimGroup[]>([]);
  const [selectedSimBlock, setSelectedSimBlock] = useState<string>("");
  const refetchSimBlocks = useCallback(() => {
    api.simBlocks()
      .then((r) => {
        setSimBlocks(r.blocks);
        setSimGroups(r.groups ?? []);
        const first = r.blocks.find((b) => b.status === "implemented") ?? r.blocks[0];
        if (first) setSelectedSimBlock((s) => s || first.id);
      })
      .catch(() => {});
  }, []);
  useEffect(() => { refetchSimBlocks(); }, [refetchSimBlocks]);
  // Re-fetch the sim catalog whenever the design artifacts change (a build /
  // generate / loop bumps `bust`), so each block's staleness re-evaluates against
  // the new schematic and the "out of date" badges/banner update without a manual
  // reload. Skip the initial mount (the effect above already did the first fetch).
  const bustForSims = useRef(bust);
  useEffect(() => {
    if (bustForSims.current === bust) return;   // no-op on the priming run
    bustForSims.current = bust;
    refetchSimBlocks();
  }, [bust, refetchSimBlocks]);
  const selectSimBlock = useCallback((id: string) => {
    setSelectedSimBlock(id);
    setTab("simulation");
  }, []);

  // Recovery: on mount, ask the backend what the most recent generate run
  // looked like. If it succeeded, mark stage=done and load its phases so
  // the dropdown isn't empty after a refresh.
  useEffect(() => {
    api.runLatest("generate")
      .then((r) => {
        if (!r.present) return;
        setPhases(r.phases ?? []);
        if (r.status === "ok") {
          setStage((s) => (s === "idle" ? "done" : s));
        } else if (r.status === "fail") {
          setStage((s) => (s === "idle" ? "error" : s));
        }
      })
      .catch(() => {});
  }, []);

  // ---- Closed-loop review state (lifted from Review.tsx) ----
  // Shared with the Review tab AND the right-pane <DiffPanes> swap.
  const [activeLoopId, setActiveLoopId] = useState<string | null>(null);
  const [loopSummary, setLoopSummary] = useState<LoopSummary | null>(null);
  const [loopDiff, setLoopDiff] = useState<DiffData | null>(null);
  const [diffSheet, setDiffSheet] = useState<string | null>(null);
  const [diffMode, setDiffMode] = useState<DiffMode>("side");
  // User toggle for "force diff view in right pane". null = auto (follow
  // hasRealDiff), true = always show, false = always hide. Reset on loop
  // resolution so the next loop starts fresh.
  const [diffVisibleOverride, setDiffVisibleOverride] = useState<boolean | null>(null);
  const loopComplete = loopSummary && loopSummary.status !== "running";
  const diffActive = !!(loopComplete && activeLoopId);

  // Fetch the diff once when a loop completes; reset when activeLoopId clears.
  useEffect(() => {
    if (!diffActive || !activeLoopId) {
      setLoopDiff(null);
      setDiffSheet(null);
      setDiffVisibleOverride(null);
      return;
    }
    let cancelled = false;
    api.loopDiff(activeLoopId).then((d) => {
      if (cancelled) return;
      setLoopDiff(d);
      setDiffSheet((prev) => {
        if (prev) return prev;
        const entries = Object.entries(d.sheets);
        if (entries.length === 0) return null;
        return entries.sort((a, b) => b[1].count - a[1].count)[0][0];
      });
    }).catch(() => { /* ignore */ });
    return () => { cancelled = true; };
  }, [diffActive, activeLoopId]);

  // Auto-show diff only when there's ACTUAL content to confirm. A clean
  // all-clear loop produces a snapshot with zero sheet changes — no reason to
  // hide the schematic. The user can still force-open via the toggle.
  const hasRealDiff = !!(loopDiff && Object.values(loopDiff.sheets).some(s => s.count > 0));
  const diffVisible = diffVisibleOverride ?? hasRealDiff;

  // ---- Generator-tab diff state (before/after for a Generate run) ----
  // Mirrors the Review diff above, but the snapshot is taken at the start of a
  // Generate (apply + build) and diffed against the rebuilt result. The Generator
  // hands us the diff_id on completion (onGenDiff); we fetch + show it in the
  // right pane, auto-opening only when the run actually changed something.
  const [genDiff, setGenDiff] = useState<DiffData | null>(null);
  const [genDiffSheet, setGenDiffSheet] = useState<string | null>(null);
  const [genDiffMode, setGenDiffMode] = useState<DiffMode>("side");
  const [genDiffVisibleOverride, setGenDiffVisibleOverride] = useState<boolean | null>(null);
  const onGenDiff = useCallback((diffId: string) => {
    setGenDiffVisibleOverride(null);   // fresh run → back to auto-show
    api.loopDiff(diffId).then((d) => {
      setGenDiff(d);
      // Default the active sheet to the one with the most changes.
      const entries = Object.entries(d.sheets);
      setGenDiffSheet(entries.length
        ? entries.sort((a, b) => b[1].count - a[1].count)[0][0]
        : null);
    }).catch(() => { /* ignore — no diff shown */ });
  }, []);
  const genHasRealDiff = !!(genDiff && Object.values(genDiff.sheets).some(s => s.count > 0));
  const genDiffVisible = genDiffVisibleOverride ?? genHasRealDiff;

  const onArtifactsChanged = useCallback(() => setBust((b) => b + 1), []);
  const onRefresh = useCallback(() => {
    // Increment bust to force re-fetch of sheets/PNG in PngViewer
    setBust((b) => b + 1);
    // Increment refreshTrigger to trigger lint/freshness refresh in Generator
    setRefreshTrigger((t) => t + 1);
    // Call the backend refresh endpoint to get fresh lint/sheets/findings
    api.refresh().catch(() => {
      // Silently ignore errors; the data will be stale but not crash
    });
  }, []);

  useEffect(() => {
    api.health()
      .then(() => setHealthError(false))
      .catch(() => setHealthError(true));
  }, []);

  useEffect(() => {
    setHealth(undefined);
  }, [tab]);

  // The Simulation tab runs long-lived background work — the setup/interpret
  // `claude -p` agents stream over SSE and the sequential run() loop lives in
  // component state. Unmounting it on a tab switch would tear down those
  // subscriptions and the in-flight UI (the run keeps going on the backend, but
  // the frontend stops listening — so the sim appears to "stop"). To retain it
  // across tabs, Simulation stays PERSISTENTLY MOUNTED and is hidden with CSS
  // when another tab is active, instead of being conditionally rendered.
  const simActive = tab === "simulation";
  // Simulation stays mounted while hidden, so its run() loop keeps calling
  // setHealth as a background sim progresses. Swallow those when it isn't the
  // active tab, so a background sim doesn't overwrite another tab's status bar.
  const simSetHealth = useCallback<typeof setHealth>(
    (h) => { if (tabRef.current === "simulation") setHealth(h); },
    [setHealth],
  );
  const simPanel = (
    <Simulation
      setHealth={simSetHealth}
      blocks={simBlocks}
      selected={selectedSimBlock}
      onBlocksChanged={refetchSimBlocks}
    />
  );

  // The other tabs have no background work, so they mount on demand as usual.
  const otherContent =
    tab === "resources" ? (
      <Resources onViewPart={goToPart} onOpenFile={onOpenFile} />
    ) : tab === "library" ? (
      <Library
        initialPart={pendingPart}
        onPartConsumed={() => setPendingPart(null)}
        onOpenFile={onOpenFile}
      />
    ) : tab === "review" ? (
      <Review
        onArtifactsChanged={onArtifactsChanged}
        setHealth={setHealth}
        activeLoopId={activeLoopId}
        setActiveLoopId={setActiveLoopId}
        loopSummary={loopSummary}
        setLoopSummary={setLoopSummary}
        loopDiff={loopDiff}
        diffSheet={diffSheet}
        setDiffSheet={setDiffSheet}
        diffMode={diffMode}
        setDiffMode={setDiffMode}
        hasRealDiff={hasRealDiff}
        diffVisible={diffVisible}
        setDiffVisibleOverride={setDiffVisibleOverride}
      />
    ) : tab === "generator" ? (
      <Generator
        onArtifactsChanged={onArtifactsChanged}
        setHealth={setHealth}
        setStage={setStage}
        pushActivity={pushActivity}
        clearActivity={clearActivity}
        setPhases={setPhases}
        setSubPhase={setSubPhase}
        refreshTrigger={refreshTrigger}
        onGenDiff={onGenDiff}
      />
    ) : null;   // simulation: rendered via the persistent simPanel below

  // Center content: the active tab's content, PLUS the always-mounted Simulation
  // panel (visible only on its tab, hidden — and so taking no layout space —
  // otherwise). A `display:none` sibling keeps the subscriptions + run loop alive
  // without affecting the active tab's layout.
  const mainContent = (
    <div className="h-full min-h-0">
      {!simActive && otherContent}
      <div className={simActive ? "h-full min-h-0" : "hidden"}>{simPanel}</div>
    </div>
  );

  // Layout matrix (every tab now carries the Agent chat rail on the right):
  //   Generator/Library + pngOpen  → content | PNG | AgentRail
  //   Generator/Library + !pngOpen → content | AgentRail
  //   Review tab        + pngOpen  → content | PNG/diff | AgentRail
  //   Review tab        + !pngOpen → content | AgentRail
  const showRail =
    tab === "generator" ||
    tab === "library" ||
    tab === "simulation" ||
    tab === "resources" ||
    tab === "review";

  // The shared right pane (schematic viewer, or an opened file) now shows on
  // Generator, Review, Simulation, AND Library + Design Resources — on the
  // latter two you can open a datasheet/file to replace the schematic.
  const showPng = pngOpen;
  // On Library/Resources we never show the Review diff; the right pane is the
  // schematic OR an opened file.
  const fileTabs = tab === "library" || tab === "resources";

  // On the Simulation tab the right pane can also show the SPICE model of the
  // selected block (what's actually simulated), toggled inside the viewer.
  // Right pane is normally the PngViewer (current schematic). When the Review
  // tab has an awaiting-decision diff, replace PngViewer with DiffPanes so the
  // user sees BEFORE/AFTER (or OVERLAY) in the big canvas instead of a
  // duplicated schematic. Diff data lives here in App.tsx; controls + Accept/
  // Reject live in the Review tab content column.
  // The right pane shows a diff on the Review tab (loop diff) OR the Generator tab
  // (this-Generate before/after). Pick the active diff source by tab.
  const reviewDiffOn = tab === "review" && diffActive && !!loopDiff && diffVisible;
  const genDiffOn = tab === "generator" && !!genDiff && genDiffVisible;
  const rightPaneIsDiff = reviewDiffOn || genDiffOn;
  // Which diff data + id + sheet/mode setters the DiffPanes should bind to.
  const activeDiff = genDiffOn ? genDiff : loopDiff;
  // DiffPanes builds /api/png_snapshot/{id}/... — use the diff's own loop_id (the
  // "gen-<hex>" snapshot id for the Generator diff, the loop id for Review).
  const activeDiffId = genDiffOn ? (genDiff?.loop_id ?? "") : (activeLoopId ?? "");
  const activeDiffSheet = genDiffOn ? genDiffSheet : diffSheet;
  const setActiveDiffSheet = genDiffOn ? setGenDiffSheet : setDiffSheet;
  const activeDiffMode = genDiffOn ? genDiffMode : diffMode;
  const setActiveDiffMode = genDiffOn ? setGenDiffMode : setDiffMode;
  const showFile = fileTabs && !!openFile && rightView === "file";

  // The right pane is built so the PngViewer is mounted ONCE and never unmounts
  // on a tab switch — so its active sheet + zoom/pan are RETAINED across tabs
  // (mirrors how the Simulation panel persists). The DiffPanes overlay and the
  // file editor are layered ON TOP (PngViewer is CSS-hidden behind them) rather
  // than swapped in, which would remount it and reset the view.
  const pngView = (
    <div className="h-full flex flex-col min-h-0 relative">
      {/* Schematic | Diff toggle bar — on the Generator tab once a Generate run has
          produced a before/after diff. Auto-opens when there are real changes; this
          lets the user flip back to the plain schematic and re-open the diff. */}
      {tab === "generator" && genDiff && (
        <div className="shrink-0 flex items-center gap-1 px-2 h-9 border-b border-edge bg-rail/30">
          <button
            onClick={() => setGenDiffVisibleOverride(false)}
            className={"h-6 px-2 rounded text-[11.5px] font-medium " +
              (!genDiffOn ? "bg-ink-900 text-white" : "text-ink-600 hover:bg-rail")}
          >
            Schematic
          </button>
          <button
            onClick={() => setGenDiffVisibleOverride(true)}
            className={"h-6 px-2 rounded text-[11.5px] font-medium inline-flex items-center gap-1.5 " +
              (genDiffOn ? "bg-ink-900 text-white" : "text-ink-600 hover:bg-rail")}
            title="Before / after this Generate"
          >
            Diff
            {genHasRealDiff && (
              <span className={"text-[9.5px] px-1 rounded-full " +
                (genDiffOn ? "bg-white/25" : "bg-amber-200 text-amber-900")}>
                {Object.values(genDiff.sheets).reduce((n, s) => n + s.count, 0)}
              </span>
            )}
          </button>
          {!genHasRealDiff && (
            <span className="text-[10.5px] text-ink-400 ml-1">no schematic changes this run</span>
          )}
          <button
            onClick={() => { setGenDiff(null); setGenDiffVisibleOverride(null); }}
            className="ml-auto h-6 w-6 inline-flex items-center justify-center rounded text-ink-500 hover:bg-rail hover:text-ink-900 text-[14px] leading-none"
            title="Dismiss diff"
          >
            ✕
          </button>
        </div>
      )}
      {/* Schematic | <file> toggle bar — only on Library/Resources with a file open */}
      {openFile && fileTabs && (
        <div className="shrink-0 flex items-center gap-1 px-2 h-9 border-b border-edge bg-rail/30">
          <button
            onClick={() => setRightView("schematic")}
            className={"h-6 px-2 rounded text-[11.5px] font-medium " +
              (!showFile ? "bg-ink-900 text-white" : "text-ink-600 hover:bg-rail")}
          >
            Schematic
          </button>
          <button
            onClick={() => setRightView("file")}
            className={"h-6 px-2 rounded text-[11.5px] font-medium max-w-[260px] truncate " +
              (showFile ? "bg-ink-900 text-white" : "text-ink-600 hover:bg-rail")}
            title={openFile.name}
          >
            {openFile.title || openFile.name}
          </button>
          <button
            onClick={closeFile}
            className="ml-auto h-6 w-6 inline-flex items-center justify-center rounded text-ink-500 hover:bg-rail hover:text-ink-900 text-[14px] leading-none"
            title="Close file"
          >
            ✕
          </button>
        </div>
      )}
      <div className="flex-1 min-h-0 relative">
        {/* Always-mounted schematic — hidden (not unmounted) when a file/diff is on top. */}
        <div className={(showFile || rightPaneIsDiff) ? "hidden" : "h-full min-h-0"}>
          <PngViewer
            bust={bust}
            simMode={tab === "simulation"}
            simBlocks={simBlocks}
            selectedSimBlock={selectedSimBlock}
          />
        </div>
        {/* Diff overlay — Review loop diff OR Generator before/after diff. */}
        {rightPaneIsDiff && activeDiff && (
          <div className="h-full min-h-0">
            <DiffPanes
              loopId={activeDiffId}
              diff={activeDiff}
              activeSheet={activeDiffSheet}
              setActiveSheet={setActiveDiffSheet}
              mode={activeDiffMode}
              setMode={setActiveDiffMode}
            />
          </div>
        )}
        {/* File editor overlay (Library/Resources). */}
        {showFile && openFile && (
          <div className="h-full min-h-0">
            <Suspense fallback={<div className="h-full grid place-items-center text-[12px] text-ink-400">opening editor…</div>}>
              <ResourceEditor key={`${openFile.kind}:${openFile.name}`} file={openFile} onClose={closeFile} />
            </Suspense>
          </div>
        )}
      </div>
    </div>
  );

  // ONE splitter + ONE storageKey for the content|right split, used across all
  // tabs that show the right pane — so the divider position is RETAINED when
  // switching tabs (previously generator/review/sim and library/resources used
  // two different splitters, so the side jumped). anchor=left so the content
  // column is the stored size and the schematic grows into the gutter.
  const centerOrPair = !showPng ? (
    mainContent
  ) : (
    <Splitter
      anchor="left"
      initial={Math.round(window.innerWidth * 0.39)}
      initialFrac={0.39}
      min={420}
      max={Math.max(640, window.innerWidth - 600)}
      minOther={340}
      storageKey="test1.gui.contentSplit-v2"
      left={mainContent}
      right={pngView}
    />
  );

  const body = showRail ? (
    <Splitter
      anchor="right"
      initial={360}
      min={240}
      max={520}
      minOther={800}
      storageKey="test1.gui.agentRail"
      left={centerOrPair}
      right={
        <AgentRail
          stage={stage}
          activity={activity}
          phases={phases}
          currentSubPhase={subPhase}
        />
      }
    />
  ) : (
    centerOrPair
  );

  const main = (
    <div className="flex-1 min-w-0 h-full flex flex-col min-h-0">
      <TopBar
        title={TAB_TITLES[tab]}
        health={healthError ? { text: "backend offline", tone: "err" } : health}
        onTogglePng={() => setPngOpen((v) => !v)}
        pngOpen={pngOpen}
        canTogglePng={true}
        onRefresh={onRefresh}
      />
      <div className="flex-1 min-h-0">{body}</div>
    </div>
  );

  return (
    <div className="h-full bg-white text-ink-900">
      <Splitter
        anchor="left"
        initial={232}
        min={160}
        max={420}
        minOther={1000}
        storageKey="test1.gui.sidebar"
        left={
          <Sidebar
            active={tab}
            onChange={setTab}
            projectLabel="SCH-EVAL..."
            simBlocks={simBlocks}
            simGroups={simGroups}
            selectedSimBlock={selectedSimBlock}
            onSelectSimBlock={selectSimBlock}
          />
        }
        right={main}
      />
    </div>
  );
}
