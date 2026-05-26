import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, subscribeAgent } from "../api";
import { I } from "./Icon";
import type {
  ChangelogItem,
  ChatMessage,
  PhaseEvent,
  StagePhase,
} from "../types";

interface Props {
  /** Current pipeline stage — owned by the Generator tab. */
  stage: StagePhase;
  /** Live tail of agent activity (apply pass or generate run). */
  activity: string[];
  /** Structured phase events from the most recent generate run, used by
   *  the details dropdown to show per-sheet progress. */
  phases?: PhaseEvent[];
  /** Optional human-readable hint about what the pipeline is doing right
   *  now (e.g. "writing fmc.kicad_sch", "kicad-cli export svg"). Shown
   *  next to the active stepper pill. */
  currentSubPhase?: string;
}

const STAGES: { key: StagePhase; label: string }[] = [
  { key: "agent-thinking", label: "Agent" },
  { key: "applying-changelog", label: "Apply" },
  { key: "generating", label: "Generate" },
  { key: "linting", label: "Lint" },
  { key: "done", label: "Done" },
];

export function AgentRail({ stage, activity, phases, currentSubPhase }: Props) {
  return (
    <div className="h-full flex flex-col bg-white border-l border-edge min-w-0">
      <div className="h-10 px-3 flex items-center gap-2 border-b border-edge shrink-0">
        <span className="text-sm font-medium text-ink-900">Agent</span>
        <span className="text-[11px] text-ink-500">
          chat · changelog · status
        </span>
      </div>

      <div className="flex-1 min-h-0 grid grid-rows-[minmax(0,1fr)_auto_auto]">
        <ChatPanel />
        <ChangelogPanel />
        <StatusPanel
          stage={stage}
          activity={activity}
          phases={phases ?? []}
          currentSubPhase={currentSubPhase}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------
function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<string>("");
  const tailRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await api.chatHistory();
      setMessages(r.messages);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (tailRef.current) tailRef.current.scrollTop = tailRef.current.scrollHeight;
  }, [messages.length, draft]);

  const send = async () => {
    const content = input.trim();
    if (!content || busy) return;
    setBusy(true);
    setDraft("");
    setInput("");
    // Optimistic user echo so the UI doesn't feel laggy.
    setMessages((prev) => [
      ...prev,
      { id: "tmp", role: "user", content, ts: Date.now() / 1000 },
    ]);
    try {
      const { run_id } = await api.chatSend(content);
      subscribeAgent(
        run_id,
        (line) => setDraft((d) => (d ? d + "\n" + line : line)),
        () => {
          setBusy(false);
          setDraft("");
          // Re-pull the canonical history (with the persisted assistant turn).
          refresh();
        },
      );
    } catch (e) {
      setBusy(false);
      setMessages((prev) => [
        ...prev,
        {
          id: "err",
          role: "assistant",
          content: `(error: ${e instanceof Error ? e.message : String(e)})`,
          ts: Date.now() / 1000,
        },
      ]);
    }
  };

  return (
    <div className="min-h-0 flex flex-col border-b border-edge">
      <div className="px-3 py-2 text-[11px] uppercase tracking-wide text-ink-500 flex items-center">
        Chat
        <button
          onClick={async () => {
            await api.chatClear();
            refresh();
          }}
          className="ml-auto text-[11px] text-ink-500 hover:text-ink-900"
        >
          clear
        </button>
      </div>
      <div
        ref={tailRef}
        className="flex-1 min-h-0 overflow-auto thin-scroll px-3 py-2 space-y-2"
      >
        {messages.length === 0 && !draft && (
          <div className="text-xs text-ink-500 italic">
            Tell the agent what to change. Bullets land in the changelog —
            press Generate to apply them.
          </div>
        )}
        {messages.map((m) => (
          <Bubble key={m.id} role={m.role} content={m.content} />
        ))}
        {draft && <Bubble role="assistant" content={draft} streaming />}
      </div>
      <div className="border-t border-edge p-2 flex items-end gap-2 shrink-0">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder={
            busy
              ? "Agent is thinking…"
              : "What should change? (⌘/Ctrl+Enter to send)"
          }
          rows={2}
          disabled={busy}
          className="flex-1 resize-none text-sm border border-edge rounded-md px-2 py-1.5 focus:outline-none focus:border-ink-300 disabled:bg-rail disabled:text-ink-500"
        />
        <button
          onClick={send}
          disabled={busy || !input.trim()}
          className="h-9 px-3 text-sm font-medium rounded-md bg-ink-900 text-white hover:bg-black disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </div>
  );
}

