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
import type { PhaseEvent, StagePhase, TabKey } from "./types";

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
      <Simulation setHealth={setHealth} />
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
  const showRail = tab === "generator" || tab === "library";
  const centerOrPair = pngOpen ? (
    <Splitter
      anchor="right"
      initial={Math.round(window.innerWidth * 0.40)}
      min={280}
      max={Math.max(400, window.innerWidth - 720)}
      storageKey="test1.gui.pngSplit"
      left={mainContent}
      right={<PngViewer bust={bust} />}
    />
  ) : (
    mainContent
  );

  const body = showRail ? (
    <Splitter
      anchor="right"
      initial={360}
      min={240}
      max={520}
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
        storageKey="test1.gui.sidebar"
        left={<Sidebar active={tab} onChange={setTab} projectLabel="SCH-EVAL..." />}
        right={main}
      />
    </div>
  );
}
