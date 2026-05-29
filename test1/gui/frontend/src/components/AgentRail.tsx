import { useCallback, useEffect, useRef, useState } from "react";
import { api, subscribeAgent } from "../api";
import { I } from "./Icon";
import { ChangelogPanel } from "./ChangelogPanel";
import type {
  ChatMessage,
  ChatSessionMeta,
  PhaseEvent,
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
  }, [messages.length, draft, summary]);

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
        {messages.length === 0 && !draft && !summary && (
          <div className="text-xs text-ink-500 italic">
            General working session. Ask anything about the schematic, library,
            simulation, or review — it keeps context across turns. To queue a
            design change, just say so and it lands in the changelog.
          </div>
        )}
        {messages.map((m) => (
          <Bubble key={m.id} role={m.role} content={m.content} />
        ))}
        {draft && <Bubble role="assistant" content={draft} streaming />}
        {compacting && (
          <div className="text-xs text-ink-500 italic">Compacting context…</div>
        )}
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
              : "Ask about the schematic, library, sim, or review…"
          }
          rows={2}
          disabled={busy || compacting || !activeId}
          className="flex-1 resize-none text-sm border border-edge rounded-md px-2 py-1.5 focus:outline-none focus:border-ink-300 disabled:bg-rail disabled:text-ink-500"
        />
        <button
          onClick={send}
          disabled={busy || compacting || !input.trim() || !activeId}
          className="h-9 px-3 text-sm font-medium rounded-md bg-ink-900 text-white hover:bg-black disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </div>
  );
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

// Changelog UI now lives in the shared ChangelogPanel component (rendered both
// here in the rail and in the Generator tab). Imported at top of file.