function Bubble({
  role,
  content,
  streaming,
}: {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}) {
  const isUser = role === "user";
  return (
    <div className={"flex " + (isUser ? "justify-end" : "")}>
      <div
        className={
          "max-w-[92%] text-[13px] leading-[1.45] rounded-md px-2.5 py-1.5 whitespace-pre-wrap " +
          (isUser
            ? "bg-ink-900 text-white"
            : "bg-rail text-ink-900 border border-edge")
        }
      >
        {content}
        {streaming && <span className="text-ink-500"> ▍</span>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Changelog
// ---------------------------------------------------------------------------
function ChangelogPanel() {
  const [items, setItems] = useState<ChangelogItem[]>([]);
  const [adding, setAdding] = useState("");

  const refresh = useCallback(async () => {
    try {
      const r = await api.changelog();
      setItems(r.items);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 2500);
    return () => clearInterval(id);
  }, [refresh]);

  const add = async () => {
    const s = adding.trim();
    if (!s) return;
    await api.changelogAdd(s);
    setAdding("");
    refresh();
  };

  return (
    <div className="border-b border-edge">
      <div className="px-3 py-2 text-[11px] uppercase tracking-wide text-ink-500 flex items-center">
        Changelog
        <span className="ml-1.5 text-[11px] text-ink-500 normal-case tracking-normal">
          ({items.length} queued)
        </span>
        {items.length > 0 && (
          <button
            onClick={async () => {
              await api.changelogClear();
              refresh();
            }}
            className="ml-auto text-[11px] text-ink-500 hover:text-ink-900"
          >
            clear
          </button>
        )}
      </div>
      <div className="px-3 pb-2 max-h-[180px] overflow-auto thin-scroll">
        {items.length === 0 ? (
          <div className="text-xs text-ink-500 italic">
            No queued changes. Ask the agent for edits or add a bullet below.
          </div>
        ) : (
          <ul className="space-y-1">
            {items.map((it) => (
              <li
                key={it.id}
                className="flex items-start gap-2 text-[12.5px] group"
              >
                <span className="mt-1.5 inline-block w-1 h-1 rounded-full bg-ink-500 shrink-0" />
                <span className="flex-1 text-ink-900">{it.summary}</span>
                <span className="text-[10px] text-ink-500 font-mono mt-0.5">
                  {it.source}
                </span>
                <button
                  onClick={async () => {
                    await api.changelogDelete(it.id);
                    refresh();
                  }}
                  className="opacity-0 group-hover:opacity-100 text-ink-500 hover:text-err"
                  title="Remove"
                >
                  <I.X size={12} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="px-2 pb-2 flex gap-1">
        <input
          value={adding}
          onChange={(e) => setAdding(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") add();
          }}
          placeholder="Add a manual bullet…"
          className="flex-1 text-[12px] border border-edge rounded-md px-2 py-1 focus:outline-none focus:border-ink-300"
        />
        <button
          onClick={add}
          disabled={!adding.trim()}
          className="h-7 px-2 text-[11px] rounded-md border border-edge text-ink-700 hover:border-ink-300 disabled:opacity-50"
        >
          add
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status stepper + expandable phase details
// ---------------------------------------------------------------------------
function StatusPanel({
  stage,
  activity,
  phases,
  currentSubPhase,
}: {
  stage: StagePhase;
  activity: string[];
  phases: PhaseEvent[];
  currentSubPhase?: string;
}) {
  const activeIdx = STAGES.findIndex((s) => s.key === stage);
  const [open, setOpen] = useState(true);

  const grouped = useMemo(() => groupPhases(phases), [phases]);
  const isRunning = stage !== "idle" && stage !== "done" && stage !== "error";

  return (
    <div>
      <div className="px-3 py-2 text-[11px] uppercase tracking-wide text-ink-500 flex items-center">
        Status
        {isRunning && currentSubPhase && (
          <span className="ml-2 text-ink-700 normal-case tracking-normal font-mono text-[11px] truncate max-w-[60%]">
            · {currentSubPhase}
          </span>
        )}
        <button
          onClick={() => setOpen((v) => !v)}
          className="ml-auto text-[11px] text-ink-500 hover:text-ink-900 flex items-center gap-1"
        >
          {open ? "hide details" : "show details"}
          <span
            className={
              "transition-transform inline-block " +
              (open ? "rotate-180" : "rotate-0")
            }
          >
            <I.Caret size={12} />
          </span>
        </button>
      </div>
      <div className="px-3 pb-2 flex items-center gap-1">
        {STAGES.map((s, i) => {
          const isActive = s.key === stage;
          const isPast =
            (stage === "done" && s.key !== "done") ||
            (activeIdx !== -1 && i < activeIdx);
          const isErr = stage === "error" && i <= Math.max(activeIdx, 0);
          return (
            <div key={s.key} className="flex items-center gap-1">
              <span
                className={
                  "inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-medium " +
                  (isErr
                    ? "bg-err/10 text-err"
                    : isActive
                    ? "bg-ink-900 text-white"
                    : isPast
                    ? "bg-ok/10 text-ok"
                    : "bg-edge text-ink-500")
                }
              >
                {isPast ? <I.Check size={10} /> : isActive && isRunning ? (
                  <span className="inline-block w-1.5 h-1.5 bg-white rounded-full animate-pulse" />
                ) : (
                  i + 1
                )}
              </span>
              <span
                className={
                  "text-[11px] " +
                  (isActive
                    ? "text-ink-900 font-medium"
                    : isPast
                    ? "text-ok"
                    : "text-ink-500")
                }
              >
                {s.label}
              </span>
              {i < STAGES.length - 1 && (
                <span className="text-ink-300 mx-1">›</span>
              )}
            </div>
          );
        })}
      </div>

      {open && (
        <div className="px-3 pb-3 space-y-2">
          {/* Per-phase grouped summary from the structured phase classifier */}
          {grouped.length > 0 && (
            <div className="border border-edge rounded-md bg-white text-[11.5px]">
              {grouped.map((g, gi) => (
                <PhaseGroup key={gi} group={g} />
              ))}
            </div>
          )}

          {/* Raw live activity log (always visible, useful while running) */}
          <div className="border border-edge rounded-md bg-[#0F1115] text-[#D6DAE0] max-h-[180px] min-h-[64px] overflow-auto thin-scroll px-2.5 py-1.5 font-mono text-[11px] leading-[1.45]">
            {activity.length === 0 ? (
              <span className="text-ink-500 italic">
                {stage === "idle" ? "Idle." : "…"}
              </span>
            ) : (
              activity.slice(-200).map((l, i) => (
                <div key={i} className="whitespace-pre-wrap">
                  {l}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** A run's phase events grouped by header / phase boundary so the
 *  dropdown can show "Phase 1 loading", "Phase 2a deterministic-rules",
 *  "kicad-cli", etc. each as a collapsible block of children. */
interface PhaseGroupT {
  title: string;
  tone: "ok" | "warn" | "err" | "neutral";
  items: { text: string; tone: "ok" | "warn" | "err" | "neutral" }[];
}

function groupPhases(events: PhaseEvent[]): PhaseGroupT[] {
  const out: PhaseGroupT[] = [];
  const ensure = (title: string): PhaseGroupT => {
    const last = out[out.length - 1];
    if (last && last.items.length === 0 && last.title === title) return last;
    const g: PhaseGroupT = { title, tone: "neutral", items: [] };
    out.push(g);
    return g;
  };
  let current: PhaseGroupT | undefined;
  for (const ev of events) {
    if (ev.kind === "header") {
      current = ensure(ev.text);
      continue;
    }
    if (ev.kind === "phase") {
      current = ensure(ev.phase);
      current.items.push({ text: ev.text, tone: "neutral" });
      continue;
    }
    if (!current) current = ensure("output");
    let tone: "ok" | "warn" | "err" | "neutral" = "neutral";
    let text = (ev as { text: string }).text;
    if (ev.kind === "sheet") {
      const lintBit = ev.lint ? ` — ${ev.lint}` : "";
      text = `${ev.sheet}${lintBit}`;
      tone = ev.lint.startsWith("0E/")
        ? "ok"
        : ev.lint.includes("ERROR")
        ? "err"
        : "neutral";
    } else if (ev.kind === "error") {
      tone = "err";
      current.tone = "err";
    } else if (ev.kind === "lint") {
      tone = ev.text.includes("ERROR")
        ? "err"
        : ev.text.includes("WARNING")
        ? "warn"
        : "neutral";
    }
    current.items.push({ text, tone });
  }
  return out;
}

function PhaseGroup({ group }: { group: PhaseGroupT }) {
  const [expanded, setExpanded] = useState(group.tone === "err");
  const toneBg =
    group.tone === "err"
      ? "bg-err/[0.04]"
      : group.tone === "warn"
      ? "bg-warn/[0.04]"
      : "";
  return (
    <div className={"border-b border-edge last:border-b-0 " + toneBg}>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full px-2.5 py-1.5 flex items-center gap-2 text-left hover:bg-rail"
      >
        <span
          className={
            "transition-transform inline-block text-ink-500 " +
            (expanded ? "rotate-180" : "rotate-0")
          }
        >
          <I.Caret size={10} />
        </span>
        <span className="text-ink-900 font-medium text-[11.5px] truncate">
          {group.title}
        </span>
        <span className="ml-auto text-[10.5px] text-ink-500">
          {group.items.length}
        </span>
      </button>
      {expanded && (
        <div className="px-2.5 pb-1.5 space-y-0.5">
          {group.items.map((it, i) => (
            <div key={i} className="flex items-start gap-2">
              <span
                className={
                  "mt-1 inline-block w-1 h-1 rounded-full shrink-0 " +
                  (it.tone === "err"
                    ? "bg-err"
                    : it.tone === "warn"
                    ? "bg-warn"
                    : it.tone === "ok"
                    ? "bg-ok"
                    : "bg-ink-300")
                }
              />
              <span className="text-[11.5px] text-ink-700 whitespace-pre-wrap">
                {it.text}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
