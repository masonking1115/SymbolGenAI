import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, subscribeAgent } from "../api";
import { I } from "./Icon";
import { ChangelogPanel } from "./ChangelogPanel";
import type {
  ChatMessage,
  ChatSessionMeta,
  PhaseEvent,
  SimBlock,
  StagePhase,
} from "../types";

interface Props {
  /** Pipeline state is still owned by the Generator tab and threaded here for
   *  backward-compat, but the rail no longer renders a status tracker /
   *  activity console (the Generator tab owns the single console now). */
  stage?: StagePhase;
  activity?: string[];
  phases?: PhaseEvent[];
  currentSubPhase?: string;
}

export function AgentRail(_props: Props) {
  return (
    <div className="h-full flex flex-col bg-white border-l border-edge min-w-0">
      <div className="h-10 px-3 flex items-center gap-2 border-b border-edge shrink-0">
        <span className="text-sm font-medium text-ink-900">Agent</span>
        <span className="text-[11px] text-ink-500">
          chat · changelog
        </span>
      </div>

      <div className="flex-1 min-h-0 grid grid-rows-[minmax(0,1fr)_auto]">
        <ChatPanel />
        <ChangelogPanel />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------
function ChatPanel() {
  const [sessions, setSessions] = useState<ChatSessionMeta[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [summary, setSummary] = useState<string | null>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);

  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [compacting, setCompacting] = useState(false);
  const [draft, setDraft] = useState<string>("");

  const [pickerOpen, setPickerOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [renameVal, setRenameVal] = useState("");

  // Slash-command palette: open when the input is a "/..." prefix. `slashIdx` is
  // the keyboard-highlighted row.
  const [slashIdx, setSlashIdx] = useState(0);
  // Inline action panel under the thread: pick a sim (block→type) or a review
  // mode before firing the existing endpoints. Null when no panel is open.
  const [panel, setPanel] = useState<null | "sim" | "review">(null);
  // Local-only "action result" cards appended to the thread (sim/review launched
  // from chat). Kept client-side (not persisted to the session transcript) and
  // merged into the rendered stream by timestamp.
  const [cards, setCards] = useState<ActionCard[]>([]);
  // Sim blocks for the /sim picker (loaded lazily on first open).
  const [simBlocks, setSimBlocks] = useState<SimBlock[] | null>(null);
  // Live effort level for the chat agent (so /effort can echo + toggle).
  const [chatEffort, setChatEffort] = useState<string>("medium");

  const tailRef = useRef<HTMLDivElement>(null);

  const loadSessionList = useCallback(async () => {
    const r = await api.chatSessions();
    setSessions(r.sessions);
    return r;
  }, []);

  const loadSession = useCallback(async (id: string) => {
    try {
      const s = await api.chatSession(id);
      setMessages(s.messages);
      setSummary(s.summary);
    } catch {
      // ignore
    }
  }, []);

  // Mount: pull the session list and land on the default session.
  useEffect(() => {
    (async () => {
      try {
        const r = await loadSessionList();
        const initial = r.default_id ?? r.sessions[0]?.id ?? null;
        if (initial) {
          setActiveId(initial);
          await loadSession(initial);
        }
      } catch {
        // backend offline — leave empty
      }
    })();
  }, [loadSessionList, loadSession]);

  useEffect(() => {
    if (tailRef.current) tailRef.current.scrollTop = tailRef.current.scrollHeight;
  }, [messages.length, draft, summary, cards]);

  const active = sessions.find((s) => s.id === activeId);
  const closeMenus = () => {
    setPickerOpen(false);
    setMenuOpen(false);
  };

  const switchTo = async (id: string) => {
    closeMenus();
    if (id === activeId) return;
    setActiveId(id);
    setInput("");
    setDraft("");
    setMessages([]);
    setSummary(null);
    await loadSession(id);
  };

  const newSession = async () => {
    closeMenus();
    try {
      const meta = await api.chatCreateSession();
      await loadSessionList();
      await switchTo(meta.id);
    } catch {
      // ignore
    }
  };

  const setDefault = async (id: string) => {
    try {
      await api.chatSetDefault(id);
      await loadSessionList();
    } catch {
      // ignore
    }
  };

  const clearActive = async () => {
    closeMenus();
    if (!activeId) return;
    try {
      await api.chatClearSession(activeId);
      await loadSession(activeId);
      await loadSessionList();
    } catch {
      // ignore
    }
  };

  const deleteActive = async () => {
    closeMenus();
    if (!activeId) return;
    try {
      await api.chatDeleteSession(activeId);
      const r = await loadSessionList();
      const next = r.default_id ?? r.sessions[0]?.id ?? null;
      if (next) {
        setActiveId(next);
        await loadSession(next);
      } else {
        setActiveId(null);
        setMessages([]);
        setSummary(null);
      }
    } catch {
      // ignore
    }
  };

  const commitRename = async () => {
    const title = renameVal.trim();
    setRenaming(false);
    if (!activeId || !title || title === active?.title) return;
    try {
      await api.chatRenameSession(activeId, title);
      await loadSessionList();
    } catch {
      // ignore
    }
  };

  const compact = async () => {
    closeMenus();
    if (!activeId || compacting || busy) return;
    setCompacting(true);
    try {
      const { run_id } = await api.chatCompact(activeId);
      subscribeAgent(run_id, () => {}, () => {
        setCompacting(false);
        loadSession(activeId);
        loadSessionList();
      });
    } catch {
      setCompacting(false);
    }
  };

  const send = async () => {
    const content = input.trim();
    if (!content || busy || compacting || !activeId) return;
    setBusy(true);
    setDraft("");
    setInput("");
    // Optimistic user echo so the UI doesn't feel laggy.
    setMessages((prev) => [
      ...prev,
      { id: "tmp", role: "user", content, ts: Date.now() / 1000 },
    ]);
    try {
      const { run_id } = await api.chatSend(content, activeId);
      subscribeAgent(
        run_id,
        (line) => setDraft((d) => (d ? d + "\n" + line : line)),
        () => {
          setBusy(false);
          setDraft("");
          // Re-pull the canonical transcript (with the persisted assistant turn).
          loadSession(activeId);
          loadSessionList();
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

  // --- slash commands -------------------------------------------------------
  // Each command: a typed `/word`, a one-line hint, and a run() that either
  // performs an action immediately or opens an inline panel. Matching is on the
  // first token so `/effort high` still resolves to the `effort` command.
  const pushCard = (c: ActionCard) =>
    setCards((prev) => [...prev, c].slice(-30)); // bound history
  const updateCard = (id: string, patch: Partial<ActionCard>) =>
    setCards((prev) => prev.map((c) => (c.id === id ? { ...c, ...patch } : c)));

  const runSim = async (block: string, simType: string, label: string) => {
    const id = `sim-${block}-${simType}-${Math.floor(performance.now())}`;
    pushCard({ id, kind: "sim", title: label, status: "running", ts: Date.now() / 1000 });
    try {
      const r = await api.simRun(block, simType);
      const ok = r.ok;
      const detail = r.message || (r.pass_criterion ? `vs: ${r.pass_criterion}` : "");
      updateCard(id, { status: ok ? "pass" : "fail", detail, sim: r.sim_type, block: r.block });
    } catch (e) {
      updateCard(id, { status: "error", detail: e instanceof Error ? e.message : String(e) });
    }
  };

  const runReview = async (mode: "review_only" | "errors" | "errors_warnings", rounds: number) => {
    const id = `rev-${mode}-${Math.floor(performance.now())}`;
    const label =
      mode === "review_only" ? "Design review (no fix)"
      : mode === "errors" ? "Auto-fix errors"
      : "Auto-fix errors + warnings";
    pushCard({ id, kind: "review", title: label, status: "running", ts: Date.now() / 1000 });
    try {
      const r = await api.loopStart(mode === "review_only" ? undefined : rounds, {
        fixWarnings: mode === "errors_warnings",
        reviewOnly: mode === "review_only",
      });
      updateCard(id, {
        status: "running",
        detail: "started — watch the Design Review tab for findings + rounds",
        loopId: r.loop_id,
      });
      // The loop runs server-side; we surface a link, not a live tail (the Review
      // tab owns that console). Flip the card to "done" once started cleanly.
      updateCard(id, { status: "started" });
    } catch (e) {
      updateCard(id, { status: "error", detail: e instanceof Error ? e.message : String(e) });
    }
  };

  const setEffort = async (level: string) => {
    try {
      await api.simSetAgentEffort("chat", level);
      setChatEffort(level);
      pushCard({
        id: `eff-${Math.floor(performance.now())}`, kind: "info",
        title: `Chat effort → ${level}`, status: "info",
        detail: level === "off" ? "extended thinking disabled" : "applies to the next chat turn",
        ts: Date.now() / 1000,
      });
    } catch {
      /* ignore */
    }
  };

  const COMMANDS: SlashCmd[] = useMemo(() => [
    { name: "sim", hint: "run a simulation (pick block + type)", run: () => { setInput(""); openSimPanel(); } },
    { name: "review", hint: "run design review / auto-fix", run: () => { setInput(""); setPanel("review"); } },
    { name: "compact", hint: "summarize + collapse this session", run: () => { setInput(""); compact(); } },
    { name: "effort", hint: "set chat thinking effort: off|low|medium|high", run: (arg?: string) => {
        setInput("");
        const lvl = (arg || "").toLowerCase();
        if (["off", "low", "medium", "high"].includes(lvl)) setEffort(lvl);
        else pushCard({ id: `eff-help-${Math.floor(performance.now())}`, kind: "info", title: "Usage: /effort off|low|medium|high", status: "info", detail: `current: ${chatEffort}`, ts: Date.now() / 1000 });
      } },
    { name: "thinking", hint: "toggle extended thinking: on|off", run: (arg?: string) => {
        setInput("");
        const a = (arg || "").toLowerCase();
        setEffort(a === "off" ? "off" : "medium");
      } },
    { name: "refresh", hint: "clear this chat (fresh session)", run: () => { setInput(""); clearActive(); } },
    { name: "default", hint: "make this the default chat session", run: () => { setInput(""); if (activeId) setDefault(activeId); } },
    { name: "help", hint: "show available commands", run: () => { setInput(""); showHelp(); } },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [activeId, chatEffort]);

  const openSimPanel = async () => {
    setPanel("sim");
    if (simBlocks === null) {
      try {
        const r = await api.simBlocks();
        setSimBlocks(r.blocks);
      } catch {
        setSimBlocks([]);
      }
    }
  };

  const showHelp = () =>
    pushCard({
      id: `help-${Math.floor(performance.now())}`, kind: "info", status: "info",
      title: "Chat commands",
      detail: COMMANDS.map((c) => `/${c.name} — ${c.hint}`).join("\n"),
      ts: Date.now() / 1000,
    });

  // The slash menu is open when the input starts with "/" and has no space yet
  // (typing the arg closes the menu but the command still runs on Enter).
  const slashQuery = input.startsWith("/") ? input.slice(1) : null;
  const slashMatches = useMemo(() => {
    if (slashQuery === null) return [];
    const q = slashQuery.split(/\s/)[0].toLowerCase();
    return COMMANDS.filter((c) => c.name.startsWith(q));
  }, [slashQuery, COMMANDS]);
  const slashOpen = slashQuery !== null && !slashQuery.includes(" ") && slashMatches.length > 0;

  // Run a "/cmd arg" string (called on Enter when input is a slash command).
  const runSlash = (raw: string) => {
    const m = raw.slice(1).match(/^(\S+)\s*(.*)$/);
    if (!m) return false;
    const [, name, arg] = m;
    const cmd = COMMANDS.find((c) => c.name === name)
      || (slashMatches.length === 1 ? slashMatches[0] : undefined);
    if (!cmd) return false;
    cmd.run(arg.trim());
    setSlashIdx(0);
    return true;
  };

  // Keystroke handler for the input: drives the slash menu + send.
  const onInputKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (slashOpen) {
      if (e.key === "ArrowDown") { e.preventDefault(); setSlashIdx((i) => Math.min(i + 1, slashMatches.length - 1)); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setSlashIdx((i) => Math.max(i - 1, 0)); return; }
      if (e.key === "Tab") { e.preventDefault(); setInput("/" + slashMatches[slashIdx].name + " "); setSlashIdx(0); return; }
      if (e.key === "Escape") { e.preventDefault(); setInput(""); return; }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        slashMatches[slashIdx].run("");
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (input.startsWith("/")) { if (runSlash(input.trim())) return; }
      send();
    }
  };

  // Load the chat agent's current effort once (for the /effort echo + label).
  useEffect(() => {
    (async () => {
      try {
        const r = await api.simAgentModels();
        const c = r.agents.find((a) => a.kind === "chat");
        if (c?.effort) setChatEffort(c.effort);
      } catch { /* optional */ }
    })();
  }, []);

  return (
    <div className="min-h-0 flex flex-col border-b border-edge">
      {/* Session header: switcher · new · actions */}
      <div className="px-2 py-1.5 border-b border-edge/70 flex items-center gap-1 relative">
        {renaming ? (
          <input
            autoFocus
            value={renameVal}
            onChange={(e) => setRenameVal(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename();
              if (e.key === "Escape") setRenaming(false);
            }}
            onBlur={commitRename}
            className="flex-1 min-w-0 text-[13px] border border-ink-300 rounded px-1.5 py-1 focus:outline-none"
          />
        ) : (
          <button
            onClick={() => {
              setMenuOpen(false);
              setPickerOpen((v) => !v);
            }}
            className="flex-1 min-w-0 flex items-center gap-1 px-1.5 py-1 rounded hover:bg-rail text-left"
            title="Switch chat session"
          >
            <span className="text-[13px] font-medium text-ink-900 truncate">
              {active?.title ?? "Chat"}
            </span>
            {active?.has_summary && (
              <span className="text-[9px] text-ink-500 border border-edge rounded px-1 leading-tight">
                compacted
              </span>
            )}
            <I.Caret size={12} className={pickerOpen ? "" : "-rotate-90 transition-transform"} />
          </button>
        )}
        <button
          onClick={newSession}
          className="p-1 rounded text-ink-500 hover:text-ink-900 hover:bg-rail shrink-0"
          title="New chat session"
        >
          <I.Plus size={15} />
        </button>
        <button
          onClick={() => {
            setPickerOpen(false);
            setMenuOpen((v) => !v);
          }}
          className="p-1 rounded text-ink-500 hover:text-ink-900 hover:bg-rail shrink-0"
          title="Session actions"
        >
          <I.Dots size={15} />
        </button>

        {(pickerOpen || menuOpen) && (
          <div className="fixed inset-0 z-10" onClick={closeMenus} />
        )}

        {/* Session picker dropdown */}
        {pickerOpen && (
          <div className="absolute left-2 top-full mt-1 z-20 w-[230px] bg-white border border-edge rounded-md shadow-lg py-1 max-h-[260px] overflow-auto thin-scroll">
            {sessions.map((s) => (
              <div
                key={s.id}
                className={
                  "flex items-center gap-1.5 px-2 py-1.5 cursor-pointer text-[13px] " +
                  (s.id === activeId ? "bg-rail" : "hover:bg-rail")
                }
                onClick={() => switchTo(s.id)}
              >
                <span className="flex-1 truncate text-ink-900">{s.title}</span>
                <span className="text-[10px] text-ink-500">{s.message_count}</span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setDefault(s.id);
                  }}
                  title={s.is_default ? "Default session" : "Set as default"}
                  className={
                    "p-0.5 rounded shrink-0 " +
                    (s.is_default
                      ? "text-ok"
                      : "text-ink-300 hover:text-ink-700")
                  }
                >
                  <I.Check size={13} />
                </button>
              </div>
            ))}
            <div className="border-t border-edge mt-1 pt-1">
              <button
                onClick={newSession}
                className="w-full flex items-center gap-1.5 px-2 py-1.5 text-[13px] text-ink-700 hover:bg-rail"
              >
                <I.Plus size={13} /> New chat
              </button>
            </div>
          </div>
        )}

        {/* Actions menu */}
        {menuOpen && (
          <div className="absolute right-2 top-full mt-1 z-20 w-[190px] bg-white border border-edge rounded-md shadow-lg py-1 text-[13px]">
            <MenuItem
              label="Compact context"
              disabled={compacting || busy}
              onClick={compact}
            />
            <MenuItem
              label={active?.is_default ? "Default session ✓" : "Set as default"}
              disabled={!activeId || active?.is_default}
              onClick={() => activeId && setDefault(activeId)}
            />
            <MenuItem
              label="Rename"
              disabled={!activeId}
              onClick={() => {
                closeMenus();
                setRenameVal(active?.title ?? "");
                setRenaming(true);
              }}
            />
            <MenuItem label="Clear messages" disabled={!activeId} onClick={clearActive} />
            <div className="border-t border-edge my-1" />
            <MenuItem label="Delete chat" danger disabled={!activeId} onClick={deleteActive} />
          </div>
        )}
      </div>

      <div
        ref={tailRef}
        className="flex-1 min-h-0 overflow-auto thin-scroll px-3 py-2 space-y-2"
      >
        {summary && (
          <div className="rounded-md border border-edge bg-rail/60 text-[12px]">
            <button
              onClick={() => setSummaryOpen((v) => !v)}
              className="w-full flex items-center gap-1.5 px-2 py-1.5 text-left text-ink-700 hover:text-ink-900"
            >
              <I.Caret size={11} className={summaryOpen ? "" : "-rotate-90 transition-transform"} />
              <span className="font-medium">Compacted context</span>
              <span className="ml-auto text-[10px] text-ink-500">summary</span>
            </button>
            {summaryOpen && (
              <div className="px-2.5 pb-2 whitespace-pre-wrap text-ink-700 leading-[1.5]">
                {summary}
              </div>
            )}
          </div>
        )}
        {messages.length === 0 && !draft && !summary && cards.length === 0 && (
          <div className="text-xs text-ink-500 italic">
            General working session. Ask anything about the schematic, library,
            simulation, or review — it keeps context across turns. Type{" "}
            <span className="font-mono not-italic text-ink-700">/</span> for
            commands (run a sim, start a review, compact, effort…), or just say
            what you want to change and it lands in the changelog.
          </div>
        )}
        {messages.map((m) => (
          <Bubble key={m.id} role={m.role} content={m.content} />
        ))}
        {draft && <Bubble role="assistant" content={draft} streaming />}
        {cards.map((c) => (
          <ResultCard key={c.id} card={c} />
        ))}
        {compacting && (
          <div className="text-xs text-ink-500 italic">Compacting context…</div>
        )}
      </div>
      {/* Inline action panels (above the input): pick a sim or a review mode. */}
      {panel === "sim" && (
        <SimPanel
          blocks={simBlocks}
          onClose={() => setPanel(null)}
          onRun={(block, simType, label) => { setPanel(null); runSim(block, simType, label); }}
        />
      )}
      {panel === "review" && (
        <ReviewPanel
          onClose={() => setPanel(null)}
          onRun={(mode, rounds) => { setPanel(null); runReview(mode, rounds); }}
        />
      )}

      <div className="border-t border-edge p-2 flex items-end gap-2 shrink-0 relative">
        {/* Slash-command palette */}
        {slashOpen && (
          <div className="absolute left-2 right-2 bottom-full mb-1 z-20 bg-white border border-edge rounded-md shadow-lg py-1 max-h-[220px] overflow-auto thin-scroll">
            {slashMatches.map((c, i) => (
              <button
                key={c.name}
                onMouseEnter={() => setSlashIdx(i)}
                onClick={() => c.run("")}
                className={
                  "w-full text-left px-2.5 py-1.5 flex items-baseline gap-2 " +
                  (i === slashIdx ? "bg-rail" : "hover:bg-rail")
                }
              >
                <span className="font-mono text-[13px] text-ink-900">/{c.name}</span>
                <span className="text-[11px] text-ink-500 truncate">{c.hint}</span>
              </button>
            ))}
          </div>
        )}
        <textarea
          value={input}
          onChange={(e) => { setInput(e.target.value); setSlashIdx(0); }}
          onKeyDown={onInputKey}
          placeholder={
            busy
              ? "Agent is thinking…"
              : "Ask anything, or type / for commands…"
          }
          rows={2}
          disabled={busy || compacting || !activeId}
          className="flex-1 resize-none text-sm border border-edge rounded-md px-2 py-1.5 focus:outline-none focus:border-ink-300 disabled:bg-rail disabled:text-ink-500"
        />
        <button
          onClick={() => { if (input.startsWith("/")) { if (runSlash(input.trim())) return; } send(); }}
          disabled={busy || compacting || !input.trim() || !activeId}
          className="h-9 px-3 text-sm font-medium rounded-md bg-ink-900 text-white hover:bg-black disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </div>
  );
}

// A slash command: typed `/name`, a hint for the palette, and a run(arg) action.
interface SlashCmd {
  name: string;
  hint: string;
  run: (arg?: string) => void;
}

// A client-side "action result" card appended to the chat thread when a sim or
// review is launched from chat (or an info echo from /effort, /help).
interface ActionCard {
  id: string;
  kind: "sim" | "review" | "info";
  title: string;
  status: "running" | "pass" | "fail" | "started" | "error" | "info";
  detail?: string;
  ts: number;
  block?: string;
  sim?: string;
  loopId?: string;
}

function MenuItem({
  label,
  onClick,
  disabled,
  danger,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={
        "w-full text-left px-2.5 py-1.5 hover:bg-rail disabled:opacity-40 disabled:hover:bg-transparent " +
        (danger ? "text-err" : "text-ink-700")
      }
    >
      {label}
    </button>
  );
}

// Result of a sim/review launched from chat (or an /effort, /help info echo).
function ResultCard({ card }: { card: ActionCard }) {
  const dot =
    card.status === "pass" ? "bg-ok"
    : card.status === "fail" || card.status === "error" ? "bg-err"
    : card.status === "running" ? "bg-warn animate-pulse"
    : card.status === "started" ? "bg-ok"
    : "bg-ink-300";
  const statusText =
    card.status === "pass" ? "PASS"
    : card.status === "fail" ? "FAIL"
    : card.status === "error" ? "error"
    : card.status === "running" ? "running…"
    : card.status === "started" ? "started"
    : "";
  const icon = card.kind === "sim" ? "◎" : card.kind === "review" ? "✓" : "ℹ";
  return (
    <div className="rounded-md border border-edge bg-white text-[12px] px-2.5 py-1.5">
      <div className="flex items-center gap-1.5">
        <span className="text-ink-500">{icon}</span>
        <span className="font-medium text-ink-900 truncate">{card.title}</span>
        {statusText && (
          <span className="ml-auto flex items-center gap-1 text-[11px] text-ink-500">
            <span className={"inline-block w-1.5 h-1.5 rounded-full " + dot} />
            {statusText}
          </span>
        )}
      </div>
      {card.detail && (
        <div className="mt-1 text-ink-700 leading-[1.4] whitespace-pre-wrap">{card.detail}</div>
      )}
      {card.kind === "review" && card.status === "started" && (
        <div className="mt-1 text-[11px] text-ink-500">
          See the <span className="font-medium">Design Review</span> tab for live
          rounds + findings.
        </div>
      )}
    </div>
  );
}

// /sim panel: choose an implemented block, then one of its implemented sim types.
function SimPanel({
  blocks,
  onClose,
  onRun,
}: {
  blocks: SimBlock[] | null;
  onClose: () => void;
  onRun: (block: string, simType: string, label: string) => void;
}) {
  const runnable = (blocks ?? []).filter((b) => b.status === "implemented");
  const [blockId, setBlockId] = useState<string>("");
  const block = runnable.find((b) => b.id === blockId);
  const simTypes = (block?.sim_types ?? []).filter((s) => s.status === "implemented");
  const [simType, setSimType] = useState<string>("");

  // Default to the first runnable block + its first sim type once loaded.
  useEffect(() => {
    if (!blockId && runnable.length) setBlockId(runnable[0].id);
  }, [runnable, blockId]);
  useEffect(() => {
    setSimType(simTypes[0]?.type ?? "");
  }, [blockId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="border-t border-edge bg-rail/60 px-2.5 py-2 space-y-2 shrink-0">
      <div className="flex items-center gap-1.5">
        <span className="text-[12px] font-medium text-ink-900">Run a simulation</span>
        <button onClick={onClose} className="ml-auto text-ink-500 hover:text-ink-900" title="Cancel">
          <I.X size={14} />
        </button>
      </div>
      {blocks === null ? (
        <div className="text-[12px] text-ink-500 italic">Loading blocks…</div>
      ) : runnable.length === 0 ? (
        <div className="text-[12px] text-ink-500 italic">No runnable sim blocks.</div>
      ) : (
        <>
          <select
            value={blockId}
            onChange={(e) => setBlockId(e.target.value)}
            className="w-full text-[12px] border border-edge rounded px-1.5 py-1 bg-white"
          >
            {runnable.map((b) => (
              <option key={b.id} value={b.id}>{b.title}</option>
            ))}
          </select>
          <select
            value={simType}
            onChange={(e) => setSimType(e.target.value)}
            disabled={!simTypes.length}
            className="w-full text-[12px] border border-edge rounded px-1.5 py-1 bg-white disabled:text-ink-500"
          >
            {simTypes.length ? (
              simTypes.map((s) => (
                <option key={s.type} value={s.type}>{s.type}</option>
              ))
            ) : (
              <option value="">(no runnable sim types)</option>
            )}
          </select>
          <button
            onClick={() => block && simType && onRun(blockId, simType, `${block.title} · ${simType}`)}
            disabled={!block || !simType}
            className="w-full h-8 text-[12px] font-medium rounded bg-ink-900 text-white hover:bg-black disabled:opacity-50"
          >
            Run sim
          </button>
        </>
      )}
    </div>
  );
}

// /review panel: choose a mode (eval-only / fix errors / fix errors+warnings) and
// (for the fix modes) a round budget. Mirrors the Review tab's controls.
function ReviewPanel({
  onClose,
  onRun,
}: {
  onClose: () => void;
  onRun: (mode: "review_only" | "errors" | "errors_warnings", rounds: number) => void;
}) {
  const [mode, setMode] = useState<"review_only" | "errors" | "errors_warnings">("review_only");
  const [rounds, setRounds] = useState(3);
  return (
    <div className="border-t border-edge bg-rail/60 px-2.5 py-2 space-y-2 shrink-0">
      <div className="flex items-center gap-1.5">
        <span className="text-[12px] font-medium text-ink-900">Design review</span>
        <button onClick={onClose} className="ml-auto text-ink-500 hover:text-ink-900" title="Cancel">
          <I.X size={14} />
        </button>
      </div>
      <select
        value={mode}
        onChange={(e) => setMode(e.target.value as typeof mode)}
        className="w-full text-[12px] border border-edge rounded px-1.5 py-1 bg-white"
      >
        <option value="review_only">Run review only (no fixes)</option>
        <option value="errors">Auto-fix errors</option>
        <option value="errors_warnings">Auto-fix errors + warnings</option>
      </select>
      {mode !== "review_only" && (
        <label className="flex items-center gap-2 text-[12px] text-ink-700">
          Max rounds
          <input
            type="number"
            min={1}
            max={10}
            value={rounds}
            onChange={(e) => setRounds(Math.max(1, Math.min(10, Number(e.target.value) || 1)))}
            className="w-16 text-[12px] border border-edge rounded px-1.5 py-1 bg-white"
          />
        </label>
      )}
      <button
        onClick={() => onRun(mode, rounds)}
        className="w-full h-8 text-[12px] font-medium rounded bg-ink-900 text-white hover:bg-black"
      >
        {mode === "review_only" ? "Run review" : "Start"}
      </button>
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
          "max-w-[92%] text-[13px] leading-[1.45] rounded-md px-2.5 py-1.5 " +
          (isUser
            ? "bg-ink-900 text-white whitespace-pre-wrap"
            : "bg-rail text-ink-900 border border-edge")
        }
      >
        {isUser ? (
          content
        ) : (
          <ChatMarkdown content={content} />
        )}
        {streaming && <span className="text-ink-500"> ▍</span>}
      </div>
    </div>
  );
}

/** GFM markdown for assistant bubbles — tables, code, lists — styled tight to
 *  fit the narrow rail. User bubbles stay plain text (they don't author md). */
function ChatMarkdown({ content }: { content: string }) {
  return (
    <div className="chat-md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Open links in a new tab; everything else inherits .chat-md styles.
          a: ({ ...p }) => <a {...p} target="_blank" rel="noreferrer" />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

// Changelog UI now lives in the shared ChangelogPanel component (rendered both
// here in the rail and in the Generator tab). Imported at top of file.

