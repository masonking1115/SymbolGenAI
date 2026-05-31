import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { PngViewer } from "./components/PngViewer";
import { DiffPanes, type DiffMode } from "./components/DiffPanes";
import { Splitter } from "./components/Splitter";
import { AgentRail } from "./components/AgentRail";
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

export default function App() {
  // Persist the active tab so a refresh keeps you on the tab you were on.
  const [tab, setTabRaw] = useState<TabKey>(initialTab);
  const setTab = useCallback((t: TabKey) => {
    setTabRaw(t);
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
  // Live mirror of `tab` for callbacks that must read the CURRENT tab without
  // re-binding (e.g. the gated setHealth handed to the always-mounted Simulation).
  const tabRef = useRef(tab);
  tabRef.current = tab;
  const [pngOpen, setPngOpen] = useState(true);
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
      <Resources onViewPart={goToPart} />
    ) : tab === "library" ? (
      <Library initialPart={pendingPart} onPartConsumed={() => setPendingPart(null)} />
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

  // Layout matrix:
  //   Generator/Library + pngOpen  → content | PNG | AgentRail
  //   Generator/Library + !pngOpen → content | AgentRail
  //   Review tab        + pngOpen  → content | PNG
  //   Review tab        + !pngOpen → content
  const showRail =
    tab === "generator" ||
    tab === "library" ||
    tab === "simulation" ||
    tab === "resources";

  // Library + Design Resources are about component symbols / source files, not
  // the schematic, so the full-schematic PNG inspector doesn't belong there.
  const showPng = pngOpen && tab !== "library" && tab !== "resources";

  // Generator/Review/Simulation are width-capped content columns, so the
  // canvas should grow into the otherwise-dead gutter on wide screens. Splits
  // are fraction-based, so the panes scale together when the window/display
  // width changes.
  const canvasGrows = tab === "generator" || tab === "review" || tab === "simulation";
  // On the Simulation tab the right pane can also show the SPICE model of the
  // selected block (what's actually simulated), toggled inside the viewer.
  // Right pane is normally the PngViewer (current schematic). When the Review
  // tab has an awaiting-decision diff, replace PngViewer with DiffPanes so the
  // user sees BEFORE/AFTER (or OVERLAY) in the big canvas instead of a
  // duplicated schematic. Diff data lives here in App.tsx; controls + Accept/
  // Reject live in the Review tab content column.
  const rightPaneIsDiff = tab === "review" && diffActive && !!loopDiff && diffVisible;
  const pngView = rightPaneIsDiff ? (
    <DiffPanes
      loopId={activeLoopId!}
      diff={loopDiff!}
      activeSheet={diffSheet}
      setActiveSheet={setDiffSheet}
      mode={diffMode}
      setMode={setDiffMode}
    />
  ) : (
    <PngViewer
      bust={bust}
      simMode={tab === "simulation"}
      simBlocks={simBlocks}
      selectedSimBlock={selectedSimBlock}
    />
  );
  const centerOrPair = !showPng ? (
    mainContent
  ) : canvasGrows ? (
    <Splitter
      anchor="left"
      initial={Math.min(760, Math.max(520, Math.round(window.innerWidth * 0.30)))}
      min={460}
      max={1100}
      minOther={320}
      storageKey="test1.gui.contentSplit"
      left={mainContent}
      right={pngView}
    />
  ) : (
    <Splitter
      anchor="right"
      initial={Math.round(window.innerWidth * 0.42)}
      min={340}
      max={Math.max(560, window.innerWidth - 720)}
      minOther={360}
      storageKey="test1.gui.pngSplit"
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
        canTogglePng={tab !== "library" && tab !== "resources"}
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
