import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { Sidebar } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import { PngViewer } from "./components/PngViewer";
import { Splitter } from "./components/Splitter";
import { AgentRail } from "./components/AgentRail";
import { Generator } from "./tabs/Generator";
import { Library } from "./tabs/Library";
import { Review } from "./tabs/Review";
import { Simulation } from "./tabs/Simulation";
import type { PhaseEvent, SimBlock, StagePhase, TabKey } from "./types";

const TAB_TITLES: Record<TabKey, string> = {
  library: "Library / Bobcat Carrier",
  generator: "Schematic Generator / test1",
  review: "Design Review / test1",
  simulation: "Simulation / test1",
};

export default function App() {
  const [tab, setTab] = useState<TabKey>("generator");
  const [pngOpen, setPngOpen] = useState(true);
  const [bust, setBust] = useState(0);
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
  const [selectedSimBlock, setSelectedSimBlock] = useState<string>("");
  useEffect(() => {
    api.simBlocks()
      .then((r) => {
        setSimBlocks(r.blocks);
        const first = r.blocks.find((b) => b.status === "implemented") ?? r.blocks[0];
        if (first) setSelectedSimBlock((s) => s || first.id);
      })
      .catch(() => {});
  }, []);
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

  const onArtifactsChanged = useCallback(() => setBust((b) => b + 1), []);

  useEffect(() => {
    api.health()
      .then(() => setHealthError(false))
      .catch(() => setHealthError(true));
  }, []);

  useEffect(() => {
    setHealth(undefined);
  }, [tab]);

  const mainContent =
    tab === "library" ? (
      <Library />
    ) : tab === "simulation" ? (
      <Simulation
        setHealth={setHealth}
        blocks={simBlocks}
        selected={selectedSimBlock}
      />
    ) : tab === "review" ? (
      <Review
        onArtifactsChanged={onArtifactsChanged}
        setHealth={setHealth}
        onAutofixCompleted={() => setTab("generator")}
      />
    ) : (
      <Generator
        onArtifactsChanged={onArtifactsChanged}
        setHealth={setHealth}
        setStage={setStage}
        pushActivity={pushActivity}
        clearActivity={clearActivity}
        setPhases={setPhases}
        setSubPhase={setSubPhase}
      />
    );

  // Layout matrix:
  //   Generator/Library + pngOpen  → content | PNG | AgentRail
  //   Generator/Library + !pngOpen → content | AgentRail
  //   Review tab        + pngOpen  → content | PNG
  //   Review tab        + !pngOpen → content
  const showRail = tab === "generator" || tab === "library" || tab === "simulation";

  // The Library tab is about component symbols (rendered in its own detail
  // pane), so the full-schematic PNG inspector doesn't belong there.
  const showPng = pngOpen && tab !== "library";

  // Generator/Review/Simulation are width-capped content columns, so the
  // canvas should grow into the otherwise-dead gutter on wide screens. Splits
  // are fraction-based, so the panes scale together when the window/display
  // width changes.
  const canvasGrows = tab === "generator" || tab === "review" || tab === "simulation";
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
      right={<PngViewer bust={bust} />}
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
      right={<PngViewer bust={bust} />}
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
        canTogglePng={tab !== "library"}
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
            selectedSimBlock={selectedSimBlock}
            onSelectSimBlock={selectSimBlock}
          />
        }
        right={main}
      />
    </div>
  );
}
