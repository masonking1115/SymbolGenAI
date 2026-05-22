import React, { useEffect, useLayoutEffect, useRef, useState } from "react";

import { useChatStore, type ChatMessage } from "@/store/chatStore";

/**
 * Anchor scrolling: stay pinned to the bottom unless the user has scrolled
 * up. If they have, suppress auto-scroll until they jump back themselves.
 */
function useAutoScroll(deps: unknown[]) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const stickyRef = useRef(true);

  const onScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const slack = 24;
    stickyRef.current = el.scrollTop + el.clientHeight >= el.scrollHeight - slack;
  };

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    if (stickyRef.current) el.scrollTop = el.scrollHeight;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { containerRef, onScroll };
}

export const ChatPanel: React.FC = () => {
  const messages = useChatStore((s) => s.messages);
  const isThinking = useChatStore((s) => s.isThinking);
  const send = useChatStore((s) => s.send);
  const clear = useChatStore((s) => s.clear);

  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const { containerRef, onScroll } = useAutoScroll([messages.length, isThinking]);

  // Auto-grow textarea up to a cap.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [draft]);

  const submit = () => {
    const value = draft;
    if (!value.trim() || isThinking) return;
    setDraft("");
    void send(value);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <aside className="chat">
      <header className="chat__head">
        <div>
          <h2>AI Assistant</h2>
          <span className="chat__sub">Symbol Library copilot — stub mode</span>
        </div>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={clear}
          disabled={messages.length <= 1 && !isThinking}
          title="Clear conversation"
        >
          Clear
        </button>
      </header>

      <div
        ref={containerRef}
        className="chat__messages"
        onScroll={onScroll}
        role="log"
        aria-live="polite"
      >
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {isThinking && <ThinkingBubble />}
      </div>

      <form
        className="chat__compose"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <textarea
          ref={inputRef}
          className="chat__input"
          placeholder="Ask about the schematic, a symbol, or an uploaded datasheet…"
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="chat__compose-row">
          <span className="chat__compose-hint">
            <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> for newline
          </span>
          <button
            type="submit"
            className="btn btn--primary"
            disabled={!draft.trim() || isThinking}
          >
            {isThinking ? "Thinking…" : "Send"}
          </button>
        </div>
      </form>
    </aside>
  );
};

const MessageBubble: React.FC<{ message: ChatMessage }> = ({ message }) => (
  <div className={`msg msg--${message.role}`}>
    <div className="msg__role">
      {message.role === "user"
        ? "You"
        : message.role === "assistant"
          ? "Assistant"
          : "System"}
    </div>
    <div className="msg__body">
      <MessageContent content={message.content} />
    </div>
  </div>
);

/** Minimal renderer: preserves newlines, highlights ```code fences``` and `inline` code. */
const MessageContent: React.FC<{ content: string }> = ({ content }) => {
  // Split on ```code blocks``` first
  const parts = content.split(/(```[\s\S]*?```)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("```") && part.endsWith("```")) {
          const inner = part.slice(3, -3).replace(/^[a-zA-Z0-9]*\n/, "");
          return (
            <pre key={i} className="msg__code">
              <code>{inner}</code>
            </pre>
          );
        }
        return (
          <p key={i} className="msg__para">
            {renderInline(part)}
          </p>
        );
      })}
    </>
  );
};

function renderInline(text: string): React.ReactNode {
  const segments = text.split(/(`[^`]+`)/g);
  return segments.map((seg, i) =>
    seg.startsWith("`") && seg.endsWith("`") && seg.length > 2 ? (
      <code key={i} className="msg__inline-code">
        {seg.slice(1, -1)}
      </code>
    ) : (
      <React.Fragment key={i}>{seg}</React.Fragment>
    ),
  );
}

const ThinkingBubble: React.FC = () => (
  <div className="msg msg--assistant msg--thinking">
    <div className="msg__role">Assistant</div>
    <div className="msg__body">
      <span className="dot" />
      <span className="dot" />
      <span className="dot" />
    </div>
  </div>
);
